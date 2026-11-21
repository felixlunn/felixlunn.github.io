"""Reference geographies for the FOI research section: the bodies FOI requests go to, and the seats they cover.

The FOI section maps uploaded FOI responses by the body that answered them. This writes the public reference
data it matches uploads against (the uploads themselves live in the private FOI database, never here):

- Police force areas (ONS boundaries, England & Wales; Police Scotland and PSNI drawn from their nations' seats).
- Courts and tribunals (HMCTS Find a court or tribunal), as points.
- NHS trusts (NHS Organisation Data Service), as points located from their head office postcode.
- NHS areas: integrated care boards (England) and local health boards (Wales), ONS boundaries.

Each area lists the seats it overlaps (share of the seat's area inside it), and each point the seat it sits in,
so a seat's office can see which force, trusts and courts serve it.
"""

from __future__ import annotations

import logging
import re

import pandas as pd
import requests
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from ..geo import SeatLocator
from ..http import get_json
from .boundaries import ARCGIS_ROOT, _round_coords
from ..ods import read_ods
from .lsoa import _services, layer_url

log = logging.getLogger(__name__)

SOURCE_URL = "https://geoportal.statistics.gov.uk/"
COURTS_URL = "https://www.find-court-tribunal.service.gov.uk/search/results.json"
COURTS_PAGE = "https://www.find-court-tribunal.service.gov.uk/"
ODS_URL = "https://directory.spineservices.nhs.uk/ORD/2-0-0/organisations"
ODS_PAGE = "https://digital.nhs.uk/services/organisation-data-service"
POSTCODES = "https://api.postcodes.io/postcodes"
GOVUK_SEARCH = "https://www.gov.uk/api/search.json"
GOVUK_CONTENT = "https://www.gov.uk/api/content"
CATCHMENT_PREFIX = "/government/statistics/nhs-acute-hospital-trust-catchment-populations"
CATCHMENT_PAGE = "https://www.gov.uk/government/collections/nhs-acute-hospital-trust-catchment-populations"
MSOA_PATTERN = re.compile(r"^(?:MSOA_2021_EW|Middle_layer_Super_Output_Areas_\(December_2021\)_Boundaries_EW)_(BSC|BGC|BFC|BFE)", re.I)
MSOA_PREFERENCE = {"BSC": 0, "BGC": 1, "BFC": 2, "BFE": 3}  # trust catchments are large: the coarsest layer is plenty
LAND_SIMPLIFY = 0.004

RES_ORDER = {"BUC": 0, "BSC": 1, "BGC": 2}
LAYERS = {
    # kind: (service name pattern with groups (year, resolution), code field pattern, name field pattern)
    "police": (re.compile(r"^Police_Force_Areas_(?:Dec_)?(\d{4})_EW_(BUC|BSC|BGC)$", re.IGNORECASE), r"PFA\d{2}CD", r"PFA\d{2}NM"),
    "icb": (re.compile(r"^Integrated_Care_Boards_April_(\d{4})(?:_Boundaries)?_EN_(BUC|BSC|BGC)$", re.IGNORECASE), r"ICB\d{2}CD", r"ICB\d{2}NM"),
    "lhb": (re.compile(r"^Local_Health_Boards_December_(\d{4})_WA_(BUC|BSC|BGC)$", re.IGNORECASE), r"LHB\d{2}CD", r"LHB\d{2}NM"),
}
SIMPLIFY = 0.003  # degrees (~300 m): plenty for areas the size of a police force or ICB
MIN_SHARE = 0.03  # ignore slivers where generalised boundaries don't quite line up


def pick_service(names: list[str], pattern: re.Pattern) -> str:
    hits = [(int(m.group(1)), -RES_ORDER[m.group(2).upper()], n) for n in names if (m := pattern.match(n))]
    if not hits:
        raise LookupError(f"No ONS service matches {pattern.pattern}")
    return max(hits)[2]


def _field(props: dict, pattern: str):
    return next((v for k, v in props.items() if re.fullmatch(pattern, k, re.IGNORECASE)), None)


def load_layer(s: requests.Session, names: list[str], kind: str) -> list[dict]:
    pattern, code_f, name_f = LAYERS[kind]
    layer = f"{ARCGIS_ROOT}/{pick_service(names, pattern)}/FeatureServer/0"
    data = get_json(s, f"{layer}/query", params={"where": "1=1", "outFields": "*", "outSR": "4326", "f": "geojson"})
    out = []
    for f in data.get("features", []):
        p = f.get("properties") or {}
        code, name = _field(p, code_f), _field(p, name_f)
        if code and name and f.get("geometry"):
            out.append({"code": code, "name": name, "geometry": shape(f["geometry"])})
    if not out:
        raise ValueError(f"No {kind} boundaries returned from {layer}")
    log.info("FOI %s areas: %d", kind, len(out))
    return out


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


