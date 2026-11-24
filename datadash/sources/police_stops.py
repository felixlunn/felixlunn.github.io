"""Stop and search from the police.uk API (England and Wales forces that publish it).

For each constituency its boundary is sent to ``/stops-street`` for each recent month with stop and search data
(the same polygons as the crime figures, see police.py), and the stops are counted with what they led to.

Not every force publishes stop and search to police.uk every month, and a stop record doesn't say which force made
it. So each seat's force is found with ``/locate-neighbourhood`` at a point inside the seat; its stops are annualised
over the months that force published, and seats whose force published fewer than MIN_MONTHS of them are left blank
rather than shown as having none.

Docs: https://data.police.uk/docs/method/stops-street/
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
from shapely.geometry import shape

from ..metrics import MetricMeta
from .police import BASE, _RateLimiter, fetch_polygon, polygon_parts

log = logging.getLogger(__name__)

SOURCE_URL = "https://data.police.uk/docs/method/stops-street/"
MIN_FOR_SHARES = 20  # outcome shares need at least this many stops to mean much
MIN_MONTHS = 3  # of the months used, a seat's force must have published at least this many

STOP_METRICS = [
    MetricMeta("stops_per_1k", "Stop and search per 1,000 residents", "policing", "per 1,000",
               "Stop and searches recorded within the constituency boundary, annualised (over the months the force published) per "
               "1,000 residents (police.uk). Blank where the force doesn't publish stop and search.", "police.uk stop and search", "neutral", 1,
               ("stop_search",)),
    MetricMeta("stops_no_action", "Stop and search: no further action", "policing", "%",
               "Share of stop and searches that ended with no further action (police.uk; seats with at least "
               f"{MIN_FOR_SHARES} stops).", "police.uk stop and search", "higher_worse", 0, ("stop_search",)),
    MetricMeta("stops_arrest", "Stop and search: arrest", "policing", "%",
               "Share of stop and searches that led to an arrest (police.uk; seats with at least "
               f"{MIN_FOR_SHARES} stops).", "police.uk stop and search", "higher_better", 0, ("stop_search",)),
]


def stop_months(dates: list[dict], n: int) -> tuple[list[str], dict[str, set[str]]]:
    """The latest ``n`` months with stop and search data, and which forces published it in each."""
    with_stops = sorted((d for d in dates if d.get("stop-and-search")), key=lambda d: d["date"], reverse=True)[:n]
    return [d["date"] for d in with_stops], {d["date"]: set(d["stop-and-search"]) for d in with_stops}


def outcome_bucket(stop: dict) -> str:
    """"no_action", "arrest" or "other" for one stop."""
    o = ((stop.get("outcome_object") or {}).get("id") or "").lower()
    name = str(stop.get("outcome") or "").lower()
    if o == "bu-arrest" or name == "arrest":
        return "arrest"
    if o == "bu-no-further-action" or "no further action" in name:
        return "no_action"
    return "other"


def summarise(stops: list[dict]) -> Counter:
    n = Counter(outcome_bucket(s) for s in stops)
    n["all"] = len(stops)
    return n


def seat_force(s: requests.Session, rl: _RateLimiter, geom) -> str | None:
    """The police force covering a point inside the seat (police.uk force id), or None if police.uk doesn't know."""
    p = geom.representative_point()
    rl.wait()
    r = s.get(f"{BASE}/locate-neighbourhood", params={"q": f"{p.y:.5f},{p.x:.5f}"}, timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json().get("force")


def seat_frames(counts: dict[str, Counter], forces: dict[str, str | None], published: dict[str, set[str]],
                population: pd.Series) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Per-metric frames, annualised over the months each seat's force published; seats whose force published fewer
    than MIN_MONTHS are left out (and listed)."""
    months = {c: sum(f in forces_in_month for forces_in_month in published.values()) for c, f in forces.items()}
    blank = sorted(c for c in forces if months[c] < MIN_MONTHS)
    keep = [c for c in counts if c in months and c not in blank]
    df = pd.DataFrame({c: counts[c] for c in keep}).T.reindex(columns=["all", "no_action", "arrest"]).fillna(0)
    pop = population.reindex(df.index)
    per_year = df["all"] * 12 / pd.Series({c: months[c] for c in df.index})
    out = {"stops_per_1k": pd.DataFrame({"num": per_year * 1000, "den": pop}).dropna()}
    enough = df[df["all"] >= MIN_FOR_SHARES]
    out["stops_no_action"] = pd.DataFrame({"num": enough["no_action"] * 100, "den": enough["all"]})
    out["stops_arrest"] = pd.DataFrame({"num": enough["arrest"] * 100, "den": enough["all"]})
    return out, blank


def load_stops(s: requests.Session, boundaries: dict, population: pd.Series, months: int | None = None,
               workers: int = 12) -> tuple[dict[str, pd.DataFrame], str]:
    months = months or int(os.environ.get("STOP_MONTHS", "6"))
    r = s.get(f"{BASE}/crimes-street-dates", timeout=60)
    r.raise_for_status()
    month_list, published = stop_months(r.json(), months)
    if not month_list:
        raise LookupError("police.uk lists no months with stop and search data")
    log.info("Stop and search months: %s", month_list)
    rl = _RateLimiter()
    seats = [(f["properties"]["code"], shape(f["geometry"])) for f in boundaries["features"]
             if f["properties"]["code"][:1] in ("E", "W")]  # police.uk stop and search: England and Wales forces
    counts: dict[str, Counter] = {}
    forces: dict[str, str | None] = {}
    failed: set[str] = set()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        located = {ex.submit(seat_force, s, rl, g): code for code, g in seats}
        jobs = {ex.submit(fetch_polygon, s, rl, part, m, 0, "stops-street"): code
                for code, g in seats for part in polygon_parts(g) for m in month_list}
        log.info("Stop and search: %d requests queued", len(jobs) + len(located))
        for fut in as_completed(located):
            try:
                forces[located[fut]] = fut.result()
            except requests.RequestException as exc:
                failed.add(located[fut])
                log.warning("police.uk locate failed for %s: %s", located[fut], exc)
        stops: dict[str, list[dict]] = {}
        for fut in as_completed(jobs):
            code = jobs[fut]
            try:
                stops.setdefault(code, []).extend(fut.result())
            except requests.RequestException as exc:
                failed.add(code)
                log.warning("police.uk stops failed for %s: %s", code, exc)
    for code, _ in seats:
        if code not in failed:
            counts[code] = summarise(stops.get(code, []))
    out, blank = seat_frames(counts, {c: f for c, f in forces.items() if c in counts}, published, population)
    if blank:
        log.info("Stop and search: %d seats left blank (force published fewer than %d of the months)", len(blank), MIN_MONTHS)
    if not len(out["stops_per_1k"]):
        raise RuntimeError("police.uk returned no stop and search data")
    n_forces = len({f for fs in published.values() for f in fs})
    return out, f"{min(month_list)} to {max(month_list)}", f"{len(month_list)} months; {n_forces} forces publishing; annualised over the months each published"
