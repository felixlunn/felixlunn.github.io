"""Personal insolvencies by constituency (Insolvency Service). England & Wales.

The Insolvency Service publishes individual insolvencies (bankruptcies, debt
relief orders and individual voluntary arrangements) by constituency each year,
as counts and rates per 10,000 adults. The latest year is used.
"""

from __future__ import annotations

import io
import logging
import re

import pandas as pd
import requests

from ..http import get_json
from ..history import with_history
from ..metrics import MetricMeta

log = logging.getLogger(__name__)

SEARCH = "https://www.gov.uk/api/search.json"
CONTENT = "https://www.gov.uk/api/content"
SOURCE_URL = "https://www.gov.uk/government/collections/individual-insolvency-statistics-releases"

INSOLVENCY_METRICS = [
    MetricMeta("insolvency_per_10k", "Personal insolvencies per 10,000 adults", "economy", "per 10,000",
               "Individual insolvencies (bankruptcies, debt relief orders and individual voluntary arrangements) a year per "
               "10,000 adults living in the constituency (Insolvency Service, latest year).", "Insolvency Service",
               "higher_worse", 1, ("debt",)),
    MetricMeta("dro_per_10k", "Debt relief orders per 10,000 adults", "economy", "per 10,000",
               "Debt relief orders (for people with low income, few assets and debts under £50,000) a year per 10,000 adults "
               "(Insolvency Service, latest year).", "Insolvency Service", "higher_worse", 1, ("debt",)),
]


def find_file(s: requests.Session) -> str:
    """Latest edition's constituency workbook, via GOV.UK search (each year is its own publication)."""
    hits = get_json(s, SEARCH, params={"q": "individual insolvencies by location age and gender england and wales",
                                       "count": 10, "fields": "link,title,public_timestamp"}).get("results", [])
    editions = sorted((h for h in hits if re.search(r"by location, age and gender.*\d{4}$", h["title"], re.I)),
                      key=lambda h: re.search(r"(\d{4})$", h["title"]).group(1), reverse=True)
    for h in editions[:5]:  # the newest may be announced but not yet published
        for a in get_json(s, CONTENT + h["link"]).get("details", {}).get("attachments", []):
            t = str(a.get("title", "")).lower()
            if "parliamentary constituency" in t and str(a.get("url", "")).endswith(".xlsx"):
                return a["url"]
    raise LookupError("No insolvencies by parliamentary constituency workbook found")


def table_years(book: pd.ExcelFile, name: str) -> dict[str, tuple[pd.Series, float | None]]:
    """{year: (values by seat, England & Wales value)} for every year in the table."""
    raw = pd.read_excel(book, sheet_name=name, header=None)
    header = next(i for i in range(15) if str(raw.iloc[i, 0]).strip() == "Code")
    t = raw.iloc[header + 1:].copy()
    t.columns = [str(c).strip().removesuffix(".0") for c in raw.iloc[header]]
    code = t["Code"].astype(str).str.strip()
    seat = code.str.match(r"^(E14|W07)\d{6}$")
    out = {}
    for year in sorted(c for c in t.columns if re.fullmatch(r"\d{4}", c)):
        v = pd.to_numeric(t[year], errors="coerce")
        ew = v[code.eq("K04000001")]
        out[year] = (pd.Series(v[seat].values, index=code[seat].values), float(ew.iloc[0]) if len(ew) and pd.notna(ew.iloc[0]) else None)
    return out


def table(book: pd.ExcelFile, name: str) -> tuple[pd.Series, str, float | None]:
    years = table_years(book, name)
    year = max(years)
    return years[year][0], year, years[year][1]


def rate_frame(n: pd.Series, rate: pd.Series) -> pd.DataFrame:
    adults = (n / rate * 10_000).where(rate > 0)
    f = pd.DataFrame({"num": n * 10_000, "den": adults})
    f.loc[rate.eq(0), ["num", "den"]] = [0.0, 1.0]  # no cases: rate 0
    return f


def load_insolvency(s: requests.Session) -> tuple[dict[str, pd.DataFrame], str]:
    r = s.get(find_file(s), timeout=120)
    r.raise_for_status()
    book = pd.ExcelFile(io.BytesIO(r.content))
    frames, year = {}, ""
    for mid, counts, rates in [("insolvency_per_10k", "Table_1a", "Table_1b"), ("dro_per_10k", "Table_3a", "Table_3b")]:
        n_years, r_years = table_years(book, counts), table_years(book, rates)
        years = sorted(set(n_years) & set(r_years))
        year = years[-1]
        periods = [(y, rate_frame(n_years[y][0], r_years[y][0]), r_years[y][1]) for y in years]
        f = periods[-1][1].copy()
        f.attrs["national"] = periods[-1][2]
        frames[mid] = with_history(f, periods)
    return frames, year
