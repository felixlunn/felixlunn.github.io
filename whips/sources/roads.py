"""Road traffic collisions with injuries by constituency (DfT STATS19), Great Britain.

DfT publishes every reported injury collision of the last five years with its
location. Collisions are placed in seats by their neighbourhood (LSOA) in
England and Wales and by their coordinates in Scotland. "Killed or seriously
injured" uses DfT's severity adjustment (police forces record injuries
differently), counting each collision's adjusted probability of being serious
plus every fatal collision.
"""

from __future__ import annotations

import io
import logging

import pandas as pd
import requests

from ..geo import SeatLocator
from ..metrics import MetricMeta

log = logging.getLogger(__name__)

URL = "https://data.dft.gov.uk/road-accidents-safety-data/dft-road-casualty-statistics-collision-last-5-years.csv"
SOURCE_URL = "https://www.gov.uk/government/statistics/road-safety-data"
COLUMNS = ["collision_year", "longitude", "latitude", "collision_severity", "lsoa_of_accident_location",
           "collision_adjusted_severity_serious"]

ROAD_METRICS = [
    MetricMeta("road_collisions_per_10k", "Injury road collisions a year per 10,000 voters", "transport", "per 10,000",
               "Reported road collisions in which someone was hurt, a year (five-year average), per 10,000 people on the "
               "electoral register (DfT STATS19).", "DfT road safety data", "higher_worse", 1, ("roads",)),
    MetricMeta("road_ksi_per_10k", "Fatal or serious road collisions a year per 10,000 voters", "transport", "per 10,000",
               "Road collisions in which someone was killed or seriously injured, a year (five-year average, DfT severity-"
               "adjusted), per 10,000 people on the electoral register.", "DfT road safety data", "higher_worse", 2, ("roads",)),
    MetricMeta("road_fatal_5y", "Fatal road collisions (5 years)", "transport", "collisions",
               "Road collisions in which someone died over the last five years (DfT STATS19). National figure: average per seat.",
               "DfT road safety data", "higher_worse", 0, ("roads",)),
]


def place(d: pd.DataFrame, lsoa_to_pcon: dict[str, str], locator: SeatLocator | None) -> pd.Series:
    """Seat code for each collision: by LSOA, else (Scotland) by coordinates."""
    seat = d["lsoa_of_accident_location"].astype(str).map(lsoa_to_pcon)
    todo = seat.isna() & d["longitude"].notna() & d["latitude"].notna()
    if locator is not None and todo.any():
        seat[todo] = locator.seats(d.loc[todo, "longitude"], d.loc[todo, "latitude"])
    return seat


def seat_frames(d: pd.DataFrame, seat: pd.Series, electorate: pd.Series, codes: list[str]) -> dict[str, pd.DataFrame]:
    years = d["collision_year"].nunique()
    d = d.assign(pcon=seat.values, ksi=(d["collision_severity"].eq(1)) + d["collision_adjusted_severity_serious"].fillna(0),
                 fatal=d["collision_severity"].eq(1).astype(int)).dropna(subset=["pcon"])
    g = d.groupby("pcon")
    gb = [c for c in codes if c[:1] in "EWS"]  # STATS19 covers Great Britain
    n, ksi, fatal = (x.reindex(gb).fillna(0) for x in (g.size(), g["ksi"].sum(), g["fatal"].sum()))
    elec = electorate.reindex(gb)
    return {
        "road_collisions_per_10k": pd.DataFrame({"num": n * 10_000 / years, "den": elec}),
        "road_ksi_per_10k": pd.DataFrame({"num": ksi * 10_000 / years, "den": elec}),
        "road_fatal_5y": pd.DataFrame({"num": fatal, "den": 1.0}),
    }


def load_roads(s: requests.Session, geo: dict, lsoa_to_pcon: dict[str, str], electorate: pd.Series) -> tuple[dict[str, pd.DataFrame], str]:
    r = s.get(URL, timeout=600)
    r.raise_for_status()
    d = pd.read_csv(io.BytesIO(r.content), usecols=COLUMNS, low_memory=False)
    seat = place(d, lsoa_to_pcon, SeatLocator(geo))
    log.info("Road collisions: %d, %.1f%% placed in a seat", len(d), seat.notna().mean() * 100)
    codes = [f["properties"]["code"] for f in geo["features"]]
    years = sorted(d["collision_year"].unique())
    return seat_frames(d, seat, electorate, codes), f"{years[0]} to {years[-1]}"
