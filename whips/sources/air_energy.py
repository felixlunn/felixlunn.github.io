"""Air pollution deaths (OHID Fingertips) and renewable electricity (DESNZ), by council, turned into seat figures.

* Fraction of adult deaths attributable to fine particulate (PM2.5) air
  pollution, by council (England), averaged over the councils each seat covers.
* Renewable electricity by local authority (DESNZ regional renewable
  statistics, England & Wales here): solar PV installations per 100 households,
  apportioned to seats. (Generation per household is left out: one large plant,
  such as Drax, would be spread across every seat in its council.)
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
from .councils import apportion, averaged

log = logging.getLogger(__name__)

FINGERTIPS = "https://fingertips.phe.org.uk/api/all_data/csv/by_indicator_id"
AIR_URL = "https://fingertips.phe.org.uk/search/air%20pollution"
SOURCE_URL = AIR_URL  # build.py links each source step by SOURCE_URL
AIR_INDICATOR, COUNCILS, ENGLAND = 93861, 501, 15
RENEWABLES = "https://www.gov.uk/api/content/government/statistics/regional-renewable-statistics"
RENEWABLES_URL = "https://www.gov.uk/government/statistics/regional-renewable-statistics"

AIR_METRICS = [
    MetricMeta("air_pollution_deaths", "Deaths linked to air pollution", "environment", "%",
               "Estimated share of deaths among adults (30+) attributable to fine particulate (PM2.5) air pollution (UKHSA/OHID). "
               "Council-level figures, averaged over the councils the constituency covers.",
               "OHID Fingertips", "higher_worse", 1, ("air",)),
]
RENEWABLE_METRICS = [
    MetricMeta("solar_pv_per_100_hh", "Solar panel installations per 100 households", "environment", "per 100",
               "Solar PV installations (mostly rooftop) per 100 households (DESNZ). Council figures shared out across the "
               "constituencies each council covers.", "DESNZ renewable electricity by local authority", "higher_better", 1,
               ("renewables",)),
]


# --- air pollution ---------------------------------------------------------------------------------

def parse_air(text: str) -> tuple[pd.Series, float | None, str]:
    d = pd.read_csv(io.StringIO(text), low_memory=False)
    d = d[d["Category Type"].isna()]
    d = d[d["Time period Sortable"].eq(d["Time period Sortable"].max())].drop_duplicates(["Area Code"])
    eng = d.loc[d["Area Type"].eq("England"), "Value"]
    councils = d[~d["Area Type"].eq("England")]
    return (pd.Series(councils["Value"].values, index=councils["Area Code"].astype(str)).dropna(),
            float(eng.iloc[0]) if len(eng) else None, str(d["Time period"].iloc[0]))


def load_air(s: requests.Session, weights: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], str]:
    r = s.get(FINGERTIPS, timeout=300, params={"indicator_ids": AIR_INDICATOR, "child_area_type_id": COUNCILS,
                                              "parent_area_type_id": ENGLAND})
    r.raise_for_status()
    values, national, period = parse_air(r.text)
    from .public_health import parse_periods  # same Fingertips layout (persons, all periods)
    ps = [p for p in parse_periods(r.text) if len(p[1]) >= 0.8 * len(values)]
    return {"air_pollution_deaths": council_periods(ps, averaged, weights)}, period


# --- renewables ------------------------------------------------------------------------------------

def renewables_file(s: requests.Session) -> str:
    for a in get_json(s, RENEWABLES).get("details", {}).get("attachments", []):
        if "by local authority" in str(a.get("title", "")).lower() and str(a.get("url", "")).endswith(".xlsx"):
            return a["url"]
    raise LookupError("No renewable electricity by local authority workbook found")


def la_sheet(book: pd.ExcelFile, kind: str) -> tuple[pd.DataFrame, str]:
    """The latest year's "LA - {kind}" sheet, with its header row applied."""
    sheets = [(int(m.group(1)), n) for n in book.sheet_names if (m := re.match(rf"LA - {kind},? (\d{{4}})$", n))]
    year, name = max(sheets)
    raw = pd.read_excel(book, sheet_name=name, header=None)
    header = next(i for i in range(15) if str(raw.iloc[i, 0]).strip().lower().startswith("local authority code"))
    t = raw.iloc[header + 1:].copy()
    t.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in raw.iloc[header]]
    return t.set_index(t.columns[0]), str(year)


def column(t: pd.DataFrame, pattern: str) -> pd.Series:
    col = next(c for c in t.columns if re.search(pattern, c, re.I))
    return pd.to_numeric(t[col], errors="coerce")


def renewable_counts(book: pd.ExcelFile) -> tuple[pd.DataFrame, str]:
    sites, year = la_sheet(book, "Sites")
    out = pd.DataFrame({"households": column(sites, r"households"), "solar_sites": column(sites, r"^solar pv")})
    out.index = out.index.astype(str).str.strip()
    return out[out.index.str.match(r"^[EW]0[6-9]\d{6}$")], year


def load_renewables(s: requests.Session, weights: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], str]:
    r = s.get(renewables_file(s), timeout=180)
    r.raise_for_status()
    c, year = renewable_counts(pd.ExcelFile(io.BytesIO(r.content)))
    has = c.dropna()
    return {"solar_pv_per_100_hh": pd.DataFrame({"num": apportion(has["solar_sites"], weights) * 100,
                                                 "den": apportion(has["households"], weights)})}, year
