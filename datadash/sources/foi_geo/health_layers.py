"""The FOI Health tab's trust layers beyond acute catchments and ICBs: mental health trusts and ambulance trusts.

Which trust goes on which layer comes from the team's list (trust_groups.json), matched to current trusts in NHS ODS.
Neither kind of trust has published boundaries, so their areas are built from councils (ONS local authority districts):

* Ambulance trusts follow regions and counties: each English region has one service, except that the South East is
  split by county (South East Coast; South Central; the Isle of Wight's own service) and North and North East
  Lincolnshire are served from the East Midlands. Wales, Scotland and Northern Ireland each have one national service.
* Mental health trusts: each English council goes to the mental health trust running the most sites there (every site
  ODS lists for the trust, by postcode); councils with no such site join the neighbouring trust they border most.
  These areas are approximate.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from difflib import get_close_matches
from pathlib import Path

import requests
from shapely.ops import unary_union

from ...http import get_json

log = logging.getLogger(__name__)

GROUPS = json.loads(Path(__file__).with_name("trust_groups.json").read_text())
ODS_URL = "https://directory.spineservices.nhs.uk/ORD/2-0-0/organisations"
POSTCODES = "https://api.postcodes.io/postcodes"

# --- Which trust is on which layer -------------------------------------------------------------------------------

def norm(name: str) -> str:
    n = name.lower().replace("&", " and ")
    n = re.sub(r"\(.*?\)", " ", n)
    n = re.sub(r"\b(the|nhs|foundation|trust|ft|university|teaching|hospitals?|of|services?)\b", " ", n)
    return re.sub(r"[^a-z]", "", n)


def resolve_groups(trusts: list[dict], lists: dict = GROUPS) -> tuple[dict[str, set[str]], list[tuple[str, str]]]:
    """({trust code: the layers the list puts it on}, [(layer, name) the list names but no current trust matches])."""
    index: dict[str, str] = {}
    for t in trusts:
        for n in [t["name"], *[a for a in t.get("aliases", []) if not re.fullmatch(r"[A-Z0-9]{3,5}", a)]]:
            index.setdefault(norm(n), t["code"])
    codes = {t["code"] for t in trusts}
    groups: dict[str, set[str]] = {}
    missing = []
    for layer in ("hospital", "mental_health", "ambulance"):
        for name in lists.get(layer, []):
            code = lists.get("renamed", {}).get(name) or index.get(norm(name))
            if not code:
                close = get_close_matches(norm(name), list(index), n=1, cutoff=0.9)
                code = index[close[0]] if close else None
            if code in codes:
                groups.setdefault(code, set()).add(layer)
            else:
                missing.append((layer, name))
    return groups, missing


def trust_groups(trusts: list[dict], kinds: dict[str, str], lists: dict = GROUPS) -> dict[str, list[str]]:
    """Each trust's layers: as the list says; a trust on no list is an ambulance trust if it is one, otherwise on the
    Trusts layer. Only the list puts trusts on the mental health layer: guessing from names would add acute and
    community trusts that don't call themselves hospitals (e.g. Homerton Healthcare)."""
    listed, missing = resolve_groups(trusts, lists)
    if missing:
        log.warning("FOI trust lists: %d names match no current trust: %s", len(missing), missing[:10])
    out = {}
    for t in trusts:
        g = listed.get(t["code"])
        if not g:
            k = kinds.get(t["code"], "")
            g = {"ambulance"} if k == "Ambulance" else {"hospital"}
        out[t["code"]] = sorted(g)
    return out

# --- Mental health trust areas -----------------------------------------------------------------------------------

def site_postcodes(s: requests.Session, code: str) -> list[str]:
    """Postcodes of every active site ODS lists for a trust."""
    sites: dict[str, str] = {}
    offset = 0
    while True:
        params = {"RelTypeId": "RE6", "TargetOrgId": code, "RelStatus": "active", "Limit": 1000}
        if offset:  # ODS refuses Offset=0: the first page has none
            params["Offset"] = offset + 1
        orgs = get_json(s, ODS_URL, params=params).get("Organisations", [])
        sites.update({o["OrgId"]: o["PostCode"].strip().upper() for o in orgs if o.get("OrgId") and o.get("PostCode")})
        if len(orgs) < 1000:
            return list(sites.values())
        offset += 1000


def postcode_districts(s: requests.Session, postcodes: list[str]) -> dict[str, str]:
    """Postcode -> council (local authority district) code, from postcodes.io."""
    out = {}
    pcs = sorted(set(postcodes))
    for i in range(0, len(pcs), 100):
        r = s.post(POSTCODES, json={"postcodes": pcs[i:i + 100]}, timeout=60)
        r.raise_for_status()
        for item in r.json().get("result", []):
            lad = ((item.get("result") or {}).get("codes") or {}).get("admin_district")
            if lad:
                out[item["query"].strip().upper()] = lad
    return out


