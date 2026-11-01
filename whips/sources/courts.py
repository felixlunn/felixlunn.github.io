"""Crown Court backlog by area (MoJ criminal court statistics), England & Wales.

MoJ publishes Crown Court receipts, disposals and open (outstanding) cases each
quarter by Local Criminal Justice Board (LCJB) area, which follow police force
areas. Each seat gets the figures for its police force area: the area its
neighbourhoods (LSOAs) mostly fall in, via ONS lookups LSOA -> council ->
police force area. Two groupings follow the court data: London's five LCJB
areas are combined (Metropolitan and City of London police), and South Wales
also covers Gwent and Dyfed-Powys (Wales has North and South Wales areas only).

The data sit in the pivot cache of MoJ's "Crown Court receipts, disposals and
open cases tool" spreadsheet, which is read directly.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from collections import Counter
from xml.etree.ElementTree import iterparse

import pandas as pd
import requests

from ..http import get_json
from ..metrics import MetricMeta
from .boundaries import ARCGIS_ROOT
from .lsoa import _services, find_ward_service

log = logging.getLogger(__name__)

COLLECTION = "https://www.gov.uk/api/content/government/collections/criminal-court-statistics"
CONTENT = "https://www.gov.uk/api/content"
SOURCE_URL = "https://www.gov.uk/government/collections/criminal-court-statistics"
TOOL_TITLE = "crown court receipts, disposals and open cases"
PFA_PATTERN = re.compile(r"^LAD(\d{2})_CSP\d{2}_PFA\d{2}_EW_LU", re.I)

COURT_METRICS = [
    MetricMeta("court_open_per_1k", "Crown Court open cases per 1,000 residents", "policing", "per 1,000",
               "Crown Court cases waiting to be dealt with (open at the end of the latest quarter) in the seat's police force area, "
               "per 1,000 residents of that area. Area-wide: every seat in the same area has the same value.",
               "MoJ criminal court statistics", "higher_worse", 2, ("courts",)),
    MetricMeta("court_backlog_change", "Crown Court backlog change over the year", "policing", "%",
               "Change in the number of open Crown Court cases in the seat's police force area over the last year (latest quarter "
               "against the same quarter a year earlier). Positive means the backlog is growing.",
               "MoJ criminal court statistics", "higher_worse", 1, ("courts",)),
]


def area_key(name: str) -> str:
    """Common key for LCJB and police force area names (London and South Wales grouped as in the court data)."""
    n = re.sub(r"\s+lcjb$", "", name.strip().lower().replace("&", "and"))
    n = n.replace(" and isle of wight", "")
    if "london" in n or n.startswith("metropolitan"):
        return "london"
    if n in ("gwent", "dyfed-powys"):
        return "south wales"
    return n


def find_tool(s: requests.Session) -> tuple[str, str]:
    """(xlsx URL, edition title) of the Crown Court receipts/disposals/open cases tool in the latest quarterly release."""
    docs = get_json(s, COLLECTION).get("links", {}).get("documents", [])
    quarterly = sorted((d for d in docs if "criminal-court-statistics-quarterly" in d.get("base_path", "")),
                       key=lambda d: d.get("public_updated_at", ""), reverse=True)
    for d in quarterly[:3]:
        for a in get_json(s, CONTENT + d["base_path"]).get("details", {}).get("attachments", []):
            if TOOL_TITLE in str(a.get("title", "")).lower() and str(a.get("url", "")).endswith(".xlsx"):
                return a["url"], d.get("title", "")
    raise LookupError("No Crown Court receipts/disposals/open cases tool found")


def read_pivot_cache(xlsx: bytes) -> pd.DataFrame:
    """The records behind the first pivot table in an Excel file, as a DataFrame."""
    z = zipfile.ZipFile(io.BytesIO(xlsx))
    defn = z.read("xl/pivotCache/pivotCacheDefinition1.xml").decode("utf-8")
    fields = []
    for m in re.finditer(r'<cacheField name="([^"]+)"[^>]*?(?:/>|>(.*?)</cacheField>)', defn, re.S):
        items = re.findall(r'<(s|n|d|b|e)\s+v="([^"]*)"', m.group(2) or "")
        fields.append((m.group(1), [float(v) if t == "n" else v for t, v in items]))
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rows = []
    for _, el in iterparse(z.open("xl/pivotCache/pivotCacheRecords1.xml")):
        if el.tag == ns + "r":
            rec = []
            for i, c in enumerate(el):
                tag, v = c.tag[len(ns):], c.get("v")
                rec.append(fields[i][1][int(v)] if tag == "x" else float(v) if tag == "n" else None if tag == "m" else v)
            rows.append(rec)
            el.clear()
    return pd.DataFrame(rows, columns=[f[0] for f in fields])


def open_by_area(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Open cases (all offences) per area key in the latest quarter and a year earlier; and the latest quarter label."""
    d = df[df["rdos"].astype(str).str.contains("Open") & df["offence_group"].astype(str).str.startswith("00")].copy()
    d["yq"] = d["year"].astype(int).astype(str) + " " + d["quarter"].astype(str)
    latest = d["yq"].max()
    year, q = latest.split()
    prior = f"{int(year) - 1} {q}"
    d = d[d["lcjb_area"].astype(str).str.contains("LCJB")]
    d["area"] = d["lcjb_area"].map(area_key)
    out = d[d["yq"].isin([latest, prior])].pivot_table(index="area", columns="yq", values="value", aggfunc="sum")
    return pd.DataFrame({"open": out.get(latest), "open_prior": out.get(prior)}), latest


