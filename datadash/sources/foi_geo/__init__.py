"""Reference geographies for the FOI research section: the bodies FOI requests go to, and the seats they cover.

The FOI section maps uploaded FOI responses by the body that answered them. This writes the public reference
data it matches uploads against (the uploads themselves live in the private FOI database, never here):

- Police force areas (ONS boundaries, England & Wales; Police Scotland and PSNI drawn from their nations' seats).
- Courts and tribunals (HMCTS Find a court or tribunal), as points.
- NHS trusts (NHS Organisation Data Service), as points located from their head office postcode.
- NHS areas: integrated care boards (England) and local health boards (Wales), ONS boundaries.

Each area lists the seats it overlaps (share of the seat's area inside it), and each point the seat it sits in,
so a seat's office can see which force, trusts and courts serve it.

Modules: ``loaders`` fetches each layer, ``assemble`` builds the published files from them (shared with the demo),
``demo`` makes synthetic data for the demo build.
"""

from __future__ import annotations

import logging
import re

import requests

from ... import arcgis
from ..councils import lad_to_county
from . import health_layers as hl
from .assemble import (
    area_of_points, area_population, assemble, ld_status, nation_area, police_aliases, seat_overlaps, to_feature, write_foi,
)
from .demo import demo_reference
from .loaders import (
    LAYERS, MSOA_PATTERN, catchment_areas, closed, current_trusts, find_catchment_file, load_catchments, load_courts, load_layer, load_trusts,
    parse_fptp, pick_service, title_name, trust_kind,
)

log = logging.getLogger(__name__)

SOURCE_URL = "https://geoportal.statistics.gov.uk/"


def load_foi_reference(s: requests.Session, geo: dict, seats: list[dict], population: dict[str, float], as_of: str) -> tuple[dict, dict, list[str]]:
    """Fetch every layer. Courts and trusts are each optional: a failure leaves them out and is reported."""
    names = arcgis.services(s, *(p for p, _, _ in LAYERS.values()))
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
    mental_health = ambulance = None
    if trusts is not None:
        try:
            mental_health, ambulance = load_health_layers(s, names, trusts)
        except Exception as exc:  # noqa: BLE001
            log.exception("Mental health / ambulance trust areas failed")
            problems.append(f"mental health and ambulance trust areas: {exc}"[:200])
    catchments = None
    try:
        catchments, _ = load_catchments(s, arcgis.services(s, MSOA_PATTERN))
    except Exception as exc:  # noqa: BLE001
        log.exception("Trust catchments failed")
        problems.append(f"trust catchments: {exc}"[:200])
    ref, areas = assemble(geo, seats, population, police, health, courts, trusts, as_of, catchments, mental_health, ambulance)
    return ref, areas, problems


def load_health_layers(s: requests.Session, names: list[str], trusts: list[dict]) -> tuple[list[dict], list[dict]]:
    """(mental health trust areas, ambulance trust areas), and each trust's layers (``groups``) set on it."""
    lads, regions = load_layer(s, names, "lad"), load_layer(s, names, "region")
    groups = hl.trust_groups(trusts, {t["code"]: t.get("kind", "") for t in trusts})
    for t in trusts:
        t["groups"] = groups[t["code"]]
    mh = {t["code"]: t for t in trusts if "mental_health" in t["groups"]}
    owners = hl.mh_owners(lads, hl.mh_site_counts(s, sorted(mh)))
    mental_health = hl.areas_from_councils(owners, lads, {c: t["name"] for c, t in mh.items()})
    for a in mental_health:  # former names still match uploads
        a["aliases"] = [x for x in mh[a["code"]].get("aliases", []) if not re.fullmatch(r"[A-Z0-9]{3,5}", x)]
    amb_owner, amb_names = hl.ambulance_owners(lads, regions, lad_to_county(s), trusts)
    ambulance = hl.areas_from_councils(amb_owner, lads, amb_names)
    log.info("FOI mental health trust areas: %d; ambulance: %d", len(mental_health), len(ambulance))
    return mental_health, ambulance


__all__ = [
    "SOURCE_URL", "LAYERS", "load_foi_reference", "write_foi", "demo_reference", "assemble", "area_of_points",
    "area_population", "ld_status", "nation_area", "police_aliases", "seat_overlaps", "to_feature", "catchment_areas",
    "find_catchment_file", "load_catchments", "load_courts", "load_layer", "load_trusts", "parse_fptp", "pick_service",
    "title_name", "trust_kind", "MSOA_PATTERN", "closed", "current_trusts",
]
