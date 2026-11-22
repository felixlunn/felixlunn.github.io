"""Fetching the FOI reference geographies: ONS police force and NHS area boundaries, HMCTS courts, NHS trusts
(ODS, located by postcode) and OHID's acute trust catchments."""

from __future__ import annotations

import logging
import re

import pandas as pd
import requests
from shapely.geometry import shape
from shapely.ops import unary_union

from ... import arcgis, govuk
from ...http import get_json
from ...ods import read_ods

log = logging.getLogger(__name__)

COURTS_URL = "https://www.find-court-tribunal.service.gov.uk/search/results.json"
COURTS_PAGE = "https://www.find-court-tribunal.service.gov.uk/"
ODS_URL = "https://directory.spineservices.nhs.uk/ORD/2-0-0/organisations"
ODS_PAGE = "https://digital.nhs.uk/services/organisation-data-service"
POSTCODES = "https://api.postcodes.io/postcodes"
CATCHMENT_PREFIX = "/government/statistics/nhs-acute-hospital-trust-catchment-populations"
CATCHMENT_PAGE = "https://www.gov.uk/government/collections/nhs-acute-hospital-trust-catchment-populations"
MSOA_PATTERN = re.compile(r"^(?:MSOA_2021_EW|Middle_layer_Super_Output_Areas_\(December_2021\)_Boundaries_EW)_(BSC|BGC|BFC|BFE)", re.I)
MSOA_PREFERENCE = {"BSC": 0, "BGC": 1, "BFC": 2, "BFE": 3}  # trust catchments are large: the coarsest layer is plenty
RES_ORDER = {"BUC": 0, "BSC": 1, "BGC": 2}
LAYERS = {
    # kind: (service name pattern with groups (year, resolution), code field pattern, name field pattern)
    "police": (re.compile(r"^Police_Force_Areas_(?:Dec_)?(\d{4})_EW_(BUC|BSC|BGC)$", re.IGNORECASE), r"PFA\d{2}CD", r"PFA\d{2}NM"),
    "icb": (re.compile(r"^Integrated_Care_Boards_April_(\d{4})(?:_Boundaries)?_EN_(BUC|BSC|BGC)$", re.IGNORECASE), r"ICB\d{2}CD", r"ICB\d{2}NM"),
    "lhb": (re.compile(r"^Local_Health_Boards_December_(\d{4})_WA_(BUC|BSC|BGC)$", re.IGNORECASE), r"LHB\d{2}CD", r"LHB\d{2}NM"),
}


def pick_service(names: list[str], pattern: re.Pattern) -> str:
    hits = [(int(m.group(1)), -RES_ORDER[m.group(2).upper()], n) for n in names if (m := pattern.match(n))]
    if not hits:
        raise LookupError(f"No ONS service matches {pattern.pattern}")
    return max(hits)[2]


def load_layer(s: requests.Session, names: list[str], kind: str) -> list[dict]:
    pattern, code_f, name_f = LAYERS[kind]
    layer = arcgis.layer(pick_service(names, pattern))
    out = []
    for f in arcgis.features(s, layer, geojson=True):
        p = f.get("properties") or {}
        code, name = arcgis.field(p, code_f), arcgis.field(p, name_f)
        if code and name and f.get("geometry"):
            out.append({"code": code, "name": name, "geometry": shape(f["geometry"])})
    if not out:
        raise ValueError(f"No {kind} boundaries returned from {layer}")
    log.info("FOI %s areas: %d", kind, len(out))
    return out


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
    res = govuk.search(s, "NHS acute hospital trust catchment populations")
    pages = sorted((r for r in res if str(r.get("link", "")).startswith(CATCHMENT_PREFIX)),
                   key=lambda r: r.get("public_timestamp", ""), reverse=True)
    for r in pages[:3]:
        for a in govuk.attachments(s, r["link"]):
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
    layer = arcgis.first_layer(s, hits[0][1])
    out = {}
    for f in arcgis.features(s, layer, where="MSOA21CD LIKE 'E%'", fields="MSOA21CD", geojson=True, timeout=180):
        code = (f.get("properties") or {}).get("MSOA21CD")
        if code and f.get("geometry"):
            out[code] = shape(f["geometry"]).buffer(0)
    return out


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