def seat_areas(s: requests.Session, lsoa_to_pcon: dict[str, str]) -> dict[str, str]:
    """Seat code -> police force area key: the area most of its LSOAs fall in (LSOA -> council -> police force area)."""
    names = _services(s)
    ward = find_ward_service(names)
    pfa_svc = sorted(((int(PFA_PATTERN.match(n).group(1)), n) for n in names if PFA_PATTERN.match(n)), reverse=True)
    if not pfa_svc:
        raise LookupError("No council to police force area lookup found on the ONS portal")
    pfa_layer = f"{ARCGIS_ROOT}/{pfa_svc[0][1]}/FeatureServer/0"

    def all_rows(layer: str) -> list[dict]:
        rows, offset = [], 0
        while True:
            data = get_json(s, f"{layer}/query", params={"where": "1=1", "outFields": "*", "returnGeometry": "false",
                                                        "f": "json", "resultOffset": offset, "resultRecordCount": 2000})
            batch = [f["attributes"] for f in data.get("features", [])]
            rows += batch
            if not batch or not data.get("exceededTransferLimit"):
                return rows
            offset += len(batch)

    def col(row: dict, pattern: str):
        return next((v for k, v in row.items() if re.fullmatch(pattern, k, re.I)), None)

    lad_pfa = {col(r, r"LAD\d{2}CD"): area_key(col(r, r"PFA\d{2}NM") or "") for r in all_rows(pfa_layer)}
    lsoa_lad = {r["LSOA21CD"]: col(r, r"LAD\d{2}CD") for r in all_rows(ward) if r.get("LSOA21CD")}
    votes: dict[str, Counter] = {}
    for lsoa, pcon in lsoa_to_pcon.items():
        area = lad_pfa.get(lsoa_lad.get(lsoa))
        if area:
            votes.setdefault(pcon, Counter())[area] += 1
    return {pcon: c.most_common(1)[0][0] for pcon, c in votes.items()}


def seat_frames(areas: pd.DataFrame, seat_area: dict[str, str], population: pd.Series) -> dict[str, pd.DataFrame]:
    """Area figures given to each seat; per-1,000 rates use the area's total population."""
    sa = pd.Series(seat_area)
    pop = population.reindex(sa.index)
    area_pop = pop.groupby(sa).sum()
    a = areas.reindex(sa.values)
    a.index = sa.index
    per_1k = a["open"] * 1000 / area_pop.reindex(sa.values).values
    change = (a["open"] - a["open_prior"]) * 100 / a["open_prior"]
    # Area-wide values: num/den chosen so the national figure is the true England & Wales rate.
    share = pop / area_pop.reindex(sa.values).values  # this seat's share of its area's people
    return {
        "court_open_per_1k": pd.DataFrame({"num": per_1k * pop, "den": pop}),
        "court_backlog_change": pd.DataFrame({"num": change * a["open_prior"] * share, "den": a["open_prior"] * share}),
    }


def load_courts(s: requests.Session, lsoa_to_pcon: dict[str, str], population: pd.Series) -> tuple[dict[str, pd.DataFrame], str]:
    url, _ = find_tool(s)
    r = s.get(url, timeout=300)
    r.raise_for_status()
    areas, quarter = open_by_area(read_pivot_cache(r.content))
    seat_area = seat_areas(s, lsoa_to_pcon)
    unmatched = sorted(set(seat_area.values()) - set(areas.index))
    if unmatched:
        log.warning("Court data has no area for: %s", unmatched)
    log.info("Courts: %d areas, %d seats, latest %s", len(areas), len(seat_area), quarter)
    return seat_frames(areas, seat_area, population), f"Open cases at end of {quarter}"
