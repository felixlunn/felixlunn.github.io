"""Election results (House of Commons Library) and current MPs (UK Parliament Members API).

* 2024 general election results by constituency, keyed by ONS code, from the
  Commons Library briefing CBP-10009.
* Current Members of the House of Commons from members-api.parliament.uk,
  matched to constituencies by name (so by-elections and defections are picked up).
"""

from __future__ import annotations

import io
import logging
import os
import re
import unicodedata

import numpy as np
import pandas as pd
import requests

from ..http import get_json
from ..metrics import ELECTION_PARTIES

log = logging.getLogger(__name__)

GE2024_RESULTS_URL = os.environ.get(
    "GE2024_RESULTS_URL",
    "https://researchbriefings.files.parliament.uk/documents/CBP-10009/HoC-GE2024-results-by-constituency.csv",
)
MEMBERS_API = "https://members-api.parliament.uk/api"


def _col(df: pd.DataFrame, *names: str) -> str | None:
    lookup = {c.strip().lower(): c for c in df.columns}
    for n in names:
        if n.lower() in lookup:
            return lookup[n.lower()]
    return None


def parse_results(df: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Return (metric num/den frames, per-seat attributes) from the Commons Library results CSV."""
    code = _col(df, "ONS ID", "ons_id", "Constituency ID")
    if code is None:
        raise ValueError("Results CSV has no ONS ID column")
    df = df.set_index(df[code].astype(str).str.strip())
    num = lambda c: pd.to_numeric(df[c].astype(str).str.replace(",", ""), errors="coerce") if c else pd.Series(np.nan, index=df.index)  # noqa: E731
    valid = num(_col(df, "Valid votes"))
    electorate = num(_col(df, "Electorate"))
    majority = num(_col(df, "Majority"))
    metrics = {
        "majority_pct": pd.DataFrame({"num": majority * 100, "den": valid}),
        "turnout": pd.DataFrame({"num": valid * 100, "den": electorate}),
    }
    for col, (mid, _label) in ELECTION_PARTIES.items():
        c = _col(df, col)
        if c:
            metrics[mid] = pd.DataFrame({"num": num(c).fillna(0) * 100, "den": valid})
    attrs = pd.DataFrame(index=df.index)
    for out, names in {
        "region": ("Region name",),
        "country": ("Country name",),
        "first_party": ("First party",),
        "second_party": ("Second party",),
        "result": ("Result",),
        "mp_first": ("Member first name",),
        "mp_last": ("Member surname",),
    }.items():
        c = _col(df, *names)
        if c:
            attrs[out] = df[c].astype(str).str.strip().replace({"nan": None})
    if "mp_first" in attrs and "mp_last" in attrs:
        attrs["mp_2024"] = (attrs.pop("mp_first").fillna("") + " " + attrs.pop("mp_last").fillna("")).str.strip()
    return metrics, attrs


def load_results(s: requests.Session) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    r = s.get(GE2024_RESULTS_URL, timeout=120)
    r.raise_for_status()
    text = r.content.decode("utf-8-sig", errors="replace")
    # Some Library CSVs have a title line before the header; find the header row.
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines[:10]) if "ONS ID" in line or "ons_id" in line.lower()), 0)
    return parse_results(pd.read_csv(io.StringIO("\n".join(lines[start:]))))


def norm_name(name: str) -> str:
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    n = n.replace("&", " and ")
    n = re.sub(r"[^a-z0-9]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def parse_members(items: list[dict]) -> list[dict]:
    out = []
    for it in items:
        v = it.get("value", it)
        hm = v.get("latestHouseMembership") or {}
        party = v.get("latestParty") or {}
        if hm.get("membershipEndDate"):
            continue
        out.append({
            "constituency": hm.get("membershipFrom"),
            "mp": v.get("nameDisplayAs"),
            "mp_id": v.get("id"),
            "party": party.get("name"),
            "party_abbr": party.get("abbreviation"),
            "party_colour": ("#" + party["backgroundColour"]) if party.get("backgroundColour") else None,
        })
    return out


def load_members(s: requests.Session) -> list[dict]:
    items, skip = [], 0
    while True:
        data = get_json(s, f"{MEMBERS_API}/Members/Search", params={
            "House": 1, "IsCurrentMember": "true", "skip": skip, "take": 20,
        })
        batch = data.get("items", [])
        items.extend(batch)
        skip += len(batch)
        if not batch or skip >= data.get("totalResults", 0):
            break
    return parse_members(items)


def match_members(members: list[dict], names: dict[str, str]) -> dict[str, dict]:
    """Map constituency code -> member record by normalised constituency name."""
    by_name = {norm_name(n): code for code, n in names.items()}
    out = {}
    for m in members:
        code = by_name.get(norm_name(m.get("constituency") or ""))
        if code:
            out[code] = m
    missing = len(names) - len(out)
    if missing:
        log.info("Members API: %d constituencies without a matched current MP (vacant or name mismatch)", missing)
    return out


GE2024_ELECTION_ID = 422  # Members API id of the 4 July 2024 general election


def parse_api_results(results: dict[str, dict]) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Turn Members API election results ({PCON code: result}) into the same shape as ``parse_results``."""
    rows, shares = {}, {}
    for code, r in results.items():
        cands = sorted(r.get("candidates") or [], key=lambda c: c.get("rankOrder") or 99)
        abbr = lambda c: ((c.get("party") or {}).get("abbreviation") or "").strip()  # noqa: E731
        valid = sum(c.get("votes") or 0 for c in cands) or r.get("turnout")
        rows[code] = {
            "valid": valid, "electorate": r.get("electorate"), "majority": r.get("majority"),
            "first_party": abbr(cands[0]) if cands else None,
            "second_party": abbr(cands[1]) if len(cands) > 1 else None,
            "result": r.get("result"),
        }
        votes: dict[str, float] = {}
        for c in cands:
            a = abbr(c)
            key = "Lab" if a.startswith("Lab") else a  # Labour and Labour Co-op count together
            votes[key] = votes.get(key, 0) + (c.get("votes") or 0)
        shares[code] = votes
    df = pd.DataFrame.from_dict(rows, orient="index")
    valid = pd.to_numeric(df["valid"], errors="coerce")
    metrics = {
        "majority_pct": pd.DataFrame({"num": pd.to_numeric(df["majority"], errors="coerce") * 100, "den": valid}),
        "turnout": pd.DataFrame({"num": valid * 100, "den": pd.to_numeric(df["electorate"], errors="coerce")}),
    }
    for col, (mid, _label) in ELECTION_PARTIES.items():
        num = pd.Series({code: v.get(col, 0) for code, v in shares.items()}, dtype=float)
        metrics[mid] = pd.DataFrame({"num": num.reindex(df.index).fillna(0) * 100, "den": valid})
    attrs = df[["first_party", "second_party", "result"]].copy()
    return metrics, attrs


def load_results_api(s: requests.Session, names: dict[str, str], workers: int = 8) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """2024 results from the UK Parliament Members API (fallback when the Commons Library file is unavailable)."""
    from concurrent.futures import ThreadPoolExecutor

    items, skip = [], 0
    while True:
        data = get_json(s, f"{MEMBERS_API}/Location/Constituency/Search", params={"skip": skip, "take": 20})
        batch = data.get("items", [])
        items.extend(it.get("value", it) for it in batch)
        skip += len(batch)
        if not batch or skip >= data.get("totalResults", 0):
            break
    by_name = {norm_name(n): code for code, n in names.items()}
    ids = {by_name[norm_name(c["name"])]: c["id"] for c in items if not c.get("endDate") and norm_name(c.get("name", "")) in by_name}

    def one(item):
        code, cid = item
        try:
            d = get_json(s, f"{MEMBERS_API}/Location/Constituency/{cid}/ElectionResult/{GE2024_ELECTION_ID}")
            return code, d.get("value", d)
        except requests.RequestException as exc:
            log.warning("No 2024 result for %s: %s", code, exc)
            return code, None

    with ThreadPoolExecutor(workers) as pool:
        results = {code: r for code, r in pool.map(one, ids.items()) if r}
    if len(results) < 600:
        raise ValueError(f"Members API returned 2024 results for only {len(results)} constituencies")
    return parse_api_results(results)
