"""Privately kept cars and plug-in vehicles by constituency (DfT vehicle licensing statistics). England & Wales.

DfT publishes licensed vehicles by neighbourhood (LSOA) and quarter: all
vehicles by body type and keepership (VEH0125), and plug-in vehicles by fuel
type (VEH0145). Company-kept vehicles are registered where the company is, not
where the driver lives, so only privately kept vehicles are used. Small counts
are suppressed ("[c]") and count as zero.
"""

from __future__ import annotations

import io
import logging

import pandas as pd
import requests

from ..http import get_json
from ..history import MAX_PERIODS, with_history

MAX_SUPPRESSED = 0.10
from ..metrics import MetricMeta

log = logging.getLogger(__name__)

DATASET = "https://www.gov.uk/api/content/government/statistical-data-sets/vehicle-licensing-statistics-data-files"
SOURCE_URL = "https://www.gov.uk/government/statistical-data-sets/vehicle-licensing-statistics-data-files"

VEHICLE_METRICS = [
    MetricMeta("cars_per_household", "Private cars per household", "transport", "cars",
               "Licensed cars kept by private individuals living in the constituency (DfT, latest quarter), per household "
               "(Census 2021).", "DfT vehicle licensing statistics", "neutral", 2, ("vehicles",)),
    MetricMeta("plugin_share_private", "Plug-in vehicles among private cars", "transport", "%",
               "Privately kept plug-in vehicles (battery electric and plug-in hybrid) as a share of privately kept licensed "
               "cars (DfT, latest quarter).", "DfT vehicle licensing statistics", "higher_better", 1, ("vehicles",)),
]


def find_files(s: requests.Session) -> dict[str, str]:
    found = {}
    for a in get_json(s, DATASET).get("details", {}).get("attachments", []):
        url = str(a.get("url", ""))
        for key in ("VEH0125", "VEH0145"):
            if url.endswith(f"df_{key}.csv"):
                found[key] = url
    if len(found) < 2:
        raise LookupError("Vehicle licensing LSOA files not found")
    return found


def latest_counts(csv: bytes, filters: dict[str, str]) -> tuple[pd.Series, str]:
    """Latest quarter's count by LSOA for rows matching ``filters`` (column -> value)."""
    header = pd.read_csv(io.BytesIO(csv), nrows=0).columns
    quarter = next(c for c in header if c[:4].isdigit() and " Q" in c)  # newest first
    d = pd.read_csv(io.BytesIO(csv), usecols=["LSOA21CD", *filters, quarter], dtype=str)
    for col, value in filters.items():
        d = d[d[col].eq(value)]
    counts = pd.to_numeric(d[quarter], errors="coerce").fillna(0)
    return counts.groupby(d["LSOA21CD"].values).sum(), quarter


def quarter_counts(csv: bytes, filters: dict[str, str]) -> pd.DataFrame:
    """Counts by LSOA for the latest quarter and the same quarter in earlier years (columns oldest first)."""
    header = pd.read_csv(io.BytesIO(csv), nrows=0).columns
    quarters = [c for c in header if c[:4].isdigit() and " Q" in c]
    same = [c for c in quarters if c.endswith(quarters[0][-2:])][:MAX_PERIODS][::-1]
    d = pd.read_csv(io.BytesIO(csv), usecols=["LSOA21CD", *filters, *same], dtype=str)
    for col, value in filters.items():
        d = d[d[col].eq(value)]
    counts = d[same].apply(pd.to_numeric, errors="coerce").fillna(0)
    out = counts.groupby(d["LSOA21CD"].values).sum()
    out.attrs["suppressed"] = {q: float(d[q].eq("[c]").mean()) for q in same}  # share of "[c]" (small counts hidden)
    return out


def seat_frames(cars: pd.Series, plugins: pd.Series, lsoa_to_pcon: dict[str, str], households: pd.Series | None) -> dict[str, pd.DataFrame]:
    to_seat = lambda v: v.groupby(v.index.map(lsoa_to_pcon)).sum()  # noqa: E731 (unmapped LSOAs drop out)
    c, p = to_seat(cars), to_seat(plugins).reindex(to_seat(cars).index).fillna(0)
    frames = {"plugin_share_private": pd.DataFrame({"num": p * 100, "den": c.where(c > 0)})}
    if households is not None:
        frames["cars_per_household"] = pd.DataFrame({"num": c, "den": households.reindex(c.index)})
    return frames


def load_vehicles(s: requests.Session, lsoa_to_pcon: dict[str, str], households: pd.Series | None) -> tuple[dict[str, pd.DataFrame], str]:
    urls = find_files(s)
    got = {}
    for key in urls:
        r = s.get(urls[key], timeout=600)
        r.raise_for_status()
        got[key] = r.content
    car_filter = {"BodyType": "Cars", "Keepership": "Private", "LicenceStatus": "Licensed"}
    cars_q = quarter_counts(got["VEH0125"], car_filter)
    plug_q = quarter_counts(got["VEH0145"], {"Fuel": "Total", "Keepership": "Private"})
    quarter = cars_q.columns[-1]
    frames = seat_frames(cars_q[quarter], plug_q.get(quarter, pd.Series(dtype=float)), lsoa_to_pcon, households)
    # Plug-in share in the same quarter of each earlier year.
    # Years when many small counts were suppressed would understate the share: only use well-covered quarters.
    ok = [q for q in cars_q.columns if q in plug_q.columns and plug_q.attrs.get("suppressed", {}).get(q, 1) < MAX_SUPPRESSED]
    past = [(q, seat_frames(cars_q[q], plug_q[q], lsoa_to_pcon, None)["plugin_share_private"]) for q in ok]
    with_history(frames["plugin_share_private"], [(q, f, None) for q, f in past])
    return frames, quarter
