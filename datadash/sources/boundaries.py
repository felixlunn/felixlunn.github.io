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

from .. import arcgis

log = logging.getLogger(__name__)

SERVICE_PATTERN = re.compile(r"^Westminster_Parliamentary_Constituencies_July_2024_Boundaries_UK_(BUC|BGC|BSC)", re.I)
RES_ORDER = {"BUC": 0, "BSC": 1, "BGC": 2}


def find_service(s: requests.Session) -> str:
    override = os.environ.get("PCON_BOUNDARY_SERVICE")
    if override:
        return override
    candidates = []
    for name in arcgis.matching(s, SERVICE_PATTERN):
        candidates.append((RES_ORDER[SERVICE_PATTERN.match(name).group(1).upper()], name))
    if not candidates:
        raise LookupError("No July 2024 Westminster constituency boundary service found on the ONS portal")
    name = sorted(candidates)[0][1]
    log.info("Boundary service: %s", name)
    return arcgis.layer(name)


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
            "geometry": {"type": g["type"], "coordinates": arcgis.round_coords(g["coordinates"])},
        })
    out.sort(key=lambda f: f["properties"]["code"])
    return out


def load_boundaries(s: requests.Session) -> dict:
    features = arcgis.features(s, find_service(s), fields="PCON24CD,PCON24NM", geojson=True, page=1000)
    feats = clean_features(features)
    if len(feats) < 600:
        raise ValueError(f"Expected ~650 constituencies, got {len(feats)}")
    return {"type": "FeatureCollection", "features": feats}


LOOKUP_PATTERN = re.compile(r"lsoa.?(20)?21.*(pcon.?24|westminster.*2024)", re.I)


def find_lookup_service(s: requests.Session) -> str:
    override = os.environ.get("LSOA_PCON_LOOKUP_SERVICE")
    if override:
        return override
    names = [n for n in arcgis.services(s, LOOKUP_PATTERN) if LOOKUP_PATTERN.search(n)]
    if not names:
        raise LookupError("No LSOA 2021 -> PCON 2024 lookup service found on the ONS portal")
    name = sorted(names, key=len)[0]
    log.info("LSOA lookup service: %s", name)
    return arcgis.layer(name)


def parse_lookup(rows: list[dict]) -> dict[str, str]:
    out = {}
    for r in rows:
        a = {k.upper(): v for k, v in (r.get("attributes") or r.get("properties") or r).items()}
        if a.get("LSOA21CD") and a.get("PCON24CD"):
            out[a["LSOA21CD"]] = a["PCON24CD"]
    return out


def load_lsoa_pcon_lookup(s: requests.Session) -> dict[str, str]:
    """ONS best-fit lookup from 2021 LSOAs to July 2024 Westminster constituencies (England & Wales)."""
    rows = arcgis.features(s, find_lookup_service(s))
    lookup = parse_lookup(rows)
    if len(lookup) < 30_000:
        raise ValueError(f"LSOA lookup looks incomplete: {len(lookup)} rows")
    return lookup
