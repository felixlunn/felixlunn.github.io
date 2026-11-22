"""Domestic Energy Performance Certificates (EPCs) by constituency, England & Wales.

Uses the MHCLG "Get energy performance of buildings data" API, which filters
certificates by parliamentary constituency (July 2024 boundaries) and energy
rating band and reports the total count. For each seat we count certificates
lodged in the last 10 years (an EPC is valid for 10 years) in each band A-G,
which gives the share of recently assessed homes in each band.

Needs a free bearer token, supplied as the ``EPC_TOKEN`` environment variable
(a GitHub Actions secret in the deploy workflow). About 4,000 small requests;
the API allows 6,000 per 5 minutes.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pandas as pd
import requests

from ..metrics import MetricMeta

log = logging.getLogger(__name__)

API = "https://api.get-energy-performance-data.communities.gov.uk/api/domestic/search"
SOURCE_URL = "https://get-energy-performance-data.communities.gov.uk/"
SOURCE = "Energy Performance Certificates (MHCLG)"
BANDS = "ABCDEFG"
YEARS = 10

EPC_METRICS = [
    MetricMeta("epc_a_c", "Homes rated EPC A-C", "housing", "%",
               "Share of homes given an Energy Performance Certificate in the last 10 years that were rated A, B or C "
               "(each certificate counted once; homes not assessed in that time aren't included).",
               SOURCE, "higher_better", 1, ("epc",)),
    MetricMeta("epc_f_g", "Homes rated EPC F-G", "housing", "%",
               "Share of homes given an Energy Performance Certificate in the last 10 years that were rated F or G, the "
               "least efficient bands.", SOURCE, "higher_worse", 1, ("epc",)),
]


def token() -> str | None:
    t = os.environ.get("EPC_TOKEN", "").strip()
    return t or None


def count(s: requests.Session, tok: str, constituency: str, band: str, start: date, end: date) -> int:
    """Number of domestic certificates in one seat and band (404 means none)."""
    r = s.get(API, timeout=60, headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"}, params={
        "constituency[]": constituency, "efficiency_rating[]": band,
        "date_start": start.isoformat(), "date_end": end.isoformat(), "page_size": 1,
    })
    if r.status_code == 404:
        return 0
    r.raise_for_status()
    body = r.json()
    data = body.get("data")
    pagination = (data.get("pagination") if isinstance(data, dict) else None) or body.get("pagination") or {}
    if "totalRecords" not in pagination:
        raise ValueError(f"EPC API response had no totalRecords for {constituency!r} {band}")
    return int(pagination["totalRecords"])


def frames_from_counts(counts: dict[str, dict[str, int]]) -> dict[str, pd.DataFrame]:
    """{seat code: {band: n}} -> num/den frames for the EPC metrics."""
    df = pd.DataFrame.from_dict(counts, orient="index").reindex(columns=list(BANDS)).fillna(0)
    total = df.sum(axis=1)
    total = total.where(total > 0)  # no certificates: no value rather than 0%
    return {
        "epc_a_c": pd.DataFrame({"num": df[list("ABC")].sum(axis=1) * 100, "den": total}),
        "epc_f_g": pd.DataFrame({"num": df[list("FG")].sum(axis=1) * 100, "den": total}),
    }


def load_epc(s: requests.Session, seats: dict[str, str], today: date | None = None, workers: int = 6) -> tuple[dict[str, pd.DataFrame], str]:
    """Counts for every seat in England & Wales ({code: name}); returns frames and the date range."""
    tok = token()
    if not tok:
        raise RuntimeError("EPC_TOKEN is not set (add the EPC API bearer token as a repository secret)")
    end = (today or date.today()) - timedelta(days=1)  # the API rejects ranges that include today
    start = end.replace(year=end.year - YEARS)
    jobs = [(code, name, band) for code, name in seats.items() if code[:1] in "EW" for band in BANDS]

    def one(job):
        code, name, band = job
        return code, band, count(s, tok, name.strip(), band, start, end)

    counts: dict[str, dict[str, int]] = {}
    with ThreadPoolExecutor(workers) as pool:
        for code, band, n in pool.map(one, jobs):
            counts.setdefault(code, {})[band] = n
    log.info("EPC: %d seats, %d certificates", len(counts), sum(sum(v.values()) for v in counts.values()))
    return frames_from_counts(counts), f"{start.isoformat()} to {end.isoformat()}"
