"""The ONS Open Geography Portal's ArcGIS REST services: finding a service, and reading every row of a layer.

ONS renames and re-versions its services often, so sources find them by name pattern in the portal's listing
(``services``) rather than hard-coding a URL, and read them with ``features``/``rows``, which follow the
service's pagination.
"""

from __future__ import annotations

import logging
import re
import time

import requests

from .http import get_json

log = logging.getLogger(__name__)

ROOT = "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services"
PAGE = 2000  # rows per query: the portal's usual maximum

_SERVICES: set[str] = set()
MIN_LISTINGS, MAX_LISTINGS = 3, 8


def services(s: requests.Session, *wanted: re.Pattern) -> list[str]:
    """Names of the ONS portal's feature services.

    The portal's service listing sometimes leaves out a large share of its services (on 20 Nov 2026 a run lost
    the police force, ward, county and LSOA lookups at once), so several listings are combined and cached. If a
    ``wanted`` pattern still has no match, the portal is listed again (up to MAX_LISTINGS in all) before giving up.
    """
    def listing() -> None:
        data = get_json(s, ROOT, params={"f": "json"})
        _SERVICES.update(svc["name"] for svc in data.get("services", []) if svc.get("type") == "FeatureServer")

    done = 0
    if not _SERVICES:
        for _ in range(MIN_LISTINGS):
            listing()
            done += 1
    missing = lambda: [p for p in wanted if not any(p.search(n) for n in _SERVICES)]  # noqa: E731
    while missing() and done < MAX_LISTINGS:
        time.sleep(2)
        listing()
        done += 1
    if missing():
        log.warning("ONS portal listing still lacks %s after %d listings", [p.pattern for p in missing()], done)
    return sorted(_SERVICES)


def matching(s: requests.Session, pattern: re.Pattern) -> list[str]:
    """The portal's services whose names match ``pattern`` (from the start of the name), sorted."""
    return [n for n in services(s, pattern) if pattern.match(n)]


def layer(service: str, index: int = 0) -> str:
    """A layer's query base URL: ``<ROOT>/<service>/FeatureServer/<index>``."""
    return f"{ROOT}/{service}/FeatureServer/{index}"


def first_layer(s: requests.Session, service: str) -> str:
    """The service's first layer: not always layer 0 (the LSOA BFE service's only layer is 3)."""
    layers = get_json(s, f"{ROOT}/{service}/FeatureServer", params={"f": "json"}).get("layers") or [{"id": 0}]
    return layer(service, layers[0]["id"])


def _more(data: dict) -> bool:
    # JSON replies flag a truncated page at the top level; GeoJSON replies put the flag in "properties".
    return bool(data.get("exceededTransferLimit") or (data.get("properties") or {}).get("exceededTransferLimit"))


def features(s: requests.Session, url: str, *, where: str = "1=1", fields: str = "*", geojson: bool = False,
             page: int = PAGE, timeout: int = 120) -> list[dict]:
    """Every feature of a layer matching ``where``, following pagination.

    ``geojson=True`` returns GeoJSON features (geometry in WGS84, attributes in "properties"); otherwise ArcGIS
    JSON features without geometry (attributes in "attributes").
    """
    params = {"where": where, "outFields": fields, "resultRecordCount": page}
    params.update({"f": "geojson", "outSR": "4326"} if geojson else {"f": "json", "returnGeometry": "false"})
    out: list[dict] = []
    while True:
        data = get_json(s, f"{url}/query", params={**params, "resultOffset": len(out)}, timeout=timeout)
        batch = data.get("features", [])
        out += batch
        if not batch or not _more(data):
            return out


def rows(s: requests.Session, url: str, **kwargs) -> list[dict]:
    """Every row's attributes (no geometry), following pagination."""
    return [f.get("attributes") or {} for f in features(s, url, **kwargs)]


def field(row: dict, pattern: str):
    """The value of the first field whose name matches ``pattern`` in full, ignoring case (e.g. LAD\\d{2}CD for
    any year's council code)."""
    return next((v for k, v in row.items() if re.fullmatch(pattern, k, re.I)), None)


def round_coords(obj, nd: int = 4):
    """Round every coordinate in a GeoJSON coordinate array (4 dp is ~10 m)."""
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(float(v), nd) for v in obj]
        return [round_coords(o, nd) for o in obj]
    return obj
