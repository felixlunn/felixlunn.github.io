"""Taxpayers' incomes by constituency (HMRC Survey of Personal Incomes, Table 3.15). UK.

HMRC publishes, for each constituency, the number of income taxpayers and their
mean and median total income, and how many pay higher or additional rate.
Only people who pay income tax are counted, so low earners below the personal
allowance are not included.
"""

from __future__ import annotations

import logging
import re

import pandas as pd
import requests

from ..http import get_json
from ..metrics import MetricMeta
from ..ods import find_table, read_ods

log = logging.getLogger(__name__)

PAGE = "https://www.gov.uk/api/content/government/statistics/income-and-tax-by-parliamentary-constituency-2010-to-2011"
SOURCE_URL = "https://www.gov.uk/government/statistics/income-and-tax-by-parliamentary-constituency-2010-to-2011"

INCOME_METRICS = [
    MetricMeta("taxpayer_income_median", "Median taxpayer income", "jobs", "£",
               "Median total income (earnings, pensions, self-employment and other taxable income) of income taxpayers "
               "living in the constituency (HMRC Survey of Personal Incomes, latest tax year).",
               "HMRC income and tax by constituency", "higher_better", 0, ("income",)),
    MetricMeta("higher_rate_taxpayers", "Higher or additional rate taxpayers", "jobs", "%",
               "Share of income taxpayers paying the higher or additional rate (HMRC, latest tax year).",
               "HMRC income and tax by constituency", "neutral", 1, ("income",)),
]


def find_file(s: requests.Session) -> tuple[str, str]:
    best = None
    for a in get_json(s, PAGE).get("details", {}).get("attachments", []):
        m = re.search(r"(\d{4}) to (\d{4})", str(a.get("title", "")))
        url = str(a.get("url", ""))
        if m and url.endswith((".ods", ".xlsx")) and (best is None or m.group(2) > best[0]):
            best = (m.group(2), url, f"{m.group(1)}-{m.group(2)[2:]}")
    if best is None:
        raise LookupError("No income and tax by constituency table found")
    return best[1], best[2]


def parse(sheet: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], dict[str, float | None]]:
    t = find_table(sheet, "Parliamentary Constitu")
    col = lambda *w: next(c for c in t.columns if all(x in c.lower() for x in w))  # noqa: E731
    num = lambda c: pd.to_numeric(t[c], errors="coerce")  # noqa: E731
    code = t.iloc[:, 0].astype(str).str.strip()
    taxpayers = num(col("total income", "number"))
    median = num(col("total income", "median"))
    higher = num(col("higher rate", "number")) + num(col("additional rate", "number")).fillna(0)
    seat = code.str.match(r"^(E14|S14|W07|N05)\d{6}$")
    uk = code.eq("K02000001") | code.str.lower().eq("united kingdom")
    frames = {
        "taxpayer_income_median": pd.DataFrame({"num": median[seat].values, "den": 1.0}, index=code[seat].values),
        "higher_rate_taxpayers": pd.DataFrame({"num": (higher * 100)[seat].values, "den": taxpayers[seat].values},
                                              index=code[seat].values),
    }
    if uk.any():
        nat = float(median[uk].iloc[0])
    else:  # no UK row: the taxpayer-weighted middle of the seat medians
        d = pd.DataFrame({"m": median[seat], "w": taxpayers[seat]}).dropna().sort_values("m")
        nat = float(d["m"][d["w"].cumsum() >= d["w"].sum() / 2].iloc[0]) if len(d) else None
    national = {"taxpayer_income_median": nat}
    return frames, national


def load_income(s: requests.Session) -> tuple[dict[str, pd.DataFrame], str]:
    url, year = find_file(s)
    r = s.get(url, timeout=120)
    r.raise_for_status()
    sheets = read_ods(r.content) if url.endswith(".ods") else pd.read_excel(url, sheet_name=None, header=None)
    sheet = next(v for k, v in sheets.items() if re.search(r"3[._]15$", k.strip()))
    frames, national = parse(sheet)
    for mid, v in national.items():
        frames[mid].attrs["national"] = v
    return frames, f"Tax year {year}"
