"""SYNTHETIC FOI reference data for the demo build (no network): forces and NHS areas are blocks of demo seats."""

from __future__ import annotations

from shapely.geometry import shape
from shapely.ops import unary_union

from .assemble import assemble


def demo_reference(geo: dict, seats: list[dict], population: dict[str, float], rng) -> tuple[dict, dict]:
    """SYNTHETIC FOI reference for the demo build: forces and NHS areas are blocks of demo seats."""
    feats = geo["features"]
    cent = [(f["properties"]["code"], shape(f["geometry"]).centroid) for f in feats]

    def blocks(n_x: int, n_y: int, prefix: str, label: str) -> list[dict]:
        xs = [c.x for _, c in cent]
        ys = [c.y for _, c in cent]
        x0, x1, y0, y1 = min(xs), max(xs) + 1e-9, min(ys), max(ys) + 1e-9
        groups: dict[tuple, list] = {}
        for (code, c), f in zip(cent, feats):
            k = (int((c.x - x0) / (x1 - x0) * n_x), int((c.y - y0) / (y1 - y0) * n_y))
            groups.setdefault(k, []).append(shape(f["geometry"]).buffer(0.001))
        return [{"code": f"{prefix}{i:02d}", "name": f"{label} {i:02d}", "geometry": unary_union(g)}
                for i, (_, g) in enumerate(sorted(groups.items()), start=1)]

    police = blocks(5, 9, "DEMO-PFA", "Demo Police")
    health = blocks(6, 8, "DEMO-ICB", "Demo NHS area")
    pick = lambda n: [cent[int(i)][1] for i in rng.integers(0, len(cent), size=n)]
    court_types = [["Crown Court"], ["Magistrates' Court"], ["County Court", "Family Court"], ["Tribunal"]]
    courts = [{"id": f"demo-court-{i}", "name": f"Demo {court_types[i % 4][0]} {i:03d}", "types": court_types[i % 4],
               "lat": round(c.y + rng.normal(0, 0.03), 5), "lon": round(c.x + rng.normal(0, 0.03), 5), "codes": [str(100 + i)]}
              for i, c in enumerate(pick(160))]
    kinds = ["Acute & specialist", "Acute & specialist", "Mental health & community", "Ambulance"]
    trusts = [{"code": f"DT{i:03d}", "name": f"Demo {('Hospitals', 'Hospitals', 'Partnership', 'Ambulance Service')[i % 4]} NHS Trust {i:03d}",
               "postcode": "", "kind": kinds[i % 4], "lat": round(c.y, 5), "lon": round(c.x, 5)}
              for i, c in enumerate(pick(90))]
    acute = [t for t in trusts if t["kind"] == "Acute & specialist"]
    nearest: dict[str, list] = {}
    for (code, c), f in zip(cent, feats):
        t = min(acute, key=lambda t: (t["lon"] - c.x) ** 2 + (t["lat"] - c.y) ** 2)
        nearest.setdefault(t["code"], []).append(shape(f["geometry"]).buffer(0.001))
    catchments = [{"code": k, "name": k, "geometry": unary_union(v)} for k, v in nearest.items()]
    return assemble(geo, seats, population, police, health, courts, trusts, "demo", catchments)
