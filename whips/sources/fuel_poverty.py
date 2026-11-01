"""Fuel poverty (Low Income Low Energy Efficiency measure), England, from DESNZ sub-regional statistics.

DESNZ publishes the share of households in fuel poverty by parliamentary
constituency (July 2024 boundaries) and by LSOA. The latest edition is found
through the GOV.UK content API, so a new year's file is picked up automatically.
"""

from __future__ import annotations

import io
import logging
import re

import pandas as pd
import requests

from ..http import get_json
from ..metrics import MetricMeta

log = logging.getLogger(__name__)

COLLECTION = "https://www.gov.uk/api/content/government/collections/fuel-poverty-statistics"
CONTENT = "https://www.gov.uk/api/content"
SOURCE_URL = "https://www.gov.uk/government/collections/fuel-poverty-sub-regional-statistics"

FUEL_POVERTY_METRICS = [
    MetricMeta("fuel_poverty", "Households in fuel poverty", "housing", "%",
               "Share of households in fuel poverty: on a low income and living in a home rated EPC band D or below after "
               "energy costs (DESNZ Low Income Low Energy Efficiency measure, modelled estimates).",
               "DESNZ sub-regional fuel poverty", "higher_worse", 1, ("fuel_poverty",)),
]


def find_file(s: requests.Session) -> tuple[str, str]:
    """(xlsx URL, data year) of the latest sub-regional fuel poverty data tables."""
    docs = get_json(s, COLLECTION).get("links", {}).get("documents", [])
    editions = []
    for d in docs:
        m = re.search(r"sub-regional-fuel-poverty-data-(\d{4})-(\d{4})-data", d.get("base_path", ""))
        if m:
            editions.append((int(m.group(1)), int(m.group(2)), d["base_path"]))
    if not editions:
        raise LookupError("No sub-regional fuel poverty data publication found")
    _, data_year, path = max(editions)
    for a in get_json(s, CONTENT + path).get("details", {}).get("attachments", []):
        if str(a.get("url", "")).lower().endswith(".xlsx"):
            return a["url"], str(data_year)
    raise LookupError(f"No Excel file in {path}")


def read_table(xlsx: bytes, sheet: str, code_col: str) -> pd.DataFrame:
    """A data table, finding its header row; indexed by area code with households and fuel-poor households."""
    raw = pd.read_excel(io.BytesIO(xlsx), sheet_name=sheet, header=None)
    header = next(i for i in range(15) if raw.iloc[i].astype(str).str.contains(code_col, case=False).any())
    df = pd.read_excel(io.BytesIO(xlsx), sheet_name=sheet, header=header)
    code = next(c for c in df.columns if code_col.lower() in str(c).lower())
    hh = next(c for c in df.columns if str(c).strip().lower() == "number of households")
    fp = next(c for c in df.columns if "in fuel poverty" in str(c).lower())
    out = pd.DataFrame({"households": pd.to_numeric(df[hh], errors="coerce"),
                        "fuel_poor": pd.to_numeric(df[fp], errors="coerce")})
    out.index = df[code].astype(str).str.strip()
    return out.dropna()


def sheet_for(xlsx: bytes, title_word: str) -> str:
    """The sheet whose title (first cell) mentions ``title_word`` (e.g. "Constituency", "LSOA")."""
    book = pd.ExcelFile(io.BytesIO(xlsx))
    for name in book.sheet_names:
        top = pd.read_excel(book, sheet_name=name, header=None, nrows=1)
        if top.empty:
            continue
        if title_word.lower() in str(top.iloc[0, 0]).lower() and str(top.iloc[0, 0]).lower().startswith("table"):
            return name
    raise LookupError(f"No sheet about {title_word}")


def frame(t: pd.DataFrame, prefix: str) -> pd.DataFrame:
    t = t[t.index.str.startswith(prefix)]
    return pd.DataFrame({"num": t["fuel_poor"] * 100, "den": t["households"]})


def load_fuel_poverty(s: requests.Session) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], str]:
    """(seat frames, LSOA frames, data year)."""
    url, year = find_file(s)
    r = s.get(url, timeout=180)
    r.raise_for_status()
    seats = read_table(r.content, sheet_for(r.content, "Constituency"), "Constituency Code")
    lsoas = read_table(r.content, sheet_for(r.content, "LSOA"), "LSOA Code")
    return {"fuel_poverty": frame(seats, "E14")}, {"fuel_poverty": frame(lsoas, "E01")}, year
