"""Street-level crime and outcomes from the police.uk API (England, Wales and Northern Ireland).

For each constituency we POST its (simplified) boundary polygon to
``/crimes-street/all-crime`` for each of the most recent N months, then count
crimes by category and by latest outcome. police.uk returns HTTP 503 when an
area has more than 10,000 crimes in a month; in that case the polygon is split
in two and each half is queried separately.

Docs: https://data.police.uk/docs/
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
from shapely.geometry import MultiPolygon, Polygon, box, shape

from ..metrics import POLICE_CATEGORIES

log = logging.getLogger(__name__)

BASE = "https://data.police.uk/api"
MAX_POINTS = 250

# Latest-outcome labels that count as "a suspect was charged / the case went to court".
CHARGED_KEYWORDS = (
    "court", "charged", "sent to prison", "suspended prison", "fined", "community sentence",
    "discharge", "not guilty", "compensation", "deprived of property", "otherwise dealt with",
)
NO_SUSPECT = "investigation complete; no suspect identified"
UNRESOLVED = {"under investigation", "status update unavailable"}


class _RateLimiter:
    """police.uk allows 15 requests/second; stay comfortably under it."""

    def __init__(self, per_second: float = 10.0):
        self.interval = 1.0 / per_second
        self.lock = threading.Lock()
        self.next = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            if self.next > now:
                time.sleep(self.next - now)
            self.next = max(now, self.next) + self.interval


def latest_months(s: requests.Session, n: int) -> list[str]:
    r = s.get(f"{BASE}/crimes-street-dates", timeout=60)
    r.raise_for_status()
    dates = sorted({d["date"] for d in r.json()}, reverse=True)
    return dates[:n]


def polygon_parts(geom) -> list[Polygon]:
    """Simplified polygon parts suitable for the police.uk ``poly`` parameter."""
    parts = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    out = []
    for p in parts:
        if p.area < 1e-6:  # skip slivers / tiny islets (< ~0.01 km²)
            continue
        tol = 0.0005
        q = p.simplify(tol, preserve_topology=True)
        while len(q.exterior.coords) > MAX_POINTS:
            tol *= 2
            q = p.simplify(tol, preserve_topology=True)
        if isinstance(q, Polygon) and not q.is_empty:
            out.append(q)
    return out


def poly_param(p: Polygon) -> str:
    # police.uk wants "lat,lng:lat,lng:..." (the ring closes implicitly)
    coords = list(p.exterior.coords)[:-1]
    return ":".join(f"{lat:.5f},{lng:.5f}" for lng, lat in coords)


def split(p: Polygon) -> list[Polygon]:
    minx, miny, maxx, maxy = p.bounds
    if maxx - minx >= maxy - miny:
        mid = (minx + maxx) / 2
        halves = [box(minx, miny, mid, maxy), box(mid, miny, maxx, maxy)]
    else:
        mid = (miny + maxy) / 2
        halves = [box(minx, miny, maxx, mid), box(minx, mid, maxx, maxy)]
    out = []
    for h in halves:
        g = p.intersection(h)
        out.extend(g.geoms if isinstance(g, MultiPolygon) else [g] if isinstance(g, Polygon) else [])
    return [g for g in out if not g.is_empty]


def fetch_polygon(s: requests.Session, rl: _RateLimiter, p: Polygon, month: str, depth: int = 0) -> list[dict]:
    rl.wait()
    r = s.post(f"{BASE}/crimes-street/all-crime", data={"poly": poly_param(p), "date": month}, timeout=120)
    if r.status_code == 503 and depth < 4:
        return [c for half in split(p) for c in fetch_polygon(s, rl, half, month, depth + 1)]
    r.raise_for_status()
    return r.json()


def summarise(crimes: list[dict]) -> dict[str, int]:
    """Count crimes per category and per outcome bucket (deduplicated by crime id)."""
    seen = {}
    for c in crimes:
        key = c.get("persistent_id") or c.get("id")
        seen[key or id(c)] = c
    counts = Counter()
    for c in seen.values():
        counts["all-crime"] += 1
        counts[c.get("category", "other")] += 1
        outcome = ((c.get("outcome_status") or {}).get("category") or "").strip().lower()
        if outcome and outcome not in UNRESOLVED:
            counts["outcome_resolved"] += 1
            if outcome == NO_SUSPECT:
                counts["outcome_no_suspect"] += 1
            elif any(k in outcome for k in CHARGED_KEYWORDS):
                counts["outcome_charged"] += 1
    # police.uk uses "violent-crime" as the category id for violence and sexual offences
    counts["violent-crime"] = counts.get("violent-crime", 0) + counts.pop("violence-and-sexual-offences", 0)
    return dict(counts)


def load_police(s: requests.Session, boundaries: dict, population: pd.Series, months: int | None = None,
                workers: int = 6) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Return per-metric num/den frames and the months covered."""
    months = months or int(os.environ.get("POLICE_MONTHS", "3"))
    month_list = latest_months(s, months)
    log.info("police.uk months: %s", month_list)
    rl = _RateLimiter()
    jobs = {}
    totals: dict[str, Counter] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for f in boundaries["features"]:
            code = f["properties"]["code"]
            if code.startswith("S"):  # police.uk does not cover Scotland
                continue
            geom = shape(f["geometry"])
            for part in polygon_parts(geom):
                for m in month_list:
                    jobs[ex.submit(fetch_polygon, s, rl, part, m)] = code
        log.info("police.uk: %d requests queued", len(jobs))
        crimes_by_code: dict[str, list[dict]] = {}
        failed = set()
        for i, fut in enumerate(as_completed(jobs), 1):
            code = jobs[fut]
            try:
                crimes_by_code.setdefault(code, []).extend(fut.result())
            except requests.RequestException as exc:
                failed.add(code)
                log.warning("police.uk failed for %s: %s", code, exc)
            if i % 200 == 0:
                log.info("police.uk: %d/%d", i, len(jobs))
    for code, crimes in crimes_by_code.items():
        if code not in failed:
            totals[code] = Counter(summarise(crimes))
    if not totals:
        raise RuntimeError("police.uk returned no data")
    df = pd.DataFrame(totals).T.fillna(0)
    annualise = 12 / len(month_list)
    pop = population.reindex(df.index)
    out: dict[str, pd.DataFrame] = {}
    for cat, (mid, _label) in POLICE_CATEGORIES.items():
        num = df.get(cat, pd.Series(0, index=df.index)) * annualise * 1000
        out[mid] = pd.DataFrame({"num": num, "den": pop})
    resolved = df.get("outcome_resolved", pd.Series(0, index=df.index)).replace(0, float("nan"))
    out["outcome_no_suspect"] = pd.DataFrame({"num": df.get("outcome_no_suspect", 0) * 100, "den": resolved})
    out["outcome_charged"] = pd.DataFrame({"num": df.get("outcome_charged", 0) * 100, "den": resolved})
    return out, month_list
