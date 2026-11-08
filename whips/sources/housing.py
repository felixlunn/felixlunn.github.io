"""Housing affordability (ONS) and homelessness (MHCLG), by council, turned into seat figures.

* ONS house price to workplace-based earnings ratios and median house prices, by
  local authority district (England and Wales), averaged over the councils each
  seat covers (see ``councils.averaged``). National figures are ONS's England
  and Wales values.
* MHCLG statutory homelessness detailed local authority tables (England, latest
  quarter): households in temporary accommodation and households owed a
  prevention or relief duty, apportioned to seats (``councils.apportion``).
"""

from __future__ import annotations

import io
import logging
import re

import pandas as pd
import requests

from ..http import get_json
from ..history import council_periods
from ..metrics import MetricMeta
from ..ods import find_table, read_ods
from .councils import apportion, averaged

log = logging.getLogger(__name__)

ONS_PAGE = ("https://www.ons.gov.uk/peoplepopulationandcommunity/housing/datasets/"
            "ratioofhousepricetoworkplacebasedearningslowerquartileandmedian")
HOMELESS = "https://www.gov.uk/api/content/government/statistical-data-sets/live-tables-on-homelessness"
HOMELESS_PAGE = "https://www.gov.uk/government/statistical-data-sets/live-tables-on-homelessness"

AREA_NOTE = " Council-level figures, averaged over the councils the constituency covers."
AFFORDABILITY_METRICS = [
    MetricMeta("house_price_median", "Median house price", "housing", "£",
               "Median price paid for residential property (ONS, year ending September)." + AREA_NOTE,
               "ONS housing affordability", "neutral", 0, ("affordability",)),
    MetricMeta("affordability_ratio", "House price to earnings ratio", "housing", "ratio",
               "Median house price divided by median annual earnings of people working in the area (ONS)." + AREA_NOTE,
               "ONS housing affordability", "higher_worse", 1, ("affordability",)),
]
HOMELESS_METRICS = [
    MetricMeta("temp_accommodation_per_1k", "Households in temporary accommodation per 1,000", "housing", "per 1,000",
               "Households in temporary accommodation arranged by the council at the end of the latest quarter, per 1,000 "
               "households. Council figures shared out across the constituencies each council covers.",
               "MHCLG statutory homelessness", "higher_worse", 1, ("homelessness",)),
    MetricMeta("homeless_duty_per_1k", "Households owed a homelessness duty per 1,000", "housing", "per 1,000",
               "Households assessed in the latest quarter as homeless or threatened with homelessness and owed a prevention "
               "or relief duty, per 1,000 households. Council figures shared out across constituencies.",
               "MHCLG statutory homelessness", "higher_worse", 2, ("homelessness",)),
]


# --- affordability -------------------------------------------------------------------------------

def affordability_url(s: requests.Session) -> str:
    html = s.get(ONS_PAGE, timeout=60).text
    links = re.findall(r'href="(/file\?uri=[^"]+\.xlsx)"', html)
    if not links:
        raise LookupError("No affordability workbook link on the ONS page")
    return "https://www.ons.gov.uk" + links[0]


def ons_table(book: pd.ExcelFile, title: str) -> tuple[pd.DataFrame, str]:
    """The sheet whose title starts with ``title``, with its header row applied; and the latest year column."""
    for name in book.sheet_names:
        top = pd.read_excel(book, sheet_name=name, header=None, nrows=1)
        if not top.empty and str(top.iloc[0, 0]).lower().startswith(title.lower()):
            raw = pd.read_excel(book, sheet_name=name, header=None)
            header = next(i for i in range(10) if raw.iloc[i].astype(str).str.contains("code", case=False).any())
            df = raw.iloc[header + 1:].copy()
            df.columns = [str(c).strip() for c in raw.iloc[header]]
            # Year columns: "2025", "2025.0" or "Year ending Sep 2025".
            years = {c: int(m.group(1)) for c in df.columns if (m := re.search(r"\b((?:19|20)\d{2})(?:\.0)?$", c))}
            return df, max(years, key=years.get)
    raise LookupError(f"No ONS table titled {title!r}")


def year_cols(df: pd.DataFrame) -> dict[str, int]:
    """Year columns ("2025", "2025.0" or "Year ending Sep 2025") -> year."""
    return {c: int(m.group(1)) for c in df.columns if (m := re.search(r"\b((?:19|20)\d{2})(?:\.0)?$", c))}


def national_value(book: pd.ExcelFile, title: str) -> float | None:
    """The England and Wales figure from the country/region table."""
    df, year = ons_table(book, title)
    row = df[df.iloc[:, 1].astype(str).str.strip().str.lower().eq("england and wales")]
    return float(pd.to_numeric(row[year], errors="coerce").iloc[0]) if len(row) else None


