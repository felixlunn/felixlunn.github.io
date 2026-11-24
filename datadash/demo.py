"""SYNTHETIC demo dataset for developing the UI without network access.

Every number and shape here is randomly generated: seats are hexagons named
"Demo seat NNN" with codes "DEMO-NNN", and ``data.json`` carries
``"demo": true`` so the dashboard shows a prominent banner. Never deploy it.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from .build import assemble, finish
from .metrics import CENSUS_METRICS, CLAIMANT_METRICS, ELECTION_METRICS, POLICE_METRICS, census_meta
from .registry import all_metrics


def _hex(cx: float, cy: float, r: float) -> list[list[float]]:
    pts = [[round(cx + r * 1.6 * math.cos(math.radians(60 * k + 30)), 4),
            round(cy + r * math.sin(math.radians(60 * k + 30)), 4)] for k in range(6)]
    return pts + [pts[0]]


def build_demo(out_dir: Path, n: int = 650, seed: int = 42) -> dict:
    rng = np.random.default_rng(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    r = 0.09
    cells = []
    for row in range(200):
        y = 50.2 + row * r * 1.5
        for col in range(-30, 30):
            x = -2.0 + col * r * 1.6 * math.sqrt(3) + (r * 0.8 * math.sqrt(3) if row % 2 else 0)
            # crude island-ish mask: narrower further north
            half_width = 3.0 - max(0.0, (y - 53.0)) * 0.35
            if abs(x + 1.8 + (y - 52) * 0.25) <= half_width:
                cells.append((x, y))
        if len(cells) >= n:
            break
    if len(cells) < n:
        raise RuntimeError("demo grid too small")
    cells = cells[:n]
    codes, features, countries = [], [], []
    for i, (x, y) in enumerate(cells):
        code = f"DEMO-{i + 1:03d}"
        country = "Scotland" if y > 55.0 else "Wales" if (x < -3.0 and 51.4 < y < 53.4) else "England"
        codes.append(code)
        countries.append(country)
        features.append({"type": "Feature", "properties": {"code": code, "name": f"Demo seat {i + 1:03d}"},
                         "geometry": {"type": "Polygon", "coordinates": [_hex(x, y, r)]}})
    geo = {"type": "FeatureCollection", "features": features}

    # Latent factors give the fake data realistic correlations.
    urban = rng.normal(size=n)
    age = rng.normal(size=n) - 0.5 * urban
    depriv = rng.normal(size=n) + 0.3 * urban
    frames = {}
    for k, m in enumerate(CENSUS_METRICS):
        if m.is_count:
            pop = rng.normal(98_000, 9_000, size=n).round()
            frames[m.id] = pd.DataFrame({"num": pop, "den": 1.0}, index=codes)
            continue
        load = rng.normal(size=3)
        base = 5 + (k * 7) % 35
        z = load[0] * urban + load[1] * age + load[2] * depriv + rng.normal(scale=0.6, size=n)
        val = np.clip(base * np.exp(0.25 * z), 0.2, 95)
        frames[m.id] = pd.DataFrame({"num": val * 1000, "den": 1000.0}, index=codes)
    for m in CLAIMANT_METRICS + POLICE_METRICS + ELECTION_METRICS:
        base = 40 if m.unit == "per 1,000" else 20
        val = np.clip(base * np.exp(0.3 * (depriv + 0.5 * urban) + rng.normal(scale=0.4, size=n)), 0.1, 99)
        frames[m.id] = pd.DataFrame({"num": val, "den": 1.0}, index=codes)
    # Every other metric any source provides (from the registry, so new sources appear in the demo automatically).
    special = {m.id for m in CLAIMANT_METRICS + POLICE_METRICS + ELECTION_METRICS}
    extra = [m for m in all_metrics() if m.id not in special]
    for m in extra:
        base = {"£": 30000 if "annual" in m.id else 750, "ratio": 0.8, "per 1,000": 75}.get(m.unit, 3 if m.id == "pop_change" else 15)
        val = base * np.exp(0.15 * (urban - depriv) + rng.normal(scale=0.15, size=n))
        frames[m.id] = pd.DataFrame({"num": val, "den": 1.0}, index=codes)
    # Census and police.uk don't cover Scotland: mirror that gap (the GB-wide Nomis series do).
    gb_wide = {m.id for m in extra if m.id != "pop_change" and m.theme != "deprivation"}
    for mid, f in frames.items():
        if mid.startswith(("vote_", "majority", "turnout")) or mid in gb_wide:
            continue
        f.loc[[c for c, ctry in zip(codes, countries) if ctry == "Scotland"], ["num"]] = np.nan
    metas = [census_meta(m) for m in CENSUS_METRICS] + CLAIMANT_METRICS + extra + POLICE_METRICS + ELECTION_METRICS
    # Synthetic history for some metrics: each seat drifts over six years to its latest value.
    from .history import assemble_history, with_history
    for k, m in enumerate(extra + CLAIMANT_METRICS):
        if k % 2:
            continue
        latest = frames[m.id]
        trend = rng.normal(scale=0.04, size=n)
        periods = []
        for back in range(5, -1, -1):
            factor = np.exp(-trend * back + rng.normal(scale=0.02, size=n) * (back > 0))
            periods.append((str(2025 - back), pd.DataFrame({"num": latest["num"].values * factor, "den": latest["den"]},
                                                         index=codes), None))
        with_history(latest, periods)
    metrics, values = assemble(codes, frames, metas)
    history = assemble_history(codes, frames, metrics)
    parties = ["Labour", "Conservative", "Liberal Democrat", "Reform UK", "Green Party", "Scottish National Party", "Plaid Cymru"]
    colours = {"Labour": "#E4003B", "Conservative": "#0087DC", "Liberal Democrat": "#FAA61A", "Reform UK": "#12B6CF",
               "Green Party": "#02A95B", "Scottish National Party": "#FDF38E", "Plaid Cymru": "#005B54"}
    seats = []
    for i, code in enumerate(codes):
        party = parties[int(rng.integers(0, 5))] if countries[i] == "England" else (
            "Scottish National Party" if countries[i] == "Scotland" and rng.random() < 0.3 else parties[0])
        seats.append({
            "code": code, "name": features[i]["properties"]["name"], "country": countries[i],
            "region": f"Demo region {chr(65 + int(cells[i][1] - 50))}" if countries[i] == "England" else countries[i],
            "mp": f"Demo MP {i + 1:03d}", "party": party, "party_colour": colours.get(party),
            "first_party_2024": party, "second_party_2024": "LD" if (i % 7 == 3 and party != "Liberal Democrat") else None, "result_2024": None,
        })
    sources = [{"id": "demo", "name": "SYNTHETIC DEMO DATA - not real", "url": "", "status": "ok",
                "detail": "Randomly generated for UI development", "as_of": None}]
    from datetime import date, timedelta

    from .sources.debates import parse_events
    day = lambda k: (date.today() + timedelta(days=k)).isoformat() + "T00:00:00"  # noqa: E731
    lead = lambda i: [{"Name": seats[i]["mp"], "Party": seats[i]["party"], "MemberFrom": seats[i]["name"]}]  # noqa: E731
    fake = [
        (1, "13:30", "Main Chamber", "Opposition Day Debate", "Demo opposition day: police numbers and neighbourhood crime", []),
        (2, "09:30", "Westminster Hall", "Westminster Hall debate", "Demo debate: access to NHS dentistry in rural areas", lead(12)),
        (2, "14:30", "Westminster Hall", "Westminster Hall debate", "Demo debate: e-petition on the cost of living for renters", lead(40)),
        (3, "12:30", "Main Chamber", "Oral questions", "Demo Home Office questions (dropped: not a debate)", []),
        (3, "18:00", "Main Chamber", "Adjournment", "Demo adjournment: bus services in the demo valleys", lead(77)),
        (6, "11:00", "Main Chamber", "Legislation", "Demo Bill: Second Reading", []),
    ]
    debates = parse_events([{"Id": k, "StartDate": day(d), "StartTime": t, "Type": v, "Category": c, "Description": title,
                             "Members": m} for k, (d, t, v, c, title, m) in enumerate(fake)])
    # Synthetic councils: a unitary or district (plus a county for some), with random control.
    parties5 = ["Liberal Democrat", "Labour", "Conservative", "Reform UK", "Green Party"]
    councils = {}
    for i, sc in enumerate(seats):
        if sc["country"] == "Northern Ireland":
            continue
        n = int(rng.integers(30, 70))
        split = rng.dirichlet(np.ones(5)) * n
        counts = {p: int(c) for p, c in sorted(zip(parties5, split), key=lambda x: -x[1]) if int(c)}
        top, top_n = next(iter(counts.items()))
        council = {"name": f"Demo council {i // 3 + 1:03d}", "code": f"DEMO-C{i // 3:03d}", "tier": "council", "share": 1.0,
                   "control": top if top_n * 2 > sum(counts.values()) else "No overall control", "largest": top,
                   "largest_seats": top_n, "seats": sum(counts.values()), "parties": counts, "next_election": "2027-05-06"}
        councils[sc["code"]] = [council] + ([{**council, "name": f"Demo county {i // 9 + 1:03d}", "code": f"DEMO-K{i // 9:03d}",
                                              "tier": "county", "next_election": "2029-05-03"}] if i % 2 else [])
    from .sources.foi_geo import demo_reference, write_foi
    ref, areas = demo_reference(geo, seats, frames["population"]["num"].to_dict(), rng)
    write_foi(out_dir, ref, areas)
    from .sources.foi_police import demo_police_datasets, write_police_datasets
    write_police_datasets(out_dir, demo_police_datasets(ref, rng), "demo")
    return finish(out_dir, geo, seats, metrics, values, sources, demo=True, debates=debates, history=history,
                  councils={"year": 2026, "by_seat": councils})
