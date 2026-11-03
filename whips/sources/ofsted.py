"""Ofsted inspection outcomes of state-funded schools, by constituency. England.

Ofsted's monthly management information lists every state-funded school with
its constituency and inspection results. Since late 2025 schools get report
cards rather than a single grade, so the share uses each school's latest
single-word grade (Outstanding, Good, Requires improvement, Inadequate),
weighted by pupils; schools never given one are left out.
"""

from __future__ import annotations

import datetime
import io
import logging
import re

import pandas as pd
import requests

from ..http import get_json
from ..metrics import MetricMeta

log = logging.getLogger(__name__)

DATASET = ("https://www.gov.uk/api/content/government/statistical-data-sets/"
           "monthly-management-information-ofsteds-school-inspections-outcomes")
SOURCE_URL = "https://www.gov.uk/government/statistical-data-sets/monthly-management-information-ofsteds-school-inspections-outcomes"

OFSTED_METRICS = [
    MetricMeta("ofsted_good_pupils", "Pupils at schools rated Good or Outstanding", "education", "%",
               "Pupils at state-funded schools in the constituency whose latest single-word Ofsted grade is Good or "
               "Outstanding, of pupils at schools with such a grade.", "Ofsted school inspections", "higher_better", 0,
               ("ofsted",)),
    MetricMeta("ofsted_concern_schools", "Schools in special measures or with serious weaknesses", "education", "schools",
               "State-funded schools in the constituency currently in an Ofsted category of concern (special measures, "
               "serious weaknesses or requiring significant improvement). National figure: average per seat.",
               "Ofsted school inspections", "higher_worse", 0, ("ofsted",)),
]


def _when(title: str) -> datetime.datetime:
    m = re.search(r"(\d{1,2}) (\w+) (\d{4})", title)
    try:
        return datetime.datetime.strptime(" ".join(m.groups()), "%d %B %Y") if m else datetime.datetime.min
    except ValueError:
        return datetime.datetime.min


def find_file(s: requests.Session) -> tuple[str, str]:
    files = [a for a in get_json(s, DATASET).get("details", {}).get("attachments", [])
             if "latest inspections" in str(a.get("title", "")).lower() and str(a.get("url", "")).endswith(".csv")]
    if not files:
        raise LookupError("No Ofsted latest inspections file found")
    best = max(files, key=lambda a: _when(a["title"]))
    return best["url"], _when(best["title"]).strftime("%-d %B %Y")


def seat_frames(d: pd.DataFrame, names: dict[str, str]) -> dict[str, pd.DataFrame]:
    seat = d["Parliamentary constituency"].astype(str).str.strip().str.lower().map(names)
    pupils = pd.to_numeric(d["Total number of pupils"], errors="coerce").fillna(0)
    grade = pd.to_numeric(d["Latest OEIF overall effectiveness"], errors="coerce")
    graded = grade.isin([1, 2, 3, 4])
    good = grade.isin([1, 2])
    concern = d["Most recent category of concern"].notna()
    codes = sorted({c for c in names.values() if c.startswith("E")})
    g = pd.DataFrame({"seat": seat, "pg": pupils.where(graded, 0), "pgood": pupils.where(good, 0),
                      "concern": concern.astype(int)}).dropna(subset=["seat"]).groupby("seat").sum()
    g = g.reindex(codes).fillna(0)
    return {
        "ofsted_good_pupils": pd.DataFrame({"num": g["pgood"] * 100, "den": g["pg"].where(g["pg"] > 0)}),
        "ofsted_concern_schools": pd.DataFrame({"num": g["concern"], "den": 1.0}),
    }


def load_ofsted(s: requests.Session, geo: dict) -> tuple[dict[str, pd.DataFrame], str]:
    url, when = find_file(s)
    r = s.get(url, timeout=180)
    r.raise_for_status()
    d = pd.read_csv(io.BytesIO(r.content), encoding="latin-1", low_memory=False)
    names = {f["properties"]["name"].strip().lower(): f["properties"]["code"] for f in geo["features"]}
    return seat_frames(d, names), f"Latest inspections as at {when}"