def load_courts(s: requests.Session) -> list[dict]:
    rows = get_json(s, COURTS_URL, params={"q": ""}, timeout=180)
    out = []
    for c in rows:
        if c.get("lat") is None or c.get("lon") is None or not c.get("name"):
            continue
        out.append({"id": c.get("slug") or c["name"], "name": c["name"], "types": c.get("types") or [],
                    "lat": round(float(c["lat"]), 5), "lon": round(float(c["lon"]), 5),
                    "codes": [str(x) for x in (c.get("cci_code"), c.get("magistrate_code"), c.get("number")) if x]})
    if len(out) < 300:
        raise ValueError(f"Expected several hundred courts, got {len(out)}")
    return out


SMALL = {"and", "of", "the", "for", "upon", "on", "in", "with", "at"}


def title_name(name: str) -> str:
    """ODS names are upper case: 'MANCHESTER UNIVERSITY NHS FOUNDATION TRUST' -> 'Manchester University NHS Foundation Trust'."""
    words = []
    for i, w in enumerate(name.split()):
        lw = w.lower()
        words.append("NHS" if lw == "nhs" else lw if (lw in SMALL and i) else w.capitalize())
    return re.sub(r"(?<=-)(\w)", lambda m: m.group(1).upper(), " ".join(words))


def trust_kind(name: str) -> str:
    n = name.lower()
    if "ambulance" in n:
        return "Ambulance"
    if re.search(r"mental health|partnership|psychiatr|tavistock|care trust", n):
        return "Mental health & community"
    if "community" in n:
        return "Community"
    return "Acute & specialist"


def load_trusts(s: requests.Session) -> list[dict]:
    orgs = get_json(s, ODS_URL, params={"PrimaryRoleId": "RO197", "Status": "Active", "Limit": 1000}).get("Organisations", [])
    trusts = [{"code": o["OrgId"], "name": title_name(o["Name"]), "postcode": (o.get("PostCode") or "").strip().upper()}
              for o in orgs if o.get("OrgId") and o.get("Name") and "ONLINE" not in o["Name"].upper()]
    pcs = sorted({t["postcode"] for t in trusts if t["postcode"]})
    where = {}
    for i in range(0, len(pcs), 100):
        r = s.post(POSTCODES, json={"postcodes": pcs[i:i + 100]}, timeout=60)
        r.raise_for_status()
        for item in r.json().get("result", []):
            res = item.get("result") or {}
            if res.get("latitude") is not None:
                where[item["query"].strip().upper()] = (round(res["latitude"], 5), round(res["longitude"], 5))
    out = []
    for t in trusts:
        if t["postcode"] in where:
            t["lat"], t["lon"] = where[t["postcode"]]
            t["kind"] = trust_kind(t["name"])
            out.append(t)
    if len(out) < 150:
        raise ValueError(f"Expected ~200 NHS trusts, got {len(out)}")
    return out


def find_catchment_file(s: requests.Session) -> tuple[str, str]:
    """(data tables .ods URL, title) of OHID's latest NHS acute trust catchment populations release."""
    res = get_json(s, GOVUK_SEARCH, params={"q": "NHS acute hospital trust catchment populations", "count": 20}).get("results", [])
    pages = sorted((r for r in res if str(r.get("link", "")).startswith(CATCHMENT_PREFIX)),
                   key=lambda r: r.get("public_timestamp", ""), reverse=True)
    for r in pages[:3]:
        for a in get_json(s, GOVUK_CONTENT + r["link"]).get("details", {}).get("attachments", []):
            if str(a.get("url", "")).endswith(".ods") and "data table" in str(a.get("title", "")).lower():
                return a["url"], r.get("title", "")
    raise LookupError("No NHS acute trust catchment data tables found on GOV.UK")


def parse_fptp(sheet: pd.DataFrame) -> pd.DataFrame:
    """Trust code, name and MSOA for each MSOA's main trust ("first past the post"), latest catchment year."""
    head = next(i for i in range(min(20, len(sheet))) if (sheet.iloc[i].astype(str).str.strip() == "MSOA21CD").any())
    t = sheet.iloc[head + 1:].copy()
    t.columns = [re.sub(r"\s+", " ", str(c)).strip().lower() for c in sheet.iloc[head]]
    col = lambda *w: next(c for c in t.columns if all(x in c for x in w))  # noqa: E731
    year, fptp = col("catchment", "year"), col("first past")
    t = t[t[fptp].astype(str).str.strip().str.upper() == "TRUE"]
    t = t[t[year].astype(str) == max(t[year].astype(str))]
    return pd.DataFrame({"code": t[col("trust", "code")].astype(str).str.strip(), "name": t[col("trust", "name")].astype(str).str.strip(),
                         "msoa": t["msoa21cd"].astype(str).str.strip()}).drop_duplicates("msoa")


