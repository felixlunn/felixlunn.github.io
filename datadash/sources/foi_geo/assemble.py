"""Turning loaded FOI geographies into the published reference data: which seats each area overlaps, which
area and seat each court or trust sits in, simplified shapes for the map, and each seat's Lib Dem status."""

from __future__ import annotations

import json
import re
from pathlib import Path

import shapely
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from ... import arcgis
from ...geo import SeatLocator
from ...parties import is_lib_dem
from .loaders import trust_kind

SIMPLIFY = 0.003  # degrees (~300 m): plenty for areas the size of a police force or ICB
MIN_SHARE = 0.03  # ignore slivers where generalised boundaries don't quite line up
LAND_SIMPLIFY = 0.004


def nation_area(geo: dict, prefix: str, code: str, name: str) -> dict:
    """One area drawn as the union of a nation's seats (Police Scotland, PSNI)."""
    polys = [shape(f["geometry"]).buffer(0) for f in geo["features"] if f["properties"]["code"].startswith(prefix)]
    return {"code": code, "name": name, "geometry": unary_union(polys)}


def seat_overlaps(areas: list[dict], geo: dict) -> dict[str, list[list]]:
    """Area code -> [[seat code, share of the seat inside the area], ...], largest first."""
    seats = [(f["properties"]["code"], shape(f["geometry"]).buffer(0)) for f in geo["features"]]
    out = {}
    for a in areas:
        g = a["geometry"].buffer(0)
        hits = []
        for code, sg in seats:
            if sg.area and g.intersects(sg):
                share = g.intersection(sg).area / sg.area
                if share >= MIN_SHARE:
                    hits.append([code, round(min(share, 1.0), 3)])
        out[a["code"]] = sorted(hits, key=lambda h: -h[1])
    return out


def area_population(links: list[list], population: dict[str, float]) -> int | None:
    total = sum(population.get(seat, 0) * share for seat, share in links)
    return round(total) if total else None


def police_aliases(name: str) -> list[str]:
    base = re.sub(r"\s+police$", "", name.strip(), flags=re.IGNORECASE)
    out = {name, base, f"{base} Police", f"{base} Constabulary", f"{base} Police Service"}
    if base.lower().startswith("metropolitan"):
        out |= {"Metropolitan Police Service", "Met Police", "MPS"}
    if base.lower() == "city of london":
        out |= {"City of London Police"}
    return sorted(out)


def area_of_points(points: list[dict], areas: list[dict]) -> None:
    """Tag each point with the area (police force / NHS area) it falls in."""
    from shapely.geometry import Point
    from shapely.strtree import STRtree
    geoms = [a["geometry"] for a in areas]
    tree = STRtree(geoms)
    for p in points:
        pt = Point(p["lon"], p["lat"])
        p["area"] = next((areas[i]["code"] for i in tree.query(pt) if geoms[i].covers(pt)), None)


def to_feature(a: dict, layer: str) -> dict:
    # Snap to the 4-decimal grid the file uses, keeping the shape valid (simplifying then rounding coordinates could
    # make a shape's edges cross, which draws oddly: seven trust catchments did in Nov 2026).
    g = mapping(shapely.set_precision(a["geometry"].simplify(SIMPLIFY, preserve_topology=True), 1e-4))
    return {"type": "Feature", "properties": {"layer": layer, "code": a["code"], "name": a["name"]},
            "geometry": {"type": g["type"], "coordinates": arcgis.round_coords(g["coordinates"], 4)}}


def ld_status(seat: dict) -> dict:
    """{"ld": "held"} for Lib Dem seats, {"ld": "target"} where the Lib Dems came second in 2024, else {}."""
    if is_lib_dem(seat.get("party")):
        return {"ld": "held"}
    if is_lib_dem(seat.get("second_party_2024")):
        return {"ld": "target"}
    return {}


