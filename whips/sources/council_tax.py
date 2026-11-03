"""Council tax: Band D bills by billing authority (MHCLG live tables), averaged over each seat's councils. England.

"Area" Band D council tax is the full average bill for a Band D home in the
area, including county, police, fire and parish precepts. The latest year's
bill and its percentage increase are used.
"""

from __future__ import annotations

import logging
import re

import pandas as pd
import requests

from ..http import get_json
from ..metrics import MetricMeta
from ..ods import find_table, read_ods
from .councils import averaged

log = logging.getLogger(__name__)

DATASET = "https://www.gov.uk/api/content/government/statistical-data-sets/live-tables-on-council-tax"
SOURCE_URL = "https://www.gov.uk/government/statistical-data-sets/live-tables-on-council-tax"
NOTE = " Council figures, averaged over the councils the constituency covers."
COUNCIL_TAX_METRICS = [
    MetricMeta("council_tax_band_d", "Band D council tax bill", "housing", "£",
               "Average Band D council tax for the area, including county, police, fire and parish precepts (MHCLG, latest year)."
               + NOTE, "MHCLG council tax statistics", "higher_worse", 0, ("council_tax",)),
    MetricMeta("council_tax_rise", "Council tax rise this year", "housing", "%",
               "Increase in the area's average Band D council tax on the previous year (MHCLG)." + NOTE,
               "MHCLG council tax statistics", "higher_worse", 1, ("council_tax",)),
]


def find_file(s: requests.Session) -> str:
    for a in get_json(s, DATASET).get("details", {}).get("attachments", []):
        if str(a.get("title", "")).lower().startswith("band d council tax") and str(a.get("url", "")).endswith(".ods"):
            return a["url"]
    raise LookupError("No Band D council tax table found")


def latest(sheet: pd.DataFrame) -> tuple[pd.Series, float | None, str]:
    t = find_table(sheet, "Code")
    year = [c for c in t.columns if re.match(r"\d{4} to \d{4}", c)][-1]
    v = pd.to_numeric(t[year], errors="coerce")
    code = t["ONS Code"].astype(str).str.strip()
    england = v[t["Authority"].astype(str).str.strip().eq("England")]
    keep = code.str.match(r"^E0[6-9]\d{6}$") & v.notna()
    return pd.Series(v[keep].values, index=code[keep].values), (float(england.iloc[0]) if len(england) else None), year


def load_council_tax(s: requests.Session, weights: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], str]:
    r = s.get(find_file(s), timeout=120)
    r.raise_for_status()
    sheets = read_ods(r.content, only={"Area_CT", "Area_CT_(%)"})
    frames, year = {}, ""
    for mid, name in [("council_tax_band_d", "Area_CT"), ("council_tax_rise", "Area_CT_(%)")]:
        values, national, year = latest(sheets[name])
        f = averaged(values, weights)
        f.attrs["national"] = national
        frames[mid] = f
    return frames, year
