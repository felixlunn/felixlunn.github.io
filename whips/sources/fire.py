"""Fire and rescue response times by fire authority (Home Office fire statistics, FIRE1001). England.

Average total response time (call handling, crew turnout and driving) to
dwelling fires and to all primary fires, for the latest year, by fire and
rescue authority. Seats average the authorities their councils belong to
(ONS council-to-fire-authority lookup), weighted by neighbourhoods.
"""

from __future__ import annotations

import io
import logging
import re

import pandas as pd
import requests

from ..http import get_json
from ..metrics import MetricMeta
from .boundaries import ARCGIS_ROOT
from .councils import arcgis_rows, averaged, column, regrouped_weights
from .lsoa import _services

log = logging.getLogger(__name__)

DATASET = "https://www.gov.uk/api/content/government/statistical-data-sets/fire-statistics-data-tables"
SOURCE_URL = "https://www.gov.uk/government/statistical-data-sets/fire-statistics-data-tables"
FRA_PATTERN = re.compile(r"^LAD(\d{2})_FRA\d{2}_EW_LU", re.I)
ALIASES = {"london fire and emergency planning authority": "greater london", "royal berkshire": "berkshire",
           "county durham and darlington": "durham", "buckinghamshire and milton keynes": "buckinghamshire",
           "nottinghamshire and city of nottingham": "nottinghamshire", "stoke-on-trent and staffordshire": "staffordshire"}

NOTE = " Figures are for the fire and rescue authority, averaged over those the constituency's councils belong to."
FIRE_METRICS = [
    MetricMeta("fire_response_dwelling", "Fire response time to house fires", "policing", "minutes",
               "Average time from the 999 call to the first fire engine arriving at dwelling fires (Home Office, latest year)."
               + NOTE, "Home Office fire statistics", "higher_worse", 1, ("fire",)),
    MetricMeta("fire_response_primary", "Fire response time to all serious fires", "policing", "minutes",
               "Average response time to primary fires (buildings, vehicles and serious outdoor fires), latest year." + NOTE,
               "Home Office fire statistics", "higher_worse", 1, ("fire",)),
]


def key(name: str) -> str:
    n = re.sub(r"\s+", " ", str(name).strip().lower().replace("&", "and"))
    return ALIASES.get(n, n)


def find_file(s: requests.Session) -> str:
    for a in get_json(s, DATASET).get("details", {}).get("attachments", []):
        if str(a.get("title", "")).upper().startswith("FIRE1001") and str(a.get("url", "")).endswith(".xlsx"):
            return a["url"]
    raise LookupError("No FIRE1001 table found")


def response_times(d: pd.DataFrame, fire_type: str) -> tuple[pd.Series, float | None, str]:
    """Minutes by authority key for the latest year with data; England's figure; the year."""
    d = d[d["FIRE_TYPE"].astype(str).str.strip().str.lower().eq(fire_type)]
    d = d[pd.to_numeric(d["TOTAL_RESPONSE_TIME"], errors="coerce").notna()]
    # The newest "year" can be a part year with authorities missing: take the latest with full coverage.
    per_year = d.groupby("FINANCIAL_YEAR").size()
    year = max(y for y, n in per_year.items() if n >= per_year.max())
    d = d[d["FINANCIAL_YEAR"].eq(year)]
    minutes = pd.to_numeric(d["TOTAL_RESPONSE_TIME"], errors="coerce") * 24 * 60  # stored as fractions of a day
    s = pd.Series(minutes.values, index=d["LOCATION_CATEGORY"].map(key).values).dropna()
    return s, (float(s["england"]) if "england" in s else None), str(year)


def lad_to_fra(s: requests.Session) -> dict[str, str]:
    names = [n for n in _services(s) if FRA_PATTERN.match(n)]
    latest = max(names, key=lambda n: (int(FRA_PATTERN.match(n).group(1)), n))
    return {column(r, r"LAD\d{2}CD"): key(column(r, r"FRA\d{2}NM")) for r in arcgis_rows(s, f"{ARCGIS_ROOT}/{latest}/FeatureServer/0")}


def load_fire(s: requests.Session, weights: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], str]:
    r = s.get(find_file(s), timeout=180)
    r.raise_for_status()
    d = pd.read_excel(io.BytesIO(r.content), sheet_name="Data - annual")
    fw = regrouped_weights(weights, lad_to_fra(s))
    frames, year = {}, ""
    for mid, ft in [("fire_response_dwelling", "dwellings"), ("fire_response_primary", "primary")]:
        values, national, year = response_times(d, ft)
        missing = sorted(set(fw["lad"]) - set(values.index))
        if missing:
            log.info("%s: no figures for %s", mid, missing[:10])
        f = averaged(values, fw)
        f.attrs["national"] = national
        frames[mid] = f
    return frames, f"Financial year {year}"
