"""Neighbourhood policing priorities from the police.uk API, for each seat's briefing (England, Wales, NI).

Every neighbourhood policing team publishes its current priorities ("drug dealing around X", "shop theft in the
town centre"). A seat holds several teams' areas, so a handful of points spread across the seat are each looked up
with ``/locate-neighbourhood``; each team found is then read with its priorities (``/{force}/{team}/priorities``),
and named from its force's list of neighbourhoods (``/{force}/neighbourhoods``, one request per force). police.uk
answers slowly (seconds per request), so many requests are kept in flight, within its rate limit. The result is written to ``policing.json``, which the site loads only when a
seat's briefing is opened.

Docs: https://data.police.uk/docs/method/neighbourhood-priorities/
"""

from __future__ import annotations

import html
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from shapely.geometry import Point, shape

from .police import BASE, _RateLimiter

log = logging.getLogger(__name__)

SOURCE_URL = "https://data.police.uk/docs/method/neighbourhood-priorities/"
POINTS = 6  # points looked up per seat: enough to find most of the teams covering it
PER_TEAM = 3  # newest priorities kept per team
MAX_CHARS = 280


def sample_points(geom, n: int = POINTS) -> list[Point]:
    """``n`` points inside the seat, spread out: its representative point, then grid points furthest from those chosen."""
    chosen = [geom.representative_point()]
    minx, miny, maxx, maxy = geom.bounds
    k = 9
    grid = [Point(minx + (i + 0.5) * (maxx - minx) / k, miny + (j + 0.5) * (maxy - miny) / k) for i in range(k) for j in range(k)]
    inside = [p for p in grid if geom.contains(p)]
    while len(chosen) < n and inside:
        p = max(inside, key=lambda q: min(q.distance(c) for c in chosen))
        chosen.append(p)
        inside.remove(p)
    return chosen


def plain(raw: str | None) -> str:
    """Priority text as plain sentences: list items become "; "-separated, tags and entities removed, shortened."""
    if not raw:
        return ""
    t = re.sub(r"</li>\s*<li[^>]*>", "; ", raw, flags=re.I)
    t = re.sub(r"<br\s*/?>|</p>\s*<p[^>]*>", " ", t, flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s*\.?\s*;\s*", "; ", t).strip(" ;.")  # "item.; item" -> "item; item"
    letters = [ch for ch in t if ch.isalpha()]
    if len(letters) > 8 and sum(ch.isupper() for ch in letters) > 0.8 * len(letters):
        t = t.capitalize()  # "DANGEROUS & ANTISOCIAL DRIVING" -> "Dangerous & antisocial driving"
    if len(t) > MAX_CHARS:
        t = t[:MAX_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return t


def priorities(raw: list[dict]) -> list[dict]:
    """A team's newest priorities: the issue and the date set. (Teams' "action" updates are left out: they're often
    long, and would more than double the file the briefing loads.)"""
    out = []
    for p in sorted(raw, key=lambda p: p.get("issue-date") or "", reverse=True):
        issue = plain(p.get("issue"))
        if len(issue) < 4:
            continue
        out.append({"issue": issue, "date": (p.get("issue-date") or "")[:10]})
        if len(out) == PER_TEAM:
            break
    return out


class _Api:
    def __init__(self, s: requests.Session):
        self.s, self.rl = s, _RateLimiter()

    def get(self, path: str, **params):
        self.rl.wait()
        r = self.s.get(f"{BASE}/{path}", params=params or None, timeout=60)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


def load_priorities(s: requests.Session, boundaries: dict, workers: int = 30) -> dict:
    """{"seats": {seat code: [{"force", "team", "url", "priorities": [...]}, ...]}} (teams with priorities only)."""
    api = _Api(s)
    forces = {f["id"]: f["name"] for f in api.get("forces") or []}
    seats = [(f["properties"]["code"], shape(f["geometry"])) for f in boundaries["features"]
             if not f["properties"]["code"].startswith("S")]  # police.uk doesn't cover Scotland
    teams_by_seat: dict[str, list[tuple[str, str]]] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        located = {ex.submit(api.get, "locate-neighbourhood", q=f"{p.y:.5f},{p.x:.5f}"): code
                   for code, g in seats for p in sample_points(g)}
        for fut in as_completed(located):
            try:
                hit = fut.result()
            except requests.RequestException as exc:
                log.warning("police.uk locate failed for %s: %s", located[fut], exc)
                continue
            if hit and hit.get("force") and hit.get("neighbourhood"):
                key = (hit["force"], hit["neighbourhood"])
                found = teams_by_seat.setdefault(located[fut], [])
                if key not in found:
                    found.append(key)
        teams = sorted({t for ts in teams_by_seat.values() for t in ts})
        log.info("Policing priorities: %d teams across %d seats", len(teams), len(teams_by_seat))
        lists = {ex.submit(api.get, f"{f}/neighbourhoods"): f for f in sorted({f for f, _ in teams})}
        prio = {ex.submit(api.get, f"{f}/{n}/priorities"): (f, n) for f, n in teams}
        names: dict[tuple[str, str], str] = {}
        for fut in as_completed(lists):
            try:
                names.update({(lists[fut], x["id"]): x["name"] for x in fut.result() or [] if x.get("id") and x.get("name")})
            except requests.RequestException as exc:
                log.warning("police.uk neighbourhoods of %s failed: %s", lists[fut], exc)
        pri = {}
        for fut in as_completed(prio):
            try:
                pri[prio[fut]] = fut.result()
            except requests.RequestException as exc:
                log.warning("police.uk team %s failed: %s", "/".join(prio[fut]), exc)
    out: dict[str, list[dict]] = {}
    for code, ts in teams_by_seat.items():
        entries = []
        for f, n in ts:
            items = priorities(pri.get((f, n)) or [])
            if not items:
                continue
            entries.append({"force": forces.get(f, f), "team": html.unescape(names.get((f, n)) or n), "priorities": items})
        if entries:
            out[code] = sorted(entries, key=lambda e: max(p["date"] for p in e["priorities"]), reverse=True)
    if len(out) < 100:
        raise RuntimeError(f"police.uk returned priorities for only {len(out)} seats")
    return {"seats": out}


def write_priorities(out_dir: Path, data: dict, as_of: str) -> None:
    (out_dir / "policing.json").write_text(json.dumps({"as_of": as_of, **data}, separators=(",", ":"), ensure_ascii=False))


def demo_priorities(seats: list[dict], rng) -> dict:
    """SYNTHETIC priorities for the demo build."""
    issues = ["Anti-social behaviour around the town centre", "Shop theft in the high street", "Speeding on residential roads",
              "Drug dealing near the park", "Burglary in residential areas", "Off-road bikes on footpaths"]
    out = {}
    for i, st in enumerate(seats):
        if i % 3 == 2:
            continue
        picks = rng.choice(len(issues), size=2, replace=False)
        out[st["code"]] = [{"force": "Demo Police", "team": f"Demo team {i:03d}",
                            "priorities": [{"issue": issues[k], "date": "2026-10-01"} for k in picks]}]
    return {"seats": out}
