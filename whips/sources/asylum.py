"""Asylum support and resettlement by council (Home Office immigration system statistics), shared out to seats. UK.

The Home Office's quarterly regional and local authority data give, for each
council, people in supported asylum accommodation (by type, including
contingency accommodation such as hotels), Homes for Ukraine arrivals and Afghan
resettlement. Counts are apportioned to seats by their share of each council's
neighbourhoods (England & Wales).
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

DATASET = ("https://www.gov.uk/api/content/government/statistical-data-sets/"
           "immigration-system-statistics-regional-and-local-authority-data")
SOURCE_URL = "https://www.gov.uk/government/statistical-data-sets/immigration-system-statistics-regional-and-local-authority-data"
NOTE = " Council figures shared out across the constituencies each council covers."
ASYLUM_METRICS = [
    MetricMeta("asylum_supported_per_10k", "People in asylum support per 10,000 residents", "people", "per 10,000",
               "People receiving asylum support from the Home Office (initial, dispersal and contingency accommodation, "
               "and subsistence only), per 10,000 residents (latest quarter)." + NOTE,
               "Home Office immigration statistics", "neutral", 1, ("asylum",)),
    MetricMeta("asylum_contingency_per_10k", "People in asylum hotels and other contingency accommodation per 10,000",
               "people", "per 10,000",
               "People in contingency asylum accommodation (mostly hotels) per 10,000 residents (latest quarter)." + NOTE,
               "Home Office immigration statistics", "neutral", 1, ("asylum",)),
    MetricMeta("homes_for_ukraine_per_10k", "Homes for Ukraine arrivals per 10,000 residents", "people", "per 10,000",
               "Arrivals under the Homes for Ukraine scheme since it began, per 10,000 residents." + NOTE,
               "Home Office immigration statistics", "neutral", 1, ("asylum",)),
]


def find_file(s: requests.Session) -> tuple[str, str]:
    """(URL, "as at" label) of the latest quarterly local authority dataset."""
    best = None
    for a in get_json(s, DATASET).get("details", {}).get("attachments", []):
        m = re.search(r"year ending (\w+) (\d{4})", str(a.get("title", "")))
        url = str(a.get("url", ""))
        if m and url.endswith((".ods", ".xlsx")):
            when = pd.to_datetime(f"1 {m.group(1)} {m.group(2)}")
            if best is None or when > best[0]:
                best = (when, url, f"{m.group(1)} {m.group(2)}")
    if best is None:
        raise LookupError("No local authority immigration groups dataset found")
    return best[1], best[2]


def counts(sheet: pd.DataFrame) -> pd.DataFrame:
    t = find_table(sheet, "Local authority")
    col = lambda *w: next(c for c in t.columns if all(x in c.lower() for x in w))  # noqa: E731
    code = t[col("ons code")].astype(str).str.strip()
    num = lambda c: pd.to_numeric(t[c], errors="coerce").values  # noqa: E731
    out = pd.DataFrame({
        "supported": num(col("supported asylum (total)")),
        "contingency": num(col("contingency accommodation")),
        "ukraine": num(col("homes for ukraine")),
        "population": num(next(c for c in t.columns if c.strip().lower() == "population")),
    }, index=code.values)
    return out[out.index.str.match(r"^[EWSN]\d{8}$") & ~out.index.str.match(r"^E1[0-2]")]


def seat_frames(c: pd.DataFrame, weights: pd.DataFrame) -> dict[str, pd.DataFrame]:
    frames = {}
    for mid, col in [("asylum_supported_per_10k", "supported"), ("asylum_contingency_per_10k", "contingency"),
                     ("homes_for_ukraine_per_10k", "ukraine")]:
        ok = c[c[col].notna() & c["population"].notna()]
        frames[mid] = pd.DataFrame({"num": apportion(ok[col], weights) * 10_000, "den": apportion(ok["population"], weights)})
    return frames


def load_asylum(s: requests.Session, weights: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], str]:
    url, when = find_file(s)
    r = s.get(url, timeout=180)
    r.raise_for_status()
    if url.endswith(".ods"):
        sheets = read_ods(r.content)
    else:
        sheets = pd.read_excel(io.BytesIO(r.content), sheet_name=None, header=None)
    sheet = next(v for k, v in sheets.items() if k.strip().lower().startswith("reg_02"))
    return seat_frames(counts(sheet), weights), f"As at end of {when}"
