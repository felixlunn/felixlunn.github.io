"""Shared geography helpers: placing points in constituencies, and British grid references.

Used by every source that has point locations (rail stations, storm overflows,
chargepoints, ...).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

# Ordnance Survey 100 km grid squares: first letter = 500 km square, second = 100 km square (no "I").
_LETTERS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"
_TO_WGS84 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)


def ngr_to_en(ngr: str) -> tuple[float, float] | None:
    """An OS grid reference such as "SP6419046470" or "SP 64190 46470" -> (easting, northing) in metres."""
    m = re.fullmatch(r"([A-HJ-Z]{2})\s*(\d+)\s*(\d*)", str(ngr).strip().upper())
    if not m:
        return None
    letters, a, b = m.groups()
    digits = a + b
    if not digits or len(digits) % 2:
        return None
    half = len(digits) // 2
    scale = 10 ** (5 - half)
    l1, l2 = _LETTERS.index(letters[0]), _LETTERS.index(letters[1])
    e100 = ((l1 - 2) % 5) * 5 + (l2 % 5)
    n100 = (19 - (l1 // 5) * 5) - (l2 // 5)
    if not (0 <= e100 <= 7 and 0 <= n100 <= 12):
        return None
    return e100 * 100_000 + int(digits[:half]) * scale, n100 * 100_000 + int(digits[half:]) * scale


def en_to_lonlat(eastings: Iterable[float], northings: Iterable[float]) -> tuple[list[float], list[float]]:
    lon, lat = _TO_WGS84.transform(list(eastings), list(northings))
    return list(lon), list(lat)


class SeatLocator:
    """Point-in-polygon lookup against the constituency boundaries.

    The boundaries are generalised and clipped to the coastline, so points on a riverbank or at the coast (or a
    sea outfall) can fall just outside every seat: those go to the nearest seat if it's within ``tolerance``
    degrees (0.02 ~ 2 km).
    """

    def __init__(self, geo: dict):
        self.polys = [shape(f["geometry"]) for f in geo["features"]]
        self.codes = [f["properties"]["code"] for f in geo["features"]]
        self.tree = STRtree(self.polys)

    def seat(self, lon: float, lat: float, tolerance: float = 0.02) -> str | None:
        p = Point(lon, lat)
        hit = next((self.codes[i] for i in self.tree.query(p) if self.polys[i].covers(p)), None)
        if hit is None and tolerance:
            i = self.tree.nearest(p)
            hit = self.codes[i] if self.polys[i].distance(p) < tolerance else None
        return hit

    def seats(self, lons: Iterable[float], lats: Iterable[float], tolerance: float = 0.02) -> list[str | None]:
        return [self.seat(lon, lat, tolerance) for lon, lat in zip(lons, lats)]
