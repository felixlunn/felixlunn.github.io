"""Neighbourhood (LSOA) census profiles for selected constituencies.

For each chosen seat, writes ``lsoa/<PCON24CD>.json`` with every LSOA in it
(ONS best-fit lookup): ward and council names, simplified boundaries, the
census metric values, and each value's percentile among all ~35,700 LSOAs in
England and Wales. Files are small (one seat each) and the dashboard loads
them on demand.

Census 2021 small-area data covers England and Wales only.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from shapely.geometry import mapping, shape

from ..http import get_json
from .boundaries import ARCGIS_ROOT, _round_coords

log = logging.getLogger(__name__)

# ONS renames these layers from time to time: the long form ("Lower_layer_Super_Output_Areas_December_2021_
# Boundaries_EW_BGC_V5") and the short form ("LSOA_2021_EW_BSC_V4_RUC") are both recognised.
BOUNDARY_PATTERN = re.compile(r"^(?:Lower_layer_Super_Output_Areas_December_2021_Boundaries_EW|LSOA_2021_EW)_(BFC|BGC|BFE|BSC)", re.I)
WARD_PATTERN = re.compile(r"^LSOA21_WD(\d{2})_LAD(\d{2})_EW_LU", re.I)
BATCH = 150  # LSOA codes per ArcGIS "IN (...)" query


def _services(s: requests.Session) -> list[str]:
    data = get_json(s, ARCGIS_ROOT, params={"f": "json"})
    return [svc["name"] for svc in data.get("services", []) if svc.get("type") == "FeatureServer"]


# Boundary versions, most preferred first. ONS has withdrawn the clipped full (BFC) and 20m generalised (BGC) LSOA
# layers; the full-resolution "extent of the realm" layer (BFE) remains and is used, trimmed to the coastline with
# the 200m super-generalised (BSC) layer. BSC alone (blocky at street scale) is the last resort.
RES_PREFERENCE = ["BFC", "BGC", "BFE", "BSC"]
COAST_MARGIN = 0.003  # degrees (~200-300 m): BFE is trimmed to its BSC shape grown by this, removing tidal flats
SIMPLIFY = 0.00008  # degrees (~6-9 m): street-level detail at a fraction of the full-resolution size


def find_boundary_services(names: list[str]) -> tuple[str, str | None]:
    """(service to draw with, coarse BSC service to trim it to the coast, or None when not needed)."""
    by_res: dict[str, str] = {}
    for n in sorted(names):
        m = BOUNDARY_PATTERN.match(n)
        if m:
            by_res.setdefault(m.group(1).upper(), n)
    best = next((r for r in RES_PREFERENCE if r in by_res), None)
    if best is None:
        raise LookupError("No LSOA 2021 boundary service found on the ONS portal")
    return by_res[best], (by_res.get("BSC") if best == "BFE" else None)


def layer_url(s: requests.Session, service: str) -> str:
    """The service's first layer: not always layer 0 (the BFE service's only layer is 3)."""
    layers = get_json(s, f"{ARCGIS_ROOT}/{service}/FeatureServer", params={"f": "json"}).get("layers") or [{"id": 0}]
    return f"{ARCGIS_ROOT}/{service}/FeatureServer/{layers[0]['id']}"


def find_ward_service(names: list[str]) -> str:
    hits = sorted(((int(WARD_PATTERN.match(n).group(1)), n) for n in names if WARD_PATTERN.match(n)), reverse=True)
    if not hits:
        raise LookupError("No LSOA 2021 to ward lookup found on the ONS portal")
    return f"{ARCGIS_ROOT}/{hits[0][1]}/FeatureServer/0"


def _query_in(s: requests.Session, layer: str, field: str, codes: list[str], **params) -> list[dict]:
    out = []
    for i in range(0, len(codes), BATCH):
        chunk = codes[i:i + BATCH]
        where = f"{field} IN ({','.join(repr(c) for c in chunk)})"
        # POST: long IN lists exceed URL limits.
        r = s.post(f"{layer}/query", data={"where": where, **params}, timeout=120)
        r.raise_for_status()
        out.extend(r.json().get("features", []))
    return out


def load_wards(s: requests.Session, layer: str, codes: list[str]) -> dict[str, dict]:
    rows = _query_in(s, layer, "LSOA21CD", codes, outFields="*", returnGeometry="false", f="json")
    out = {}
    for r in rows:
        a = {k.upper(): v for k, v in (r.get("attributes") or {}).items()}
        ward = next((a[k] for k in a if re.fullmatch(r"WD\d{2}NM", k)), None)
        lad = next((a[k] for k in a if re.fullmatch(r"LAD\d{2}NM", k)), None)
        if a.get("LSOA21CD"):
            out[a["LSOA21CD"]] = {"name": a.get("LSOA21NM"), "ward": ward, "council": lad}
    return out


def _shapes(s: requests.Session, layer: str, codes: list[str]) -> dict:
    feats = _query_in(s, layer, "LSOA21CD", codes, outFields="LSOA21CD", outSR="4326", f="geojson")
    out = {}
    for f in feats:
        props = {k.upper(): v for k, v in (f.get("properties") or {}).items()}
        if props.get("LSOA21CD") and f.get("geometry"):
            geom = shape(f["geometry"])
            out[props["LSOA21CD"]] = geom if geom.is_valid else geom.buffer(0)
    return out


def trim_to_coast(detail, coarse):
    """Cut a full-extent LSOA back to (near) the coastline: keep only what lies within COAST_MARGIN of its coarse
    clipped shape. Inland edges are unaffected (the coarse shape is never that far off); tidal flats are removed."""
    if coarse is None:
        return detail
    trimmed = detail.intersection(coarse.buffer(COAST_MARGIN))
    return trimmed if not trimmed.is_empty else detail


def load_geometries(s: requests.Session, layer: str, codes: list[str], coast_layer: str | None = None) -> dict[str, dict]:
    shapes = _shapes(s, layer, codes)
    coarse = _shapes(s, coast_layer, codes) if coast_layer else {}
    out = {}
    for code, geom in shapes.items():
        g = mapping(trim_to_coast(geom, coarse.get(code)).simplify(SIMPLIFY, preserve_topology=True))
        out[code] = {"type": g["type"], "coordinates": _round_coords(g["coordinates"], 5)}
    return out


def metric_values(frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """LSOA x metric values (num/den) and their percentiles (0-100) among all LSOAs in England & Wales."""
    vals = pd.DataFrame({mid: (f["num"] / f["den"]).replace([np.inf, -np.inf], np.nan) for mid, f in frames.items()})
    pct = vals.rank(pct=True, method="average") * 100
    return vals, pct


def _clean(v, nd=2):
    return None if v is None or pd.isna(v) else round(float(v), nd)


def seat_file(seat: str, name: str, lsoas: list[str], vals: pd.DataFrame, pct: pd.DataFrame,
              wards: dict[str, dict], geoms: dict[str, dict], deciles: pd.Series | None = None) -> dict:
    lsoas = sorted(lsoas, key=lambda c: ((wards.get(c) or {}).get("ward") or "", c))
    metrics = [m for m in vals.columns if vals.loc[vals.index.intersection(lsoas), m].notna().any()]
    return {
        "seat": seat,
        "name": name,
        "lsoas": [{"code": c, "name": (wards.get(c) or {}).get("name") or c, "ward": (wards.get(c) or {}).get("ward"),
                   "council": (wards.get(c) or {}).get("council")} for c in lsoas],
        "metrics": metrics,
        "values": {m: [_clean(vals.at[c, m]) if c in vals.index else None for c in lsoas] for m in metrics},
        "pct": {m: [None if c not in pct.index or pd.isna(pct.at[c, m]) else int(round(pct.at[c, m])) for c in lsoas] for m in metrics},
        # IMD 2025 decile (1 = most deprived 10% in England); null in Wales.
        "imd_decile": [None if deciles is None or c not in deciles.index or pd.isna(deciles[c]) else int(deciles[c]) for c in lsoas],
        "geo": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"code": c}, "geometry": geoms[c]} for c in lsoas if c in geoms
        ]},
    }


def write_seat_files(s: requests.Session, out_dir: Path, seats: dict[str, str], lookup: dict[str, str],
                     frames: dict[str, pd.DataFrame], deciles: pd.Series | None = None) -> dict:
    """Write one neighbourhood file per seat in ``seats`` ({code: name}); returns a summary for data.json."""
    by_seat: dict[str, list[str]] = {}
    for lsoa, pcon in lookup.items():
        if pcon in seats:
            by_seat.setdefault(pcon, []).append(lsoa)
    if not by_seat:
        raise ValueError("None of the chosen seats has LSOAs in England & Wales")
    wanted = sorted(c for cs in by_seat.values() for c in cs)
    names = _services(s)
    wards = load_wards(s, find_ward_service(names), wanted)
    detail, coast = find_boundary_services(names)
    log.info("Neighbourhood boundaries: %s%s", detail, f" trimmed to the coast with {coast}" if coast else "")
    geoms = load_geometries(s, layer_url(s, detail), wanted, layer_url(s, coast) if coast else None)
    vals, pct = metric_values(frames)
    folder = out_dir / "lsoa"
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.json"):
        old.unlink()
    for pcon, lsoas in by_seat.items():
        doc = seat_file(pcon, seats[pcon], lsoas, vals, pct, wards, geoms, deciles)
        (folder / f"{pcon}.json").write_text(json.dumps(doc, separators=(",", ":"), allow_nan=False))
    log.info("Neighbourhoods: %d seats, %d LSOAs, %d metrics", len(by_seat), len(wanted), vals.shape[1])
    return {"seats": sorted(by_seat), "lsoas": len(wanted), "metrics": int(vals.shape[1])}
