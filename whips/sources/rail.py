"""Rail station usage by constituency, Great Britain (ORR estimates of station usage).

ORR publishes entries and exits for every station each year; DfT's NaPTAN gives
station locations. Stations are matched by name, placed in a constituency by
point-in-polygon against the July 2024 boundaries, and summed per seat.

(Delays and cancellations need Rail Data Marketplace credentials: not included.)
"""

from __future__ import annotations

import io
import logging
import re

import pandas as pd
import requests
from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from ..metrics import MetricMeta

log = logging.getLogger(__name__)

ORR_PAGE = "https://dataportal.orr.gov.uk/statistics/usage/estimates-of-station-usage/"
ORR_FALLBACK = "https://dataportal.orr.gov.uk/media/1909/table-1410-passenger-entries-and-exits-and-interchanges-by-station.csv"
NAPTAN = "https://naptan.api.dft.gov.uk/v1/access-nodes"

RAIL_METRICS = [
    MetricMeta("rail_journeys_per_resident", "Rail journeys per resident", "transport", "ratio",
               "Entries and exits at the constituency's railway stations in a year (ORR estimates), per resident.",
               "ORR estimates of station usage", "neutral", 1, ("rail",)),
    MetricMeta("rail_stations", "Railway stations", "transport", "stations",
               "Number of National Rail stations in the constituency (national figure: average per seat).",
               "ORR estimates of station usage", "neutral", 0, ("rail",)),
]


def norm(name: str) -> str:
    s = str(name).lower().replace("&", "and").replace("'", "").replace("’", "")
    s = re.sub(r"\[note.*?\]", "", s)
    s = re.sub(r"\b(rail|railway) station\b", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


def orr_url(s: requests.Session) -> str:
    try:
        html = s.get(ORR_PAGE, timeout=60).text
        links = re.findall(r'href="(/media/[^"]*table-1410[^"]*\.csv)"', html)
        if links:
            return "https://dataportal.orr.gov.uk" + links[0]
    except requests.RequestException as exc:
        log.warning("ORR page unavailable (%s); using the known table URL", exc)
    return ORR_FALLBACK


def parse_orr(text: str) -> tuple[pd.DataFrame, str]:
    """ORR table 1410 CSV -> (station name, entries+exits) and the period from its title."""
    raw = pd.read_csv(io.StringIO(text), header=None, dtype=str)
    period = re.search(r"annual data,\s*(.+)$", str(raw.iloc[0, 0]))
    header = next(i for i in range(15) if str(raw.iloc[i, 0]).strip() == "Station name")
    df = pd.read_csv(io.StringIO(text), header=header, dtype=str)
    df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]
    col = next(c for c in df.columns if c.lower().startswith("entries and exits") and "all tickets" in c.lower())
    out = pd.DataFrame({"name": df["Station name"], "journeys": pd.to_numeric(df[col].str.replace(",", ""), errors="coerce")})
    return out.dropna(), period.group(1).strip() if period else ""


def parse_naptan(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text), low_memory=False)
    df = df[df["StopType"].eq("RLY") & df["Status"].astype(str).str.lower().eq("active")].copy()
    # Some stations (e.g. new Elizabeth line ones) only have British National Grid coordinates.
    missing = df["Longitude"].isna() & df["Easting"].notna() & df["Northing"].notna()
    if missing.any():
        to_wgs84 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
        lon, lat = to_wgs84.transform(df.loc[missing, "Easting"].astype(float).values, df.loc[missing, "Northing"].astype(float).values)
        df.loc[missing, "Longitude"], df.loc[missing, "Latitude"] = lon, lat
    full = pd.DataFrame({"key": df["CommonName"].map(norm), "lon": df["Longitude"], "lat": df["Latitude"]})
    # Also index each station without its bracketed part ("Witham (Essex)" -> "witham"), unless that is ambiguous.
    short = full.assign(key=df["CommonName"].str.replace(r"\s*\(.*?\)", "", regex=True).map(norm))
    short = short[~short["key"].duplicated(keep=False)]
    return pd.concat([full, short]).dropna().drop_duplicates("key")


def locate(stations: pd.DataFrame, places: pd.DataFrame, geo: dict) -> pd.DataFrame:
    """Stations (name, journeys) matched to locations by name, then to constituency codes by point-in-polygon."""
    st = stations.assign(key=stations["name"].map(norm))
    # Also try the name without a bracketed part, e.g. "Penrith (North Lakes)" -> "Penrith".
    alt = stations["name"].str.replace(r"\s*\(.*?\)", "", regex=True).map(norm)
    loc = places.set_index("key")
    st["key"] = st["key"].where(st["key"].isin(loc.index), alt)
    # Last resort: a unique longer name, e.g. "Lincoln" -> "lincoln central", "Newark Northgate" stays exact.
    keys = list(loc.index)
    def by_prefix(k: str) -> str:
        if k in loc.index:
            return k
        hits = [x for x in keys if x.startswith(k + " ")]
        return hits[0] if len(hits) == 1 else k
    st["key"] = st["key"].map(by_prefix)
    st = st.join(loc, on="key").dropna(subset=["lon", "lat"])
    polys = [shape(f["geometry"]) for f in geo["features"]]
    codes = [f["properties"]["code"] for f in geo["features"]]
    tree = STRtree(polys)
    seat = []
    for lon, lat in zip(st["lon"], st["lat"]):
        p = Point(lon, lat)
        hit = next((codes[i] for i in tree.query(p) if polys[i].covers(p)), None)
        if hit is None:
            # Boundaries are generalised and clipped to the coast, so riverside/coastal stations can fall just
            # outside: take the nearest seat if it's within ~2 km.
            i = tree.nearest(p)
            hit = codes[i] if polys[i].distance(p) < 0.02 else None
        seat.append(hit)
    return st.assign(pcon=seat).dropna(subset=["pcon"])


def seat_frames(located: pd.DataFrame, population: pd.Series, all_codes: list[str]) -> dict[str, pd.DataFrame]:
    g = located.groupby("pcon")
    journeys = g["journeys"].sum()
    gb = [c for c in all_codes if c[:1] in "EWS"]  # National Rail is Great Britain only
    count = g.size().reindex(gb).fillna(0)  # GB seats with no station: 0, not "no data"
    pop = population.reindex(journeys.index.union(population.index))
    return {
        "rail_journeys_per_resident": pd.DataFrame({"num": journeys.reindex(pop.index).fillna(0), "den": pop}),
        "rail_stations": pd.DataFrame({"num": count, "den": 1.0}, index=count.index),
    }


def load_rail(s: requests.Session, geo: dict, population: pd.Series) -> tuple[dict[str, pd.DataFrame], str]:
    r = s.get(orr_url(s), timeout=120)
    r.raise_for_status()
    stations, period = parse_orr(r.content.decode("utf-8", errors="replace"))
    n = s.get(NAPTAN, params={"atcoAreaCodes": "910", "dataFormat": "csv"}, timeout=120)
    n.raise_for_status()
    located = locate(stations, parse_naptan(n.text), geo)
    share = located["journeys"].sum() / stations["journeys"].sum() * 100
    log.info("Rail: %d of %d stations located (%.1f%% of journeys)", len(located), len(stations), share)
    codes = [f["properties"]["code"] for f in geo["features"]]
    return seat_frames(located, population, codes), period