def by_council(df: pd.DataFrame, year: str) -> pd.Series:
    code = next(c for c in df.columns if "local authority code" in c.lower())
    return pd.Series(pd.to_numeric(df[year], errors="coerce").values, index=df[code].astype(str).str.strip()).dropna()


def load_affordability(s: requests.Session, weights: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], str]:
    r = s.get(affordability_url(s), timeout=180)
    r.raise_for_status()
    book = pd.ExcelFile(io.BytesIO(r.content))
    frames = {}
    for mid, by_la, by_country in [
        ("house_price_median", "Table 5a", "Table 1a"),
        ("affordability_ratio", "Table 5c", "Table 1c"),
    ]:
        df, year = ons_table(book, by_la)
        nat_df, _ = ons_table(book, by_country)
        ew = nat_df[nat_df.iloc[:, 1].astype(str).str.strip().str.lower().eq("england and wales")]
        cols = sorted(year_cols(df), key=lambda c: year_cols(df)[c])
        nat_col = {y: c for c, y in year_cols(nat_df).items()}  # the country table labels years its own way

        def national(c):
            nc = nat_col.get(year_cols(df)[c])
            v = pd.to_numeric(ew[nc], errors="coerce").iloc[0] if nc is not None and len(ew) else None
            return float(v) if v is not None and pd.notna(v) else None
        years = [(str(year_cols(df)[c]), by_council(df, c), national(c)) for c in cols]
        frames[mid] = council_periods([y for y in years if len(y[1])], averaged, weights)
    return frames, f"{re.search(r'(19|20)\d{2}', year).group(0)} (house prices: year ending September)"


# --- homelessness --------------------------------------------------------------------------------

def homelessness_url(s: requests.Session) -> tuple[str, str]:
    """(URL, quarter) of the latest quarterly detailed local authority tables."""
    pat = re.compile(r"^Detailed local authority level tables: ((January|April|July|October) to \w+ \d{4})", re.I)
    found = []
    for a in get_json(s, HOMELESS).get("details", {}).get("attachments", []):
        m = pat.match(a.get("title", ""))
        if m and "accessible" not in a["title"].lower() and str(a.get("url", "")).endswith(".ods"):
            found.append((pd.to_datetime("1 " + m.group(1).split(" to ")[1]), m.group(1), a["url"]))
    if not found:
        raise LookupError("No quarterly detailed local authority homelessness tables found")
    _, quarter, url = max(found)
    return url, quarter


def homeless_counts(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Per council: households in TA, households (thousands) and households owed a duty."""
    ta = find_table(sheets["TA1"], "Organisation")
    a1 = find_table(sheets["A1"], "Organisation")
    col = lambda df, *w: next(c for c in df.columns if all(x in c.lower() for x in w))  # noqa: E731
    out = pd.DataFrame({
        "ta": pd.to_numeric(ta[col(ta, "households in ta", "total")].values, errors="coerce"),
        "households": pd.to_numeric(ta[col(ta, "households in area")].values, errors="coerce") * 1000,
    }, index=ta.iloc[:, 0].astype(str).str.strip())
    owed = pd.Series(pd.to_numeric(a1[col(a1, "owed a prevention or relief duty")].values, errors="coerce"),
                     index=a1.iloc[:, 0].astype(str).str.strip())
    out["owed"] = owed.reindex(out.index)
    return out[out.index.str.match(r"^E0[6-9]\d{6}$")]  # councils only (not England, regions)


def load_homelessness(s: requests.Session, weights: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], str]:
    url, quarter = homelessness_url(s)
    r = s.get(url, timeout=180)
    r.raise_for_status()
    c = homeless_counts(read_ods(r.content))
    hh = apportion(c["households"].dropna(), weights)
    ta, owed = apportion(c["ta"].dropna(), weights), apportion(c["owed"].dropna(), weights)
    # Councils that didn't submit leave gaps: compare only households of councils that did.
    hh_ta = apportion(c.loc[c["ta"].notna(), "households"], weights)
    hh_owed = apportion(c.loc[c["owed"].notna(), "households"], weights)
    return {
        "temp_accommodation_per_1k": pd.DataFrame({"num": ta.reindex(hh.index) * 1000, "den": hh_ta.reindex(hh.index)}),
        "homeless_duty_per_1k": pd.DataFrame({"num": owed.reindex(hh.index) * 1000, "den": hh_owed.reindex(hh.index)}),
    }, quarter
