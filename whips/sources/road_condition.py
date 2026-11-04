"""Local road condition by highway authority (DfT road condition statistics, RDC tables). England.

DfT publishes, for each local highway authority (county or unitary council),
the share of its roads where maintenance should have been considered ("red"):
A roads (RDC0120), B and C roads (RDC0120) and unclassified roads (RDC0130).
Seats take the average of the authorities they overlap.
"""

from __future__ import annotations

import logging
import re

import pandas as pd
import requests

from ..http import get_json
from ..metrics import MetricMeta
from ..ods import find_table, read_ods
from .councils import averaged, lad_to_county, upper_tier_weights

log = logging.getLogger(__name__)

DATASET = "https://www.gov.uk/api/content/government/statistical-data-sets/road-condition-statistics-data-tables-rdc"
SOURCE_URL = "https://www.gov.uk/government/statistical-data-sets/road-condition-statistics-data-tables-rdc"
TABLES = {  # metric -> (table, sheet pattern, label)
    "roads_red_a": ("rdc0120", r"A_Road", "A roads"),
    "roads_red_bc": ("rdc0120", r"B_and_C", "B and C roads"),
    "roads_red_unclassified": ("rdc0130", r"^RDC0130$", "unclassified (residential and rural) roads"),
}
NOTE = " Figures are for the highway authority (county or unitary council), averaged over those the constituency covers."
ROAD_CONDITION_METRICS = [
    MetricMeta(mid, f"{short} needing repair", "transport", "%",
               f"Share of council-managed {label} where maintenance should have been considered (rated red), latest "
               "financial year (DfT road condition statistics)." + NOTE, "DfT road condition statistics", "higher_worse", 0,
               ("roads",))
    for (mid, (_, _, label)), short in zip(TABLES.items(), ["A roads", "B and C roads", "Unclassified roads"])
]


def find_files(s: requests.Session) -> dict[str, str]:
    out = {}
    for a in get_json(s, DATASET).get("details", {}).get("attachments", []):
        url = str(a.get("url", ""))
        for table in {t for t, _, _ in TABLES.values()}:
            if url.endswith(f"/{table}.ods"):
                out[table] = url
    return out


def latest_by_authority(sheet: pd.DataFrame) -> tuple[pd.Series, str]:
    t = find_table(sheet, "ONS Area Code")
    years = [c for c in t.columns if re.match(r"FYE \d{4}", c)]
    year = years[-1]
    v = pd.to_numeric(t[year], errors="coerce")
    code = t["ONS Area Code"].astype(str).str.strip()
    keep = code.str.match(r"^E(06|08|09|10)\d{6}$") & v.notna()
    england = v[code.eq("E92000001") | t["Local Authority"].astype(str).str.strip().str.lower().eq("england")]
    s = pd.Series(v[keep].values, index=code[keep].values)
    s.attrs["national"] = float(england.iloc[0]) if len(england) else None
    return s, year


def load_road_condition(s: requests.Session, weights: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], str]:
    urls = find_files(s)
    uw = upper_tier_weights(weights, lad_to_county(s))
    books, frames, years = {}, {}, set()
    for mid, (table, pattern, _) in TABLES.items():
        if table not in urls:
            continue
        if table not in books:
            r = s.get(urls[table], timeout=120)
            r.raise_for_status()
            books[table] = read_ods(r.content)
        sheet = next(v for k, v in books[table].items() if re.search(pattern, k))
        values, year = latest_by_authority(sheet)
        f = averaged(values, uw)
        f.attrs["national"] = values.attrs.get("national")
        frames[mid] = f
        years.add(year)
    if not frames:
        raise LookupError("No road condition tables found")
    return frames, ", ".join(sorted(years))
