"""Travel time to key services by public transport or walking (DfT journey time statistics). England.

DfT's journey time statistics (JTS05xx tables, latest edition 2019) give, for
each neighbourhood (LSOA, 2011 codes), the average minimum journey time to the
nearest GP, hospital, secondary school, food store and town centre by public
transport or walking. Seats average their neighbourhoods, weighted by the
people each service is for (e.g. children of secondary school age).
Neighbourhoods whose codes changed in 2021 drop out (about 5%).
"""

from __future__ import annotations

import logging
import re

import pandas as pd
import requests

from ..http import get_json
from ..metrics import MetricMeta
from ..ods import find_table, read_ods, sheet_names

log = logging.getLogger(__name__)

DATASET = "https://www.gov.uk/api/content/government/statistical-data-sets/journey-time-statistics-data-tables-jts"
SOURCE_URL = "https://www.gov.uk/government/collections/journey-time-statistics"
SERVICES = {  # metric -> (table, label, description)
    "travel_gp": ("jts0505", "GP", "the nearest GP surgery"),
    "travel_hospital": ("jts0506", "hospital", "the nearest hospital"),
    "travel_secondary": ("jts0503", "secondary school", "the nearest secondary school (for children aged 11-15)"),
    "travel_food": ("jts0507", "food store", "the nearest food store"),
    "travel_town": ("jts0508", "town centre", "the nearest town centre"),
}

TRAVEL_METRICS = [
    MetricMeta(mid, f"Minutes to a {label} by bus or on foot", "transport", "minutes",
               f"Average minimum journey time to {desc} by public transport or walking, averaged over the constituency's "
               "neighbourhoods (DfT journey time statistics, 2019).", "DfT journey time statistics", "higher_worse", 0,
               ("access",))
    for mid, (_, label, desc) in SERVICES.items()
]


def find_files(s: requests.Session) -> dict[str, str]:
    urls = {}
    for a in get_json(s, DATASET).get("details", {}).get("attachments", []):
        url = str(a.get("url", ""))
        for mid, (table, _, _) in SERVICES.items():
            if url.endswith(f"/{table}.ods"):
                urls[mid] = url
    return urls


def times(sheet: pd.DataFrame) -> pd.DataFrame:
    """LSOA -> (minutes by public transport/walk, people the service is for)."""
    t = find_table(sheet, "LSOA_code")
    minutes = next(c for c in t.columns if re.fullmatch(r"[A-Za-z]+PTt", c))
    weight = next(c for c in t.columns if c.lower().endswith("_pop"))
    return pd.DataFrame({"minutes": pd.to_numeric(t[minutes], errors="coerce").values,
                         "weight": pd.to_numeric(t[weight], errors="coerce").values},
                        index=t["LSOA_code"].astype(str).str.strip()).dropna()


def seat_frame(lsoa: pd.DataFrame, lsoa_to_pcon: dict[str, str]) -> pd.DataFrame:
    d = lsoa.assign(pcon=lsoa.index.map(lsoa_to_pcon)).dropna(subset=["pcon"])
    g = d.assign(wm=d["minutes"] * d["weight"]).groupby("pcon")
    return pd.DataFrame({"num": g["wm"].sum(), "den": g["weight"].sum()})


def load_travel(s: requests.Session, lsoa_to_pcon: dict[str, str]) -> tuple[dict[str, pd.DataFrame], str]:
    urls = find_files(s)
    if not urls:
        raise LookupError("No journey time statistics LSOA tables found")
    frames, years = {}, set()
    for mid, url in urls.items():
        r = s.get(url, timeout=300)
        r.raise_for_status()
        year = max((n for n in sheet_names(r.content) if re.fullmatch(r"\d{4}", n)), default=None)
        if year is None:
            continue
        lsoa = times(read_ods(r.content, only={year})[year])
        frames[mid] = seat_frame(lsoa, lsoa_to_pcon)
        years.add(year)
        log.info("%s: %d neighbourhoods, %d matched to seats (%s)", mid, len(lsoa), lsoa.index.isin(list(lsoa_to_pcon)).sum(), year)
    return frames, ", ".join(sorted(years))