def load_msoa_shapes(s: requests.Session, names: list[str]) -> dict:
    hits = sorted((MSOA_PREFERENCE[m.group(1).upper()], n) for n in names if (m := MSOA_PATTERN.match(n)))
    if not hits:
        raise LookupError("No MSOA 2021 boundary service found on the ONS portal")
    layer = layer_url(s, hits[0][1])
    out, offset = {}, 0
    while True:
        data = get_json(s, f"{layer}/query", params={"where": "MSOA21CD LIKE 'E%'", "outFields": "MSOA21CD", "outSR": "4326",
                                                     "f": "geojson", "resultOffset": offset, "resultRecordCount": 2000}, timeout=180)
        batch = data.get("features", [])
        for f in batch:
            code = (f.get("properties") or {}).get("MSOA21CD")
            if code and f.get("geometry"):
                out[code] = shape(f["geometry"]).buffer(0)
        if not batch or not (data.get("exceededTransferLimit") or data.get("properties", {}).get("exceededTransferLimit")):
            return out
        offset += len(batch)


def catchment_areas(fptp: pd.DataFrame, msoas: dict) -> list[dict]:
    """One shape per trust: the MSOAs whose residents mostly use it, merged."""
    out = []
    for (code, name), g in fptp.groupby(["code", "name"]):
        parts = [msoas[m] for m in g["msoa"] if m in msoas]
        if parts:
            out.append({"code": code, "name": name, "geometry": unary_union(parts).buffer(0.0005).buffer(-0.0005)})
    return out


def load_catchments(s: requests.Session, names: list[str]) -> tuple[list[dict], str]:
    url, title = find_catchment_file(s)
    r = s.get(url, timeout=300)
    r.raise_for_status()
    sheets = read_ods(r.content, only={"All_admissions"})
    fptp = parse_fptp(next(iter(sheets.values())))
    areas = catchment_areas(fptp, load_msoa_shapes(s, names))
    if len(areas) < 80:
        raise ValueError(f"Expected ~120 trust catchments, got {len(areas)}")
    log.info("Trust catchments: %d (%s)", len(areas), title)
    return areas, title


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
    g = mapping(a["geometry"].simplify(SIMPLIFY, preserve_topology=True))
    return {"type": "Feature", "properties": {"layer": layer, "code": a["code"], "name": a["name"]},
            "geometry": {"type": g["type"], "coordinates": _round_coords(g["coordinates"], 4)}}


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
        known = {t["code"] for t in trusts}
        drawn = [c for c in (catchments or []) if c["code"] in known]
        links = seat_overlaps(drawn, geo)
        for t in trusts:
            t["seat"] = locator.seat(t["lon"], t["lat"])
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
           "seats": [{"code": st["code"], "name": st["name"], "mp": st.get("mp"), "party": st.get("party"),
                      **({"lon": round(centre[st["code"]].x, 4), "lat": round(centre[st["code"]].y, 4)} if st["code"] in centre else {})}
                     for st in seats]}
    return ref, {"type": "FeatureCollection", "features": features}


def load_foi_reference(s: requests.Session, geo: dict, seats: list[dict], population: dict[str, float], as_of: str) -> tuple[dict, dict, list[str]]:
    """Fetch every layer. Courts and trusts are each optional: a failure leaves them out and is reported."""
    names = _services(s, *(p for p, _, _ in LAYERS.values()))
    police = load_layer(s, names, "police")
    police += [nation_area(geo, "S", "S23000009", "Police Scotland"), nation_area(geo, "N", "N23000001", "Police Service of Northern Ireland")]
    health = load_layer(s, names, "icb") + load_layer(s, names, "lhb")
    problems = []
    courts = trusts = None
    try:
        courts = load_courts(s)
    except Exception as exc:
        log.exception("Courts list failed")
        problems.append(f"courts: {exc}"[:200])
    try:
        trusts = load_trusts(s)
    except Exception as exc:
        log.exception("NHS trusts list failed")
        problems.append(f"NHS trusts: {exc}"[:200])
    catchments = None
    try:
        catchments, _ = load_catchments(s, _services(s, MSOA_PATTERN))
    except Exception as exc:  # noqa: BLE001
        log.exception("Trust catchments failed")
        problems.append(f"trust catchments: {exc}"[:200])
    ref, areas = assemble(geo, seats, population, police, health, courts, trusts, as_of, catchments)
    return ref, areas, problems


def write_foi(out_dir, ref: dict, areas: dict) -> None:
    d = out_dir / "foi"
    d.mkdir(parents=True, exist_ok=True)
    import json
    (d / "reference.json").write_text(json.dumps(ref, separators=(",", ":"), allow_nan=False))
    (d / "areas.geojson").write_text(json.dumps(areas, separators=(",", ":")))


def demo_reference(geo: dict, seats: list[dict], population: dict[str, float], rng) -> tuple[dict, dict]:
    """SYNTHETIC FOI reference for the demo build: forces and NHS areas are blocks of demo seats."""
    from shapely.geometry import Point  # noqa: F401 - shapely is already required
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
