"""Second homes, long-term empty homes and housebuilding, by council (MHCLG), shared out to seats. England.

* Council Taxbase (October each year): dwellings on the valuation list, those
  classed as second homes, and those empty for more than six months.
* Live Table 122: net additional dwellings per year (new builds, conversions and
  changes of use, minus demolitions), averaged over the latest three years.

Council counts are apportioned to seats by the seat's share of each council's
neighbourhoods (``councils.apportion``).
"""

from __future__ import annotations

import io
import logging
import re

import pandas as pd
import requests

from ..http import get_json
from ..metrics import MetricMeta
from ..ods import find_table, read_ods
from .councils import apportion

log = logging.getLogger(__name__)

CONTENT = "https://www.gov.uk/api/content"
TAXBASE = CONTENT + "/government/collections/council-taxbase-statistics"
SUPPLY = CONTENT + "/government/statistical-data-sets/live-tables-on-net-supply-of-housing"
SOURCE_URL = "https://www.gov.uk/government/collections/council-taxbase-statistics"

NOTE = " Council figures shared out across the constituencies each council covers."
HOUSING_STOCK_METRICS = [
    MetricMeta("second_homes", "Second homes", "housing", "%",
               "Dwellings classed as second homes for council tax (furnished but no one's main residence), as a share of all "
               "dwellings (MHCLG Council Taxbase)." + NOTE, "MHCLG Council Taxbase", "higher_worse", 1, ("second_homes",)),
    MetricMeta("empty_homes_long_term", "Long-term empty homes", "housing", "%",
               "Dwellings empty for more than six months, as a share of all dwellings (MHCLG Council Taxbase)." + NOTE,
               "MHCLG Council Taxbase", "higher_worse", 1, ("second_homes",)),
    MetricMeta("net_new_homes_per_1k", "New homes per year per 1,000 dwellings", "housing", "per 1,000",
               "Net additional dwellings a year (new builds and conversions minus demolitions), averaged over the latest "
               "three years, per 1,000 existing dwellings (MHCLG Live Table 122)." + NOTE,
               "MHCLG housing supply", "neutral", 1, ("housebuilding",)),
]


def taxbase_url(s: requests.Session) -> tuple[str, str]:
    """(URL, title) of the latest local authority Council Taxbase workbook."""
    docs = sorted(get_json(s, TAXBASE).get("links", {}).get("documents", []),
                  key=lambda d: d.get("public_updated_at", ""), reverse=True)
    for d in docs[:3]:
        for a in get_json(s, CONTENT + d["base_path"]).get("details", {}).get("attachments", []):
            if "local authority level data" in str(a.get("title", "")).lower() and str(a.get("url", "")).endswith(".xlsx"):
                return a["url"], d.get("title", "")
    raise LookupError("No local authority Council Taxbase workbook found")


def taxbase_table(sheet: pd.DataFrame, number: str) -> pd.Series:
    """Totals by council code from table ``number`` (e.g. "1.01") of a wide sheet of side-by-side tables."""
    header = next(i for i in range(15) if str(sheet.iloc[i, 0]).strip() == "E-code")
    titles = sheet.iloc[header - 1]
    starts = [j for j, t in titles.items() if isinstance(t, str) and t.startswith("Table ")]
    start = next(j for j in starts if re.match(rf"Table {re.escape(number)}\b", titles[j]))
    end = next((j for j in starts if j > start), sheet.shape[1])
    total = next(j for j in range(start, end) if str(sheet.iloc[header, j]).strip().lower() == "total")
    rows = sheet.iloc[header + 1:]
    return pd.Series(pd.to_numeric(rows[total], errors="coerce").values, index=rows[1].astype(str).str.strip()).dropna()


def taxbase_counts(book: bytes) -> pd.DataFrame:
    sheet = pd.read_excel(io.BytesIO(book), sheet_name="Council Taxbase Data", header=None)
    return pd.DataFrame({"dwellings": taxbase_table(sheet, "1.01"), "second": taxbase_table(sheet, "1.11"),
                         "empty_6m": taxbase_table(sheet, "1.19")})


def supply_url(s: requests.Session) -> str:
    for a in get_json(s, SUPPLY).get("details", {}).get("attachments", []):
        if str(a.get("title", "")).lower().startswith("table 122") and str(a.get("url", "")).endswith(".ods"):
            return a["url"]
    raise LookupError("No Live Table 122 found")


def net_additions(sheet: pd.DataFrame, years: int = 3) -> tuple[pd.Series, str]:
    """Average net additional dwellings a year over the latest ``years`` years, by council; and the period."""
    t = find_table(sheet, "DCLG code")
    cols = [c for c in t.columns if re.match(r"^\d{4}-\d{2}", c)][-years:]
    code = t["Current ONS code"].astype(str).str.strip()
    vals = t[cols].apply(pd.to_numeric, errors="coerce")
    keep = code.str.match(r"^E0[6-9]\d{6}$") & vals.notna().any(axis=1)  # newer councils lack early years
    period = f"{cols[0][:7]} to {cols[-1][:7]}"
    return pd.Series(vals[keep].mean(axis=1).values, index=code[keep].values), period


def load_housing_stock(s: requests.Session, weights: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], str]:
    url, title = taxbase_url(s)
    r = s.get(url, timeout=180)
    r.raise_for_status()
    c = taxbase_counts(r.content)
    c = c[c.index.str.match(r"^E0[6-9]\d{6}$")]
    dwell = apportion(c["dwellings"], weights)
    frames = {
        "second_homes": pd.DataFrame({"num": apportion(c["second"], weights) * 100, "den": dwell}),
        "empty_homes_long_term": pd.DataFrame({"num": apportion(c["empty_6m"], weights) * 100, "den": dwell}),
    }
    period = re.sub(r" in England$", "", title) or "Council Taxbase"
    try:
        r = s.get(supply_url(s), timeout=180)
        r.raise_for_status()
        sheets = read_ods(r.content)
        net, years = net_additions(next(v for k, v in sheets.items() if re.search(r"122", k)))
        has = c.index.intersection(net.index)
        frames["net_new_homes_per_1k"] = pd.DataFrame({"num": apportion(net.reindex(has), weights) * 1000,
                                                       "den": apportion(c["dwellings"].reindex(has), weights)})
        period += f"; net additions {years}"
    except Exception as exc:  # noqa: BLE001 - keep the taxbase figures if Live Table 122 fails
        log.warning("Housing supply table failed: %s", exc)
    return frames, period