def catchments_of_current(catchments: list[dict], trusts: list[dict]) -> list[dict]:
    """Catchments under current trusts: one filed under a closed trust's code (OHID's file can predate a merger) goes to
    the trust that took it over, merged with that trust's own; catchments of no current trust are left out."""
    heir = {t["code"]: t["code"] for t in trusts}
    for t in trusts:
        for a in t.get("aliases", []):
            if re.fullmatch(r"[A-Z0-9]{3,5}", a):  # aliases hold former codes as well as names
                heir.setdefault(a, t["code"])
    shapes: dict[str, list] = {}
    for c in catchments:
        if c["code"] in heir:
            shapes.setdefault(heir[c["code"]], []).append(c["geometry"])
    names = {t["code"]: t["name"] for t in trusts}
    return [{"code": code, "name": names[code], "geometry": parts[0] if len(parts) == 1 else unary_union(parts).buffer(0)}
            for code, parts in shapes.items()]


def assemble(geo: dict, seats: list[dict], population: dict[str, float], police: list[dict], health: list[dict],
             courts: list[dict] | None, trusts: list[dict] | None, as_of: str,
             catchments: list[dict] | None = None) -> tuple[dict, dict]:
    """(reference JSON, areas GeoJSON) from loaded layers. Pure apart from geometry work: used by the demo too."""
    locator = SeatLocator(geo)
    layers, features = {}, []
    for layer, label, areas in (("police", "Police force areas", police), ("health", "NHS areas (ICBs and Welsh health boards)", health)):
        links = seat_overlaps(areas, geo)
        layers[layer] = {"label": label, "areas": [
            {"code": a["code"], "name": a["name"], "aliases": police_aliases(a["name"]) if layer == "police" else [a["name"]],
             "population": area_population(links[a["code"]], population), "seats": links[a["code"]]}
            for a in sorted(areas, key=lambda a: a["name"])]}
        features += [to_feature(a, layer) for a in areas]
    points = {}
    if courts is not None:
        area_of_points(courts, police)
        for c in courts:
            c["seat"] = locator.seat(c["lon"], c["lat"])
        points["courts"] = sorted(courts, key=lambda c: c["name"])
    if trusts is not None:
        area_of_points(trusts, health)
        drawn = catchments_of_current(catchments or [], trusts)
        links = seat_overlaps(drawn, geo)
        for t in trusts:
            t["seat"] = locator.seat(t["lon"], t["lat"])
            t["kind"] = trust_kind(t["name"], t["code"] in links)
            if t["code"] in links:  # official catchment: the seats whose residents mostly use the trust
                t["catchment"] = links[t["code"]]
        points["trusts"] = sorted(trusts, key=lambda t: t["name"])
        features += [to_feature(c, "trust") for c in drawn]
    # The land of each jurisdiction (England & Wales, Scotland, Northern Ireland), for clipping approximate court
    # areas to the coast in the browser without letting a court in one jurisdiction cover another.
    nation = lambda c: c[0] if c[:1] in ("S", "N") else "EW"  # noqa: E731 - England, Wales (and demo seats)
    for code in ("EW", "S", "N"):
        parts = [shape(f["geometry"]).buffer(0) for f in geo["features"] if nation(f["properties"]["code"]) == code]
        if parts:
            land = unary_union(parts).buffer(0.002).simplify(LAND_SIMPLIFY, preserve_topology=True)
            features.append(to_feature({"code": code, "name": code, "geometry": land}, "land"))
    # Each seat's centre: lets the browser tell which court in a response is nearest to a seat.
    centre = {f["properties"]["code"]: shape(f["geometry"]).representative_point() for f in geo["features"]}
    ref = {"version": 1, "as_of": as_of, "layers": layers, "points": points,
           "seats": [{"code": st["code"], "name": st["name"], "mp": st.get("mp"), "party": st.get("party"), **ld_status(st),
                      **({"lon": round(centre[st["code"]].x, 4), "lat": round(centre[st["code"]].y, 4)} if st["code"] in centre else {})}
                     for st in seats]}
    return ref, {"type": "FeatureCollection", "features": features}


def write_foi(out_dir: Path, ref: dict, areas: dict) -> None:
    d = out_dir / "foi"
    d.mkdir(parents=True, exist_ok=True)
    (d / "reference.json").write_text(json.dumps(ref, separators=(",", ":"), allow_nan=False))
    (d / "areas.geojson").write_text(json.dumps(areas, separators=(",", ":")))
