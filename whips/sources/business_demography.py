"""Business start-ups and closures by council (ONS business demography), shared out to seats. England & Wales.

ONS counts business births (new registrations for VAT or PAYE), deaths
(de-registrations) and active businesses by local authority each year. Births
and deaths are expressed as a share of active businesses, as ONS does.
"""

from __future__ import annotations

import io
import logging
import re

import pandas as pd
import requests

from ..metrics import MetricMeta
from .councils import apportion

log = logging.getLogger(__name__)

SOURCE_URL = "https://www.ons.gov.uk/businessindustryandtrade/business/activitysizeandlocation/datasets/businessdemographyreferencetable"
NOTE = " Council figures shared out across the constituencies each council covers."
BUSINESS_DEMOGRAPHY_METRICS = [
    MetricMeta("business_birth_rate", "New businesses (birth rate)", "jobs", "%",
               "Businesses started in the latest year as a share of active businesses (ONS business demography)." + NOTE,
               "ONS business demography", "higher_better", 1, ("business",)),
    MetricMeta("business_death_rate", "Businesses closing (death rate)", "jobs", "%",
               "Businesses that closed in the latest year as a share of active businesses (ONS business demography)." + NOTE,
               "ONS business demography", "higher_worse", 1, ("business",)),
]


def find_file(s: requests.Session) -> str:
    html = s.get(SOURCE_URL, timeout=60).text
    links = re.findall(r'href="(/file\?uri=[^"]+\.xlsx)"', html)
    if not links:
        raise LookupError("No business demography workbook on the ONS page")
    return "https://www.ons.gov.uk" + links[0]


def counts(book: pd.ExcelFile, table: str) -> tuple[pd.Series, str]:
    """Latest year's counts by area from e.g. "Table 1.1d" (the sheet holding the most recent year)."""
    raw = pd.read_excel(book, sheet_name=table, header=None)
    header = next(i for i in range(10) if pd.notna(pd.to_numeric(raw.iloc[i, 2:], errors="coerce")).any())
    years = pd.to_numeric(raw.iloc[header], errors="coerce")
    col = years.idxmax()
    t = raw.iloc[header + 1:]
    code = t[0].astype(str).str.strip()
    v = pd.to_numeric(t[col], errors="coerce")
    return pd.Series(v.values, index=code.values).dropna(), str(int(years[col]))


def latest_sheet(book: pd.ExcelFile, n: int) -> str:
    """The last lettered sheet of table n.1 (e.g. "Table 1.1d")."""
    return max(s for s in book.sheet_names if re.fullmatch(rf"Table {n}\.1[a-z]", s))


def load_business_demography(s: requests.Session, weights: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], str]:
    r = s.get(find_file(s), timeout=180)
    r.raise_for_status()
    book = pd.ExcelFile(io.BytesIO(r.content))
    births, year = counts(book, latest_sheet(book, 1))
    deaths, _ = counts(book, latest_sheet(book, 2))
    active, _ = counts(book, latest_sheet(book, 3))
    lad = lambda x: x[x.index.str.match(r"^[EW]0[6-9]\d{6}$")]  # noqa: E731
    act = apportion(lad(active), weights)
    frames = {}
    for mid, c in [("business_birth_rate", births), ("business_death_rate", deaths)]:
        f = pd.DataFrame({"num": apportion(lad(c), weights) * 100, "den": act})
        ew = "K04000001"
        f.attrs["national"] = float(c[ew] * 100 / active[ew]) if ew in c and ew in active else None
        frames[mid] = f
    return frames, year
