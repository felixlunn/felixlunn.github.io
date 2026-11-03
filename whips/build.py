"""Data pipeline: fetch every source, compute metrics, write the dashboard's static data files.

    python -m whips.build --out frontend/public/data

Outputs
    data.json           metrics catalogue, seats, columnar values, peer groups, source status
    boundaries.geojson  simplified July 2024 Westminster constituency boundaries
    constituencies.csv  wide table of every metric, for download / spreadsheets

Boundaries and Census 2021 are required (the build fails without them). The
other sources are optional: if one fails, the build continues and records the
failure in ``data.json`` so the dashboard can say what is missing.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import engine
from .http import session
from .metrics import (
    CENSUS_METRICS, CLAIMANT_METRICS, ELECTION_METRICS, POLICE_METRICS, THEMES, MetricMeta, census_meta,
)
from .sources import boundaries as bsrc
from .sources import courts as courts_src
from .sources import debates as debates_src
from .sources import epc as epc_src
from .sources import ev as ev_src
from .sources import councils as councils_src
from .sources import fuel_poverty as fuel_src
from .sources import housing as housing_src
from .sources import nhs as nhs_src
from .sources import nhsbsa as nhsbsa_src
from .sources import petitions as petitions_src
from .sources import questions as questions_src
from .sources import rail as rail_src
from .sources import schools as schools_src
from .sources import sewage as sewage_src
from .sources import imd as imd_src
from .sources import life_expectancy as life_src
from .sources import pupils as pupils_src
from .sources import pharmacies as pharmacies_src
from .sources import public_health as public_health_src
from .sources import income as income_src
from .sources import asylum as asylum_src
from .sources import road_condition as road_condition_src
from .sources import rents as rents_src
from .sources import energy as energy_src
from .sources import travel as travel_src
from .sources import air_energy as air_src
from .sources import children as children_src
from .sources import vehicles as vehicles_src
from .sources import buses as buses_src
from .sources import cqc as cqc_src
from .sources import roads as roads_src
from .sources import housing_stock as housing_stock_src
from .sources import child_poverty as child_poverty_src
from .sources import lsoa as lsoa_src
from .sources import nomis, nomis_extra, parliament, police

log = logging.getLogger("whips.build")

# Neighbourhood (LSOA) profiles are published for seats held by this party.
NEIGHBOURHOOD_PARTY = re.compile(r"^(liberal democrats?|lib ?dems?|ld)$", re.I)

SKIPPABLE = ["pupils", "pharmacies", "public_health", "income", "asylum", "road_condition", "rents", "energy", "travel", "renewables", "air_pollution", "children", "vehicles", "buses", "cqc", "roads", "housing_stock", "child_poverty", "dental", "life_expectancy", "affordability", "homelessness", "ev", "sewage", "petitions", "questions", "rail", "courts", "fuel_poverty", "nhs", "schools", "epc", "imd", "neighbourhoods", "debates", "claimants", "aps", "ashe", "bres", "business", "popest", "police", "elections", "members", "lsoa"]

COUNTRY_BY_PREFIX = {"E": "England", "W": "Wales", "S": "Scotland", "N": "Northern Ireland"}


def _clean(v: float, decimals: int = 3):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    return round(float(v), decimals)


def assemble(codes: list[str], frames: dict[str, pd.DataFrame], metas: list[MetricMeta]) -> tuple[list[dict], dict[str, list]]:
    """Align num/den frames to ``codes`` and compute values + national figures."""
    metrics, values = [], {}
    for meta in metas:
        f = frames.get(meta.id)
        if f is None:
            continue
        official = f.attrs.get("national")  # e.g. a UK median, which can't be built from seat medians
        f = f.reindex(codes)
        num, den = f["num"].astype(float), f["den"].astype(float)
        val = (num / den).replace([np.inf, -np.inf], np.nan)
        ok = val.notna()
        if not ok.any():
            continue
        national = official if official is not None else float(num[ok].sum() / den[ok].sum()) if den[ok].sum() else None
        metrics.append({
            "id": meta.id, "label": meta.label, "theme": meta.theme, "unit": meta.unit,
            "description": meta.description, "source": meta.source, "polarity": meta.polarity,
            "decimals": meta.decimals, "tags": list(meta.tags),
            "national": _clean(national), "coverage": int(ok.sum()),
        })
        values[meta.id] = [_clean(v) for v in val.tolist()]
    return metrics, values


def build(out_dir: Path, skip: set[str] | None = None) -> dict:
    skip = skip or set()
    out_dir.mkdir(parents=True, exist_ok=True)
    s = session()
    sources: list[dict] = []
    frames: dict[str, pd.DataFrame] = {}
    metas: list[MetricMeta] = []

    def record(sid, name, url, status, detail="", as_of=None):
        sources.append({"id": sid, "name": name, "url": url, "status": status, "detail": detail, "as_of": as_of})

    def optional(sid: str, name: str, url: str, detail: str, load, meta_list: list[MetricMeta]) -> None:
        """Run an optional source: ``load()`` returns (frames, period). A failure is recorded, not raised."""
        try:
            got, period = load()
            frames.update(got)
            metas.extend(m for m in meta_list if m.id in got)
            record(sid, name, url, "ok", detail, period)
        except Exception as exc:  # noqa: BLE001 - optional source
            log.exception("%s failed", name)
            record(sid, name, url, "failed", str(exc)[:300])

    # 1. Boundaries (required)
    t0 = time.time()
    geo = bsrc.load_boundaries(s)
    codes = [f["properties"]["code"] for f in geo["features"]]
    names = {f["properties"]["code"]: f["properties"]["name"] for f in geo["features"]}
    record("boundaries", "ONS Open Geography: Westminster constituencies (July 2024)",
           "https://geoportal.statistics.gov.uk/", "ok", f"{len(codes)} constituencies", "July 2024")
    log.info("Boundaries: %d features (%.0fs)", len(codes), time.time() - t0)

    # 2. Census 2021 (required)
    t0 = time.time()
    lookup_cache: dict = {}

    def lsoa_lookup():
        if "v" not in lookup_cache:
            lookup_cache["v"] = bsrc.load_lsoa_pcon_lookup(s)
            log.info("LSOA -> constituency lookup: %d LSOAs", len(lookup_cache["v"]))
        return lookup_cache["v"]

    want_lsoa = "lsoa" not in skip and "neighbourhoods" not in skip
    lsoa_frames: dict[str, pd.DataFrame] | None = {} if want_lsoa else None
    census, _census_names, prov = nomis.load_census(s, CENSUS_METRICS, None if "lsoa" in skip else lsoa_lookup, lsoa_frames)
    frames.update(census)
    metas += [census_meta(m) for m in CENSUS_METRICS]
    record("census", "Census 2021 (ONS via Nomis)", "https://www.nomisweb.co.uk/sources/census_2021",
           "ok", f"{len(prov['tables'])} tables; England & Wales only"
           + (f"; {len(prov['aggregated_from_lsoa'])} summed from LSOAs (ONS best-fit)" if prov.get("aggregated_from_lsoa") else "")
           + (f"; unavailable: {', '.join(sorted(prov['failed']))}" if prov["failed"] else ""), "March 2021")
    log.info("Census: %d metrics (%.0fs)", len(census), time.time() - t0)
    population = census["population"]["num"]

    # 3. Optional sources
    imd_deciles = None
    if "imd" not in skip:
        try:
            imd = imd_src.load_imd(s)
            frames.update(imd_src.seat_frames(imd, lsoa_lookup()))
            metas += imd_src.IMD_METRICS
            if lsoa_frames is not None:
                lsoa_frames.update(imd_src.lsoa_frames(imd))
                imd_deciles = imd["decile"]
            record("imd", "English Indices of Deprivation 2025 (MHCLG)", imd_src.PAGE_URL, "ok",
                   f"{len(imd)} LSOAs; England only; best-fit to constituencies, population-weighted", "2025")
        except Exception as exc:  # noqa: BLE001
            log.exception("IMD failed")
            record("imd", "English Indices of Deprivation 2025 (MHCLG)", imd_src.PAGE_URL, "failed", str(exc))

    if "fuel_poverty" not in skip:
        def fuel():
            seat_f, lsoa_f, year = fuel_src.load_fuel_poverty(s)
            if lsoa_frames is not None:
                lsoa_frames.update(lsoa_f)  # also shown per neighbourhood
            return seat_f, year
        optional("fuel_poverty", "Sub-regional fuel poverty (DESNZ)", fuel_src.SOURCE_URL,
                 "Low Income Low Energy Efficiency measure; England", fuel, fuel_src.FUEL_POVERTY_METRICS)

    if "sewage" not in skip:
        optional("sewage", "Storm overflow spills (Environment Agency EDM annual return)", sewage_src.SOURCE_URL,
                 "Overflows placed in seats by outlet location; England & Wales", lambda: sewage_src.load_sewage(s, geo),
                 sewage_src.SEWAGE_METRICS)

    if "rail" not in skip:
        optional("rail", "Estimates of station usage (ORR)", rail_src.ORR_PAGE,
                 "Stations located with DfT NaPTAN; Great Britain", lambda: rail_src.load_rail(s, geo, population), rail_src.RAIL_METRICS)

    if "courts" not in skip:
        optional("courts", "Criminal court statistics: Crown Court (MoJ)", courts_src.SOURCE_URL,
                 "By police force area (London combined; South Wales includes Gwent and Dyfed-Powys); England & Wales",
                 lambda: courts_src.load_courts(s, lsoa_lookup(), population), courts_src.COURT_METRICS)

    if "claimants" not in skip:
        try:
            cf, period = nomis.load_claimants(s)
            frames["claimant_rate"] = cf
            metas += CLAIMANT_METRICS
            record("claimants", "ONS Claimant Count (Nomis)", "https://www.nomisweb.co.uk/sources/cc", "ok", "", period)
        except Exception as exc:  # noqa: BLE001 - optional source
            log.exception("Claimant count failed")
            record("claimants", "ONS Claimant Count (Nomis)", "https://www.nomisweb.co.uk/sources/cc", "failed", str(exc))

    extra_frames, extra_metas = nomis_extra.load_all(s, skip, record)
    frames.update(extra_frames)
    metas += extra_metas

    if "schools" not in skip:
        optional("gias", "Schools register (DfE Get Information about Schools)", schools_src.GIAS_PAGE,
                 "Open schools in England, by July 2024 constituency", lambda: schools_src.load_gias(s), schools_src.SCHOOL_METRICS)
        optional("ks4", "GCSE results by constituency (DfE Key stage 4 performance)", schools_src.KS4_PAGE,
                 "Pupils' constituency of residence; England", lambda: schools_src.load_ks4(s), schools_src.KS4_METRICS)

    if "nhs" not in skip:
        optional("nhs", "NHS GP practice data: QOF disease registers and GP Patient Survey (OHID Fingertips)", nhs_src.SOURCE_URL,
                 "Practices placed in their constituency by postcode; England", lambda: nhs_src.load_nhs(s), nhs_src.NHS_METRICS)

    if "epc" not in skip:
        try:
            ef, period = epc_src.load_epc(s, names)
            frames.update(ef)
            metas += epc_src.EPC_METRICS
            record("epc", "Energy Performance Certificates (MHCLG)", epc_src.SOURCE_URL, "ok",
                   "Domestic certificates lodged in the last 10 years; England & Wales", period)
        except Exception as exc:  # noqa: BLE001
            log.exception("EPC failed")
            record("epc", "Energy Performance Certificates (MHCLG)", epc_src.SOURCE_URL, "failed", str(exc))

    if "police" not in skip:
        try:
            t0 = time.time()
            pf, months = police.load_police(s, geo, population)
            frames.update(pf)
            metas += POLICE_METRICS
            record("police", "police.uk street-level crime", "https://data.police.uk/", "ok",
                   f"{len(months)} months; England, Wales & Northern Ireland; annualised",
                   f"{min(months)} to {max(months)}")
            log.info("Police: done (%.0fs)", time.time() - t0)
        except Exception as exc:  # noqa: BLE001
            log.exception("police.uk failed")
            record("police", "police.uk street-level crime", "https://data.police.uk/", "failed", str(exc))

    attrs = pd.DataFrame(index=codes)
    if "elections" not in skip:
        try:
            try:
                ef, eattrs = parliament.load_results(s)
                source = ("2024 general election results (House of Commons Library)",
                          "https://commonslibrary.parliament.uk/research-briefings/cbp-10009/")
            except Exception as exc:  # noqa: BLE001 - the Library file can refuse automated downloads
                log.warning("Commons Library results unavailable (%s); using the Members API", exc)
                ef, eattrs = parliament.load_results_api(s, names)
                source = ("2024 general election results (UK Parliament Members API)", "https://members-api.parliament.uk/")
            frames.update(ef)
            metas += ELECTION_METRICS
            attrs = attrs.join(eattrs, how="left")
            record("elections", *source, "ok", f"{len(eattrs)} constituencies", "4 July 2024")
        except Exception as exc:  # noqa: BLE001
            log.exception("Election results failed")
            record("elections", "2024 general election results", "https://members-api.parliament.uk/", "failed", str(exc))

    members: dict[str, dict] = {}
    if "members" not in skip:
        try:
            members = parliament.match_members(parliament.load_members(s), names)
            record("members", "Current MPs (UK Parliament Members API)", "https://members-api.parliament.uk/", "ok",
                   f"{len(members)} seats matched", datetime.now(timezone.utc).date().isoformat())
        except Exception as exc:  # noqa: BLE001
            log.exception("Members API failed")
            record("members", "Current MPs (UK Parliament Members API)", "https://members-api.parliament.uk/", "failed", str(exc))

    if members and "questions" not in skip:
        optional("questions", "Written questions (UK Parliament)", questions_src.SOURCE_URL, "Tabled by each current MP",
                 lambda: questions_src.load_questions(s, members), questions_src.QUESTION_METRICS)

    council_cache: dict = {}

    def council_weights():
        """Seat x council overlaps (fetched once, shared by council-level sources)."""
        if "w" not in council_cache:
            council_cache["w"] = councils_src.seat_council_weights(lsoa_lookup(), councils_src.lsoa_to_lad(s))
        return council_cache["w"]

    if "dental" not in skip:
        optional("dental", "NHS dental activity (NHSBSA)", nhsbsa_src.SOURCE_URL,
                 "Patients seen by dental practices in each seat; England",
                 lambda: nhsbsa_src.load_dental(s, lsoa_lookup(), population), nhsbsa_src.DENTAL_METRICS)
    if "life_expectancy" not in skip:
        optional("life_expectancy", "Life expectancy at birth (OHID Fingertips)", life_src.SOURCE_URL,
                 "By council, averaged over the councils each seat covers; England",
                 lambda: life_src.load_life_expectancy(s, council_weights()), life_src.LIFE_METRICS)
    if "affordability" not in skip:
        optional("affordability", "Housing affordability (ONS)", housing_src.ONS_PAGE,
                 "By council, averaged over the councils each seat covers; England & Wales",
                 lambda: housing_src.load_affordability(s, council_weights()), housing_src.AFFORDABILITY_METRICS)
    if "homelessness" not in skip:
        optional("homelessness", "Statutory homelessness (MHCLG)", housing_src.HOMELESS_PAGE,
                 "By council, shared out across the seats each council covers; England",
                 lambda: housing_src.load_homelessness(s, council_weights()), housing_src.HOMELESS_METRICS)

    if "ev" not in skip:
        optional("ev", "EV charging infrastructure statistics (DfT, from Zapmap)", ev_src.SOURCE_URL, "Public chargers by constituency; UK",
                 lambda: ev_src.load_ev(s, (frames["turnout"]["den"] if "turnout" in frames else population).dropna()),
                 ev_src.EV_METRICS)

    if "child_poverty" not in skip:
        optional("child_poverty", "Children in low income families (DWP)", child_poverty_src.SOURCE_URL,
                 "By constituency; UK",
                 lambda: child_poverty_src.load_child_poverty(s), child_poverty_src.CHILD_POVERTY_METRICS)

    if "housing_stock" not in skip:
        optional("housing_stock", "Council Taxbase and net additional dwellings (MHCLG)", housing_stock_src.SOURCE_URL,
                 "By council, shared out across the seats each council covers; England",
                 lambda: housing_stock_src.load_housing_stock(s, council_weights()), housing_stock_src.HOUSING_STOCK_METRICS)

    if "roads" not in skip:
        optional("roads", "Road safety data: STATS19 collisions (DfT)", roads_src.SOURCE_URL,
                 "Injury collisions placed by neighbourhood or location, last five years; Great Britain",
                 lambda: roads_src.load_roads(s, geo, lsoa_lookup(), (frames["turnout"]["den"] if "turnout" in frames else population).dropna()), roads_src.ROAD_METRICS)

    if "cqc" not in skip:
        optional("cqc", "Care Quality Commission ratings (CQC)", cqc_src.SOURCE_URL,
                 "Active registered services placed by location; England",
                 lambda: cqc_src.load_cqc(s, geo, census["age_65_plus"]["num"] if "age_65_plus" in census else None), cqc_src.CQC_METRICS)

    if "buses" not in skip:
        optional("buses", "Bus statistics (DfT)", buses_src.SOURCE_URL,
                 "By local transport authority, averaged over the authorities each seat covers; England",
                 lambda: buses_src.load_buses(s, council_weights()), buses_src.BUS_METRICS)

    if "vehicles" not in skip:
        optional("vehicles", "Vehicle licensing statistics (DfT)", vehicles_src.SOURCE_URL,
                 "Privately kept cars and plug-in vehicles by neighbourhood; England & Wales",
                 lambda: vehicles_src.load_vehicles(s, lsoa_lookup(), census["no_car"]["den"] if "no_car" in census else None), vehicles_src.VEHICLE_METRICS)

    if "children" not in skip:
        optional("children", "SEND and early years (DfE explore education statistics)", children_src.SOURCE_URL,
                 "SEN pupils by constituency; EHC plan timeliness and 2-year-old childcare take-up by council; England",
                 lambda: children_src.load_children(s, council_weights()), children_src.CHILDREN_METRICS)

    if "air_pollution" not in skip:
        optional("air_pollution", "Air pollution mortality (OHID Fingertips)", air_src.SOURCE_URL,
                 "By council, averaged over the councils each seat covers; England",
                 lambda: air_src.load_air(s, council_weights()), air_src.AIR_METRICS)

    if "renewables" not in skip:
        optional("renewables", "Renewable electricity by local authority (DESNZ)", air_src.RENEWABLES_URL,
                 "Solar PV installations by council, shared out across the seats each council covers; England & Wales",
                 lambda: air_src.load_renewables(s, council_weights()), air_src.RENEWABLE_METRICS)

    if "travel" not in skip:
        optional("travel", "Journey time statistics (DfT)", travel_src.SOURCE_URL,
                 "Travel times by public transport or walking, by neighbourhood (2019); England",
                 lambda: travel_src.load_travel(s, lsoa_lookup()), travel_src.TRAVEL_METRICS)

    if "energy" not in skip:
        optional("energy", "Sub-national gas and electricity consumption (DESNZ)", energy_src.SOURCE_URL,
                 "Domestic meters and consumption by neighbourhood; England & Wales",
                 lambda: energy_src.load_energy(s, lsoa_lookup()), energy_src.ENERGY_METRICS)

    if "rents" not in skip:
        optional("rents", "Price Index of Private Rents (ONS)", rents_src.SOURCE_URL,
                 "By council, averaged over the councils each seat covers; England & Wales",
                 lambda: rents_src.load_rents(s, council_weights()), rents_src.RENT_METRICS)

    if "road_condition" not in skip:
        optional("road_condition", "Road condition statistics (DfT)", road_condition_src.SOURCE_URL,
                 "By highway authority, averaged over the authorities each seat covers; England",
                 lambda: road_condition_src.load_road_condition(s, council_weights()), road_condition_src.ROAD_CONDITION_METRICS)

    if "asylum" not in skip:
        optional("asylum", "Immigration system statistics: local authority data (Home Office)", asylum_src.SOURCE_URL,
                 "Asylum support and resettlement by council, shared out across the seats each council covers; England & Wales",
                 lambda: asylum_src.load_asylum(s, council_weights()), asylum_src.ASYLUM_METRICS)

    if "income" not in skip:
        optional("income", "Income and tax by constituency (HMRC)", income_src.SOURCE_URL,
                 "Survey of Personal Incomes, Table 3.15; UK",
                 lambda: income_src.load_income(s), income_src.INCOME_METRICS)

    if "public_health" not in skip:
        optional("public_health", "Public health indicators (OHID Fingertips)", public_health_src.SOURCE_URL,
                 "By council, averaged over the councils each seat covers; England",
                 lambda: public_health_src.load_public_health(s, council_weights()), public_health_src.PUBLIC_HEALTH_METRICS)

    if "pharmacies" not in skip:
        optional("pharmacies", "Consolidated pharmaceutical list (NHSBSA)", pharmacies_src.SOURCE_URL,
                 "Community pharmacies placed by postcode; England",
                 lambda: pharmacies_src.load_pharmacies(s, population), pharmacies_src.PHARMACY_METRICS)

    if "pupils" not in skip:
        optional("pupils", "Pupil absence and KS4 destinations (DfE explore education statistics)", pupils_src.SOURCE_URL,
                 "By council, shared out across the seats each council covers; England",
                 lambda: pupils_src.load_pupils(s, council_weights()), pupils_src.PUPIL_METRICS)

    petitions = None
    if "petitions" not in skip:
        def load_petitions():
            nonlocal petitions
            electorate = frames["turnout"]["den"] if "turnout" in frames else population
            frame, petitions, detail = petitions_src.load_petitions(s, electorate.dropna())
            return {"petition_signatures_per_1k": frame}, detail
        optional("petitions", "Parliament petitions", petitions_src.SOURCE_URL,
                 "Open petitions with 500+ signatures; per 1,000 on the 2024 electoral register", load_petitions,
                 petitions_src.PETITION_METRICS)

    # 4. Assemble seats + values
    metrics, values = assemble(codes, frames, metas)
    seats = []
    for code in codes:
        a = attrs.loc[code].to_dict() if code in attrs.index else {}
        a = {k: v for k, v in a.items() if isinstance(v, str) and v}
        country = a.get("country") or COUNTRY_BY_PREFIX.get(code[0], "")
        m = members.get(code, {})
        seats.append({
            "code": code,
            "name": names[code],
            "country": country,
            "region": a.get("region") or (country if country != "England" else ""),
            "mp": m.get("mp") or a.get("mp_2024"),
            "party": m.get("party") or a.get("first_party"),
            "party_colour": m.get("party_colour"),
            "first_party_2024": a.get("first_party"),
            "second_party_2024": a.get("second_party"),
            "result_2024": a.get("result"),
        })
    neighbourhoods = None
    if lsoa_frames:
        try:
            chosen = {st["code"]: st["name"] for st in seats if st.get("party") and NEIGHBOURHOOD_PARTY.match(st["party"].strip())}
            neighbourhoods = lsoa_src.write_seat_files(s, out_dir, chosen, lsoa_lookup(), lsoa_frames, imd_deciles)
            record("neighbourhoods", "Neighbourhood (LSOA) census profiles", "https://geoportal.statistics.gov.uk/", "ok",
                   f"{len(neighbourhoods['seats'])} Lib Dem seats in England & Wales; {neighbourhoods['lsoas']} LSOAs", "March 2021")
        except Exception as exc:  # noqa: BLE001
            log.exception("Neighbourhood profiles failed")
            record("neighbourhoods", "Neighbourhood (LSOA) census profiles", "https://geoportal.statistics.gov.uk/", "failed", str(exc))

    debates: list[dict] = []
    if "debates" not in skip:
        try:
            debates = debates_src.load_debates(s)
            record("debates", "Upcoming Commons debates (UK Parliament What's On)", debates_src.SOURCE_URL, "ok",
                   f"{len(debates)} debates in the next 3 weeks", datetime.now(timezone.utc).date().isoformat())
        except Exception as exc:  # noqa: BLE001
            log.exception("What's On calendar failed")
            record("debates", "Upcoming Commons debates (UK Parliament What's On)", debates_src.SOURCE_URL, "failed", str(exc))
    return finish(out_dir, geo, seats, metrics, values, sources, demo=False, debates=debates, neighbourhoods=neighbourhoods,
                  petitions=petitions)


def finish(out_dir: Path, geo: dict, seats: list[dict], metrics: list[dict], values: dict[str, list],
           sources: list[dict], demo: bool, debates: list[dict] | None = None, neighbourhoods: dict | None = None,
           petitions: dict | None = None) -> dict:
    """Add peer groups and write all output files."""
    ds = engine.Dataset.from_json({"seats": seats, "metrics": metrics, "values": values})
    groups, group_meta = engine.peer_groups(ds)
    for seat, g in zip(seats, groups):
        seat["peer_group"] = g
    data = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "demo": demo,
        "themes": THEMES,
        "metrics": metrics,
        "seats": seats,
        "values": values,
        "peer_groups": group_meta,
        "sources": sources,
        "debates": debates or [],
        "debate_topics": debates_src.topic_catalogue(),
        "neighbourhoods": neighbourhoods,
        "petitions": petitions,
    }
    (out_dir / "data.json").write_text(json.dumps(data, separators=(",", ":"), allow_nan=False))
    (out_dir / "boundaries.geojson").write_text(json.dumps(geo, separators=(",", ":")))
    wide = pd.DataFrame({"code": [s["code"] for s in seats], "name": [s["name"] for s in seats],
                         "country": [s["country"] for s in seats], "region": [s["region"] for s in seats],
                         "mp": [s["mp"] for s in seats], "party": [s["party"] for s in seats]})
    wide = pd.concat([wide, pd.DataFrame({m["id"]: values[m["id"]] for m in metrics})], axis=1)
    wide.to_csv(out_dir / "constituencies.csv", index=False)
    log.info("Wrote %s: %d seats, %d metrics", out_dir, len(seats), len(metrics))
    return data


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default="frontend/public/data", type=Path)
    p.add_argument("--skip", action="append", default=[], choices=SKIPPABLE,
                   help="Skip an optional source (repeatable); 'lsoa' skips the slow LSOA fallback for census tables")
    p.add_argument("--demo", action="store_true", help="Write a SYNTHETIC demo dataset (no network); for UI development only")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.demo:
        from .demo import build_demo
        build_demo(args.out)
    else:
        build(args.out, set(args.skip))


if __name__ == "__main__":
    main()
