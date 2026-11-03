"""Flood warning areas by constituency (Environment Agency flood monitoring API). England.

The Environment Agency defines a flood warning area for each community where
it can warn of flooding from rivers or the sea. Each area is placed in the
seat containing its centre; the count is a rough measure of how many places
in the seat are at known flood risk.
"""

from __future__ import annotations

import logging

import pandas as pd
import requests

from ..geo import SeatLocator
from ..http import get_json
from ..metrics import MetricMeta

log = logging.getLogger(__name__)

API = "https://environment.data.gov.uk/flood-monitoring/id/floodAreas"
SOURCE_URL = "https://environment.data.gov.uk/flood-monitoring/doc/reference"

FLOOD_METRICS = [
    MetricMeta("flood_warning_areas", "Flood warning areas", "environment", "areas",
               "Environment Agency flood warning areas (communities at risk of flooding from rivers or the sea that can get "
               "flood warnings) centred in the constituency. National figure: average per seat.",
               "Environment Agency flood monitoring", "higher_worse", 0, ("flooding",)),
]


def seat_frames(areas: pd.DataFrame, seats: list[str | None], codes: list[str]) -> dict[str, pd.DataFrame]:
    eng = [c for c in codes if c.startswith("E")]
    n = pd.Series(seats, index=areas.index).dropna().value_counts().reindex(eng).fillna(0)
    return {"flood_warning_areas": pd.DataFrame({"num": n, "den": 1.0})}


def load_floods(s: requests.Session, geo: dict) -> tuple[dict[str, pd.DataFrame], str]:
    items = get_json(s, API, params={"_limit": 20000}).get("items", [])
    d = pd.DataFrame([{"code": i.get("notation", ""), "lat": i.get("lat"), "lon": i.get("long")} for i in items])
    d = d[d["code"].str[3:5].eq("FW")]  # warning areas (not the wider "flood alert" areas)
    d["lat"], d["lon"] = pd.to_numeric(d["lat"], errors="coerce"), pd.to_numeric(d["lon"], errors="coerce")
    d = d.dropna(subset=["lat", "lon"])
    seats = SeatLocator(geo).seats(d["lon"], d["lat"])
    log.info("Flood warning areas: %d, %d placed", len(d), sum(x is not None for x in seats))
    codes = [f["properties"]["code"] for f in geo["features"]]
    return seat_frames(d, seats, codes), f"{len(d)} flood warning areas"
