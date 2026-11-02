"""Parliament petitions: what each constituency is signing (petition.parliament.uk).

Every petition's JSON includes its signatures by constituency (July 2024
codes). We take open petitions with at least ``MIN_SIGNATURES`` signatures,
which cover almost all signatures, and produce:

* a metric: signatures to open petitions per 1,000 registered voters (2024
  electorate, so it covers the whole UK);
* for each seat, its most-signed petitions and those signed far more there than
  nationally, for the seat briefing.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

from ..http import get_json
from ..metrics import MetricMeta

log = logging.getLogger(__name__)

API = "https://petition.parliament.uk/petitions.json"
PETITION = "https://petition.parliament.uk/petitions/{id}"
SOURCE_URL = "https://petition.parliament.uk/"
MIN_SIGNATURES = 500
TOP = 5            # most-signed petitions kept per seat
LOCAL = 3          # petitions most over-represented in the seat
LOCAL_MIN = 50     # ...with at least this many signatures there
LOCAL_INDEX = 1.5  # ...and at least this multiple of the national signing rate

PETITION_METRICS = [
    MetricMeta("petition_signatures_per_1k", "Petition signatures per 1,000 voters", "politics", "per 1,000",
               "Signatures from the constituency to open Parliament petitions (those with 500+ signatures), per 1,000 people "
               "on the 2024 electoral register.", "UK Parliament petitions", "neutral", 0, ("petitions",)),
]


def list_open(s: requests.Session) -> list[dict]:
    """(id, title, signatures) of open petitions above the threshold."""
    out, url = [], API
    params: dict | None = {"state": "open"}
    while url:
        data = get_json(s, url, params=params)
        params = None  # the "next" link already carries the query
        for p in data.get("data", []):
            a = p["attributes"]
            if a.get("signature_count", 0) >= MIN_SIGNATURES:
                out.append({"id": p["id"], "title": a.get("action", ""), "signatures": a["signature_count"]})
        url = (data.get("links") or {}).get("next")
    return out


def by_constituency(s: requests.Session, pid: int) -> dict[str, int]:
    attrs = get_json(s, f"{PETITION.format(id=pid)}.json")["data"]["attributes"]
    return {c["ons_code"]: int(c["signature_count"]) for c in attrs.get("signatures_by_constituency") or [] if c.get("ons_code")}


def summarise(petitions: list[dict], counts: dict[int, dict[str, int]], electorate: pd.Series) -> tuple[pd.DataFrame, dict]:
    """Seat x petition signature table -> (metric frame, briefing data)."""
    table = pd.DataFrame(counts).fillna(0)  # rows: seats, columns: petition ids
    table = table.reindex(electorate.index).fillna(0) if len(electorate) else table
    total = table.sum(axis=1)
    frame = pd.DataFrame({"num": total * 1000, "den": electorate.reindex(table.index)})
    # Over-representation: the seat's share of a petition's signatures vs its share of the electorate.
    elec = electorate.reindex(table.index)
    expected = table.sum(axis=0).to_numpy()[None, :] * (elec / elec.sum()).to_numpy()[:, None]
    index = pd.DataFrame(table.to_numpy() / expected, index=table.index, columns=table.columns)
    order = {p["id"]: k for k, p in enumerate(petitions)}
    by_seat = {}
    for code in table.index:
        row, idx = table.loc[code], index.loc[code]
        top = row.sort_values(ascending=False).head(TOP)
        local = idx[(row >= LOCAL_MIN) & (idx >= LOCAL_INDEX)].sort_values(ascending=False).head(LOCAL)
        by_seat[code] = {
            "top": [[order[int(p)], int(row[p]), round(float(idx[p]), 2)] for p in top.index if row[p] > 0],
            "local": [[order[int(p)], int(row[p]), round(float(idx[p]), 2)] for p in local.index],
        }
    items = [{"id": p["id"], "title": p["title"], "signatures": p["signatures"], "url": PETITION.format(id=p["id"])} for p in petitions]
    return frame, {"items": items, "by_seat": by_seat}


def load_petitions(s: requests.Session, electorate: pd.Series, workers: int = 6) -> tuple[pd.DataFrame, dict, str]:
    petitions = list_open(s)
    with ThreadPoolExecutor(workers) as pool:
        counts = dict(zip((p["id"] for p in petitions), pool.map(lambda p: by_constituency(s, p["id"]), petitions)))
    frame, briefing = summarise(petitions, counts, electorate)
    log.info("Petitions: %d open petitions with %d+ signatures", len(petitions), MIN_SIGNATURES)
    return frame, briefing, f"{len(petitions)} open petitions"