def mh_site_counts(s: requests.Session, codes: list[str]) -> dict[str, Counter]:
    """{trust code: Counter(council code -> sites)} for the mental health trusts."""
    with ThreadPoolExecutor(max_workers=6) as ex:
        sites = dict(zip(codes, ex.map(lambda c: site_postcodes(s, c), codes)))
    lad_of = postcode_districts(s, [p for pcs in sites.values() for p in pcs])
    return {c: Counter(lad_of[p] for p in pcs if p in lad_of) for c, pcs in sites.items()}


def mh_owners(lads: list[dict], counts: dict[str, Counter], fixed: dict[str, str] | None = None) -> dict[str, str]:
    """English council code -> mental health trust: most sites there; councils with none join the trust whose
    councils they border most (repeatedly, so a cluster of empty councils fills in from its edges). ``fixed``
    (trust_groups.json "mental_health_councils") sets councils the rule gets wrong."""
    fixed = {k: v for k, v in (GROUPS.get("mental_health_councils", {}) if fixed is None else fixed).items() if not k.startswith("_")}
    england = {a["code"]: a for a in lads if a["code"].startswith("E")}
    owner = {lad: trust for lad, trust in fixed.items() if lad in england and trust in counts}
    for lad in england:
        tally = Counter({c: n[lad] for c, n in counts.items() if n.get(lad)})
        if tally and lad not in owner:
            owner[lad] = max(tally.items(), key=lambda kv: (kv[1], kv[0]))[0]
    for _ in range(10):
        todo = [c for c in england if c not in owner]
        if not todo:
            break
        for lad in todo:
            g = england[lad]["geometry"].buffer(0.001)
            border = Counter()
            for other, trust in owner.items():
                og = england[other]["geometry"]
                if g.intersects(og):
                    border[trust] += g.intersection(og).length
            if border:
                owner[lad] = border.most_common(1)[0][0]
    return owner

# --- Ambulance trust areas ---------------------------------------------------------------------------------------

AMBULANCE_BY_REGION = {
    "E12000001": "north east", "E12000002": "north west", "E12000003": "yorkshire", "E12000004": "east midlands",
    "E12000005": "west midlands", "E12000006": "east of england", "E12000007": "london", "E12000009": "south western",
}
SECAMB_COUNTIES = {"E10000016", "E10000030", "E10000011", "E10000032"}  # Kent, Surrey, East Sussex, West Sussex
SECAMB_UNITARIES = {"E06000035", "E06000043"}  # Medway, Brighton and Hove
ISLE_OF_WIGHT = "E06000046"
TO_EAST_MIDLANDS = {"E06000012", "E06000013"}  # North East and North Lincolnshire
NATIONAL = {"W": ("W-AMB", "Welsh Ambulance Services University NHS Trust"), "S": ("S-AMB", "Scottish Ambulance Service"),
            "N": ("N-AMB", "Northern Ireland Ambulance Service")}


def ambulance_key(lad: str, region: str | None, county: str | None) -> str | None:
    """Which ambulance service covers a council, as a word in its name ("south central", "isle of wight"...)."""
    if lad[:1] in NATIONAL:
        return lad[:1]
    if lad == ISLE_OF_WIGHT:
        return "isle of wight"
    if lad in TO_EAST_MIDLANDS:
        return "east midlands"
    if region == "E12000008":  # South East
        return "south east coast" if (county in SECAMB_COUNTIES or lad in SECAMB_UNITARIES) else "south central"
    return AMBULANCE_BY_REGION.get(region or "")


def ambulance_owners(lads: list[dict], regions: list[dict], county: dict[str, str], trusts: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    """({council code: ambulance trust code}, {code: name}) incl. the national services of Wales, Scotland and NI."""
    names = {}
    by_key = {}
    for t in trusts:
        n = t["name"].lower()
        if "ambulance" in n:
            for k in ("north east", "north west", "yorkshire", "east midlands", "west midlands", "east of england", "london",
                      "south western", "south east coast", "south central"):
                if k in n:
                    by_key[k] = t["code"]
                    names[t["code"]] = t["name"]
        if n.startswith("isle of wight"):  # not "Hampshire and Isle of Wight Healthcare" (mental health)
            by_key["isle of wight"] = t["code"]
            names[t["code"]] = t["name"]
    for k, (code, name) in NATIONAL.items():
        by_key[k] = code
        names[code] = name
    owner = {}
    for a in lads:
        region = None
        if a["code"].startswith("E"):
            p = a["geometry"].representative_point()
            region = next((r["code"] for r in regions if r["geometry"].contains(p)), None)
        key = ambulance_key(a["code"], region, county.get(a["code"]))
        if key in by_key:
            owner[a["code"]] = by_key[key]
    return owner, names

# --- Shared --------------------------------------------------------------------------------------------------------

def areas_from_councils(owner: dict[str, str], lads: list[dict], names: dict[str, str]) -> list[dict]:
    """One area per trust: the union of its councils."""
    by_trust: dict[str, list] = {}
    shapes = {a["code"]: a["geometry"] for a in lads}
    for lad, trust in owner.items():
        if lad in shapes:
            by_trust.setdefault(trust, []).append(shapes[lad])
    return [{"code": t, "name": names.get(t, t), "geometry": unary_union(parts).buffer(0)} for t, parts in sorted(by_trust.items())]
