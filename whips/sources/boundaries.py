"""Westminster constituency boundaries (July 2024) from the ONS Open Geography Portal.

Uses the ultra-generalised clipped ("BUC") boundaries, which are designed for
web mapping. Coordinates are rounded to 4 decimal places (~10m) to keep the
file small. The service is discovered from the portal's ArcGIS REST catalogue
so a renamed service does not break the pipeline.
"""

from __future__ import annotations

import logging
import os
import re

import requests
from shapely.geometry import mapping, shape

from ..http import get_json

log = logging.getLogger(__name__)

ARCGIS_ROOT = "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services"
SERVICE_PATTERN = re.compile(r"^Westminster_Parliamentary_Constituencies_July_2024_Boundaries_UK_(BUC|BGC|BSC)", re.I)
RES_ORDER = {"BUC": 0, "BSC": 1, "BGC": 2}


def find_service(s: requests.Session) -> str:
    override = os.environ.get("PCON_BOUNDARY_SERVICE")
    if override:
        return override
    data = get_json(s, ARCGIS_ROOT, params={"f": "json"})
    candidates = []
    for svc in data.get("services", []):
        m = SERVICE_PATTERN.match(svc.get("name", ""))
        if m and svc.get("type") == "FeatureServer":
            candidates.append((RES_ORDER[m.group(1).upper()], svc["name"]))
    if not candidates:
        raise LookupError("No July 2024 Westminster constituency boundary service found on the ONS portal")
    name = sorted(candidates)[0][1]
    log.info("Boundary service: %s", name)
    return f"{ARCGIS_ROOT}/{name}/FeatureServer/0"


def _round_coords(obj, nd=4):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(float(v), nd) for v in obj]
        return [_round_coords(o, nd) for o in obj]
    return obj


def clean_features(features: list[dict]) -> list[dict]:
    """Keep just code + name, fix invalid rings, round coordinates."""
    out = []
    for f in features:
        props = {k.upper(): v for k, v in (f.get("properties") or {}).items()}
        code = props.get("PCON24CD")
        name = props.get("PCON24NM")
        if not code or not f.get("geometry"):
            continue
        geom = shape(f["geometry"])
        if not geom.is_valid:
            geom = geom.buffer(0)
        g = mapping(geom)
        out.append({
            "type": "Feature",
            "properties": {"code": code, "name": name},
            "geometry": {"type": g["type"], "coordinates": _round_coords(g["coordinates"])},
        })
    out.sort(key=lambda f: f["properties"]["code"])
    return out


def load_boundaries(s: requests.Session) -> dict:
    layer = find_service(s)
    features, offset = [], 0
    while True:
        data = get_json(s, f"{layer}/query", params={
            "where": "1=1", "outFields": "PCON24CD,PCON24NM", "outSR": "4326",
            "f": "geojson", "resultOffset": offset, "resultRecordCount": 1000,
        })
        batch = data.get("features", [])
        features.extend(batch)
        if not batch or not (data.get("exceededTransferLimit") or data.get("properties", {}).get("exceededTransferLimit")):
            break
        offset += len(batch)
    feats = clean_features(features)
    if len(feats) < 600:
        raise ValueError(f"Expected ~650 constituencies, got {len(feats)}")
    return {"type": "FeatureCollection", "features": feats}


LOOKUP_PATTERN = re.compile(r"lsoa.?(20)?21.*(pcon.?24|westminster.*2024)", re.I)


def find_lookup_service(s: requests.Session) -> str:
    override = os.environ.get("LSOA_PCON_LOOKUP_SERVICE")
    if override:
        return override
    data = get_json(s, ARCGIS_ROOT, params={"f": "json"})
    names = [svc["name"] for svc in data.get("services", [])
             if svc.get("type") == "FeatureServer" and LOOKUP_PATTERN.search(svc.get("name", ""))]
    if not names:
        raise LookupError("No LSOA 2021 -> PCON 2024 lookup service found on the ONS portal")
    name = sorted(names, key=len)[0]
    log.info("LSOA lookup service: %s", name)
    return f"{ARCGIS_ROOT}/{name}/FeatureServer/0"


def parse_lookup(rows: list[dict]) -> dict[str, str]:
    out = {}
    for r in rows:
        a = {k.upper(): v for k, v in (r.get("attributes") or r.get("properties") or r).items()}
        if a.get("LSOA21CD") and a.get("PCON24CD"):
            out[a["LSOA21CD"]] = a["PCON24CD"]
    return out


def load_lsoa_pcon_lookup(s: requests.Session) -> dict[str, str]:
    """ONS best-fit lookup from 2021 LSOAs to July 2024 Westminster constituencies (England & Wales)."""
    layer = find_lookup_service(s)
    rows, offset = [], 0
    while True:
        data = get_json(s, f"{layer}/query", params={
            "where": "1=1", "outFields": "*", "returnGeometry": "false", "f": "json",
            "resultOffset": offset, "resultRecordCount": 2000,
        })
        batch = data.get("features", [])
        rows.extend(batch)
        if not batch or not data.get("exceededTransferLimit"):
            break
        offset += len(batch)
    lookup = parse_lookup(rows)
    if len(lookup) < 30_000:
        raise ValueError(f"LSOA lookup looks incomplete: {len(lookup)} rows")
    return lookup
