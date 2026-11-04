"""Community pharmacies by constituency (NHSBSA consolidated pharmaceutical list). England.

NHSBSA publishes the list of community pharmacy contracts each quarter, with
postcodes. Pharmacies are placed in seats by postcode (postcodes.io), giving
the number per 10,000 residents now and the change since the earliest list on
the portal (2022), a period of many closures.
"""

from __future__ import annotations

import io
import logging
import re

import pandas as pd
import requests

from ..http import get_json
from ..metrics import MetricMeta
from .nhs import practice_constituencies

log = logging.getLogger(__name__)

API = "https://opendata.nhsbsa.net/api/3/action"
PACKAGE = "consolidated-pharmaceutical-list"
SOURCE_URL = "https://opendata.nhsbsa.net/dataset/consolidated-pharmaceutical-list"

PHARMACY_METRICS = [
    MetricMeta("pharmacies_per_10k", "Pharmacies per 10,000 residents", "health", "per 10,000",
               "Community pharmacies located in the constituency per 10,000 residents (NHSBSA pharmaceutical list, latest quarter).",
               "NHSBSA pharmaceutical list", "higher_better", 1, ("pharmacies",)),
    MetricMeta("pharmacies_change", "Change in pharmacies since 2022", "health", "%",
               "Change in the number of community pharmacies located in the constituency since the earliest NHSBSA list (2022).",
               "NHSBSA pharmaceutical list", "higher_better", 0, ("pharmacies",)),
]


def quarter_key(name: str) -> tuple[int, int]:
    """CONSOL_PHARMACY_LIST_202526Q4 -> (2025, 4); 202606Q1 -> (2026, 1)."""
    m = re.search(r"(\d{4})\d{2}Q(\d)", name)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def lists(s: requests.Session) -> tuple[dict, dict]:
    res = [r for r in get_json(s, f"{API}/package_show", params={"id": PACKAGE})["result"]["resources"]
           if quarter_key(r["name"]) != (0, 0)]
    res.sort(key=lambda r: quarter_key(r["name"]))
    return res[0], res[-1]


def read_list(s: requests.Session, url: str) -> pd.Series:
    """Pharmacy code -> postcode."""
    r = s.get(url, timeout=120)
    r.raise_for_status()
    d = pd.read_csv(io.BytesIO(r.content), encoding="utf-8-sig", dtype=str)
    code = next(c for c in d.columns if "ODS" in c.upper() or "F_CODE" in c.upper())
    pc = next(c for c in d.columns if "POST" in c.upper())
    return pd.Series(d[pc].str.strip().values, index=d[code].str.strip().values).dropna()


def label(resource: dict) -> str:
    y, q = quarter_key(resource["name"])
    return f"{y}/{str(y + 1)[2:]} Q{q}"


def seat_frames(now: pd.Series, then: pd.Series, population: pd.Series) -> dict[str, pd.DataFrame]:
    eng = [c for c in population.index if str(c).startswith("E")]
    n = now.value_counts().reindex(eng).fillna(0)
    t = then.value_counts().reindex(eng).fillna(0)
    return {
        "pharmacies_per_10k": pd.DataFrame({"num": n * 10_000, "den": population.reindex(eng)}),
        "pharmacies_change": pd.DataFrame({"num": (n - t) * 100, "den": t.where(t > 0)}),
    }


def load_pharmacies(s: requests.Session, population: pd.Series) -> tuple[dict[str, pd.DataFrame], str]:
    first, last = lists(s)
    now, then = read_list(s, last["url"]), read_list(s, first["url"])
    seats = practice_constituencies(s, {**{f"n{k}": v for k, v in now.items()}, **{f"t{k}": v for k, v in then.items()}})
    now_seat = pd.Series({k: seats.get(f"n{k}") for k in now.index}).dropna()
    then_seat = pd.Series({k: seats.get(f"t{k}") for k in then.index}).dropna()
    log.info("Pharmacies: %d now (%d placed), %d in %s (%d placed)", len(now), len(now_seat), len(then), label(first), len(then_seat))
    return seat_frames(now_seat, then_seat, population), f"{label(last)}; change since {label(first)}"
