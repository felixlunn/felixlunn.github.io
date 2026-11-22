"""Private rents by council (ONS Price Index of Private Rents), averaged over each seat's councils. England & Wales.

ONS publishes the average monthly private rent and its annual change for each
local authority every month. Seats take the average of their councils,
weighted by their neighbourhoods in each.
"""

from __future__ import annotations

import io
import logging
import re

import pandas as pd
import requests

from ..history import council_periods
from ..metrics import MetricMeta
from .councils import averaged

log = logging.getLogger(__name__)

SOURCE_URL = ("https://www.ons.gov.uk/economy/inflationandpriceindices/datasets/"
              "priceindexofprivaterentsukmonthlypricestatistics")
NOTE = " Council figures, averaged over the councils the constituency covers."
RENT_METRICS = [
    MetricMeta("rent_monthly", "Average private rent", "housing", "£",
               "Average monthly private rent, all property types (ONS Price Index of Private Rents, latest month)." + NOTE,
               "ONS private rents", "higher_worse", 0, ("rents",)),
    MetricMeta("rent_change", "Private rent rise over the year", "housing", "%",
               "Change in average private rents over the last 12 months (ONS)." + NOTE, "ONS private rents",
               "higher_worse", 1, ("rents",)),
]


def find_file(s: requests.Session) -> str:
    html = s.get(SOURCE_URL, timeout=60).text
    links = re.findall(r'href="(/file\?uri=[^"]+\.xlsx)"', html)
    if not links:
        raise LookupError("No private rents workbook on the ONS page")
    return "https://www.ons.gov.uk" + links[0]


def latest(book: pd.ExcelFile) -> tuple[pd.DataFrame, str]:
    """Latest month's rent and annual change for every area."""
    name = next(n for n in book.sheet_names if n.lower().startswith("table"))
    raw = pd.read_excel(book, sheet_name=name, header=None)
    header = next(i for i in range(10) if str(raw.iloc[i, 0]).strip().lower() == "time period")
    t = raw.iloc[header + 1:].copy()
    t.columns = [str(c).strip() for c in raw.iloc[header]]
    t["Time period"] = pd.to_datetime(t["Time period"], errors="coerce")
    month = t["Time period"].max()
    t = t[t["Time period"].eq(month)]
    out = pd.DataFrame({"rent": pd.to_numeric(t["Rental price"], errors="coerce").values,
                        "change": pd.to_numeric(t["Annual change"], errors="coerce").values},
                       index=t["Area code"].astype(str).str.strip())
    return out, month.strftime("%B %Y")


def same_month_each_year(book: pd.ExcelFile) -> list[tuple[str, pd.DataFrame]]:
    """[(month label, rents and changes by area)] for the latest month and the same month in earlier years."""
    name = next(n for n in book.sheet_names if n.lower().startswith("table"))
    raw = pd.read_excel(book, sheet_name=name, header=None)
    header = next(i for i in range(10) if str(raw.iloc[i, 0]).strip().lower() == "time period")
    t = raw.iloc[header + 1:].copy()
    t.columns = [str(c).strip() for c in raw.iloc[header]]
    t["Time period"] = pd.to_datetime(t["Time period"], errors="coerce")
    month = t["Time period"].max()
    out = []
    for when in sorted(t.loc[t["Time period"].dt.month.eq(month.month), "Time period"].dropna().unique()):
        g = t[t["Time period"].eq(when)]
        out.append((pd.Timestamp(when).strftime("%b %Y"),
                    pd.DataFrame({"rent": pd.to_numeric(g["Rental price"], errors="coerce").values,
                                  "change": pd.to_numeric(g["Annual change"], errors="coerce").values},
                                 index=g["Area code"].astype(str).str.strip())))
    return out


def load_rents(s: requests.Session, weights: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], str]:
    r = s.get(find_file(s), timeout=180)
    r.raise_for_status()
    book = pd.ExcelFile(io.BytesIO(r.content))
    _, month = latest(book)
    snaps = same_month_each_year(book)
    frames = {}
    for mid, col in [("rent_monthly", "rent"), ("rent_change", "change")]:
        years = []
        for label, t in snaps:
            uk = t[col].get("K02000001")
            years.append((label, t[col].dropna(), None if uk is None or pd.isna(uk) else float(uk)))
        frames[mid] = council_periods([y for y in years if len(y[1])], averaged, weights)
    return frames, month
