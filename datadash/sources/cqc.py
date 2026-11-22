"""Care Quality Commission ratings and care home beds by constituency. England.

CQC's monthly list of active registered locations gives each service's
latest overall rating, its type and its coordinates. Services are placed in
seats by location. Shares are of services with a rating (Outstanding, Good,
Requires improvement or Inadequate); dormant locations are left out.
"""

from __future__ import annotations

import logging
import re

import pandas as pd
import requests

from ..geo import SeatLocator
from ..metrics import MetricMeta
from ..ods import find_table, read_ods

log = logging.getLogger(__name__)

SOURCE_URL = "https://www.cqc.org.uk/about-us/transparency/using-cqc-data"
RATED = ["Outstanding", "Good", "Requires improvement", "Inadequate"]
POOR = ["Requires improvement", "Inadequate"]
KINDS = {  # metric -> (label, primary inspection category, care home flag)
    "care_homes_poor": ("care homes", "Residential social care", "Y"),
    "home_care_poor": ("home care and community social care services", "Community based adult social care services", None),
    "gp_practices_poor": ("GP practices", "GP Practices", None),
}
_LABELS = {"care_homes_poor": "Care homes rated poor", "home_care_poor": "Home care services rated poor",
           "gp_practices_poor": "GP practices rated poor"}

CQC_METRICS = [
    MetricMeta(mid, _LABELS[mid], "health", "%",
               f"Share of rated {label} in the constituency whose latest CQC overall rating is Requires improvement or "
               "Inadequate.", "CQC ratings", "higher_worse", 0, ("cqc",))
    for mid, (label, _, _) in KINDS.items()
] + [
    MetricMeta("care_home_beds_per_1k_65", "Care home beds per 1,000 aged 65+", "health", "per 1,000",
               "Beds in CQC-registered care homes in the constituency per 1,000 residents aged 65 and over (Census 2021).",
               "CQC ratings", "neutral", 0, ("cqc",)),
]


def find_file(s: requests.Session) -> str:
    html = s.get(SOURCE_URL, timeout=60).text
    links = re.findall(r'href="([^"]+HSCA_Active_Locations\.ods)"', html)
    if not links:
        raise LookupError("No CQC active locations file linked from the CQC data page")
    return links[0]


def seat_frames(t: pd.DataFrame, seat: pd.Series, age65: pd.Series | None, codes: list[str]) -> dict[str, pd.DataFrame]:
    t = t.assign(pcon=seat.values)
    t = t[t["Dormant (Y/N)"].astype(str).str.upper().ne("Y") & t["pcon"].notna()]
    england = [c for c in codes if c.startswith("E")]
    rating = t["Location Latest Overall Rating"].astype(str).str.strip()
    frames = {}
    for mid, (_, category, care_home) in KINDS.items():
        sel = t["Location Primary Inspection Category"].eq(category) & rating.isin(RATED)
        if care_home:
            sel &= t["Care home?"].astype(str).str.upper().eq(care_home)
        g = t[sel].groupby("pcon")
        frames[mid] = pd.DataFrame({"num": rating[sel].isin(POOR).groupby(t.loc[sel, "pcon"]).sum() * 100,
                                    "den": g.size()}).reindex(england)
    if age65 is not None:
        homes = t[t["Care home?"].astype(str).str.upper().eq("Y")]
        beds = pd.to_numeric(homes["Care homes beds"], errors="coerce").groupby(homes["pcon"]).sum()
        frames["care_home_beds_per_1k_65"] = pd.DataFrame({"num": beds.reindex(england).fillna(0) * 1000,
                                                           "den": age65.reindex(england)})
    return frames


def load_cqc(s: requests.Session, geo: dict, age65: pd.Series | None) -> tuple[dict[str, pd.DataFrame], str]:
    url = find_file(s)
    r = s.get(url, timeout=300)
    r.raise_for_status()
    sheets = read_ods(r.content)
    t = find_table(next(v for k, v in sheets.items() if "active" in k.lower()), "Location ID")
    lon = pd.to_numeric(t["Location Longitude"], errors="coerce")
    lat = pd.to_numeric(t["Location Latitude"], errors="coerce")
    ok = lon.notna() & lat.notna()
    seat = pd.Series(None, index=t.index, dtype=object)
    seat[ok] = SeatLocator(geo).seats(lon[ok], lat[ok])
    log.info("CQC: %d active locations, %.1f%% placed", len(t), seat.notna().mean() * 100)
    codes = [f["properties"]["code"] for f in geo["features"]]
    when = re.search(r"/(\d{2})_(\w+)_(\d{4})_HSCA", url)
    return seat_frames(t, seat, age65, codes), (f"{int(when.group(1))} {when.group(2)} {when.group(3)}" if when else "Latest")
