"""Every data source in one place.

Each ``Source`` says what it is (name, link, description), what it provides (metrics), how to load it, how often its
publisher updates it (for the freshness check), how long a downloaded copy may be reused (the cache), and the name
used to skip it (``python -m datadash.build --skip NAME``). ``build.py``, ``demo.py``, ``freshness.py``, the cache and
the refresh workflow's skip list all read from here, so adding a source means adding one entry.

Sources run in the order listed (it is the order of figures and sources in data.json). Most are loaded generically
(``load`` returns frames and a period); the few that need special handling have a ``run`` function instead.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from .metrics import CLAIMANT_METRICS, ELECTION_METRICS, POLICE_METRICS, MetricMeta
from .sources import air_energy as air_src
from .sources import asylum as asylum_src
from .sources import electoral as electoral_src
from .sources import buses as buses_src
from .sources import business_demography as business_demography_src
from .sources import child_poverty as child_poverty_src
from .sources import children as children_src
from .sources import council_control as council_control_src
from .sources import council_tax as council_tax_src
from .sources import courts as courts_src
from .sources import cqc as cqc_src
from .sources import debates as debates_src
from .sources import energy as energy_src
from .sources import epc as epc_src
from .sources import ev as ev_src
from .sources import fire as fire_src
from .sources import floods as floods_src
from .sources import foi_geo as foi_src
from .sources import foi_police as foi_police_src
from .sources import fuel_poverty as fuel_src
from .sources import green_space as green_space_src
from .sources import heat_pumps as heat_pumps_src
from .sources import housing as housing_src
from .sources import housing_stock as housing_stock_src
from .sources import imd as imd_src
from .sources import income as income_src
from .sources import insolvency as insolvency_src
from .sources import life_expectancy as life_src
from .sources import nhs as nhs_src
from .sources import nhsbsa as nhsbsa_src
from .sources import nomis, nomis_extra, parliament, police
from .sources import ofsted as ofsted_src
from .sources import petitions as petitions_src
from .sources import pharmacies as pharmacies_src
from .sources import police_workforce as police_workforce_src
from .sources import police_priorities as priorities_src
from .sources import public_health as public_health_src
from .sources import pupils as pupils_src
from .sources import questions as questions_src
from .sources import rail as rail_src
from .sources import rents as rents_src
from .sources import road_condition as road_condition_src
from .sources import roads as roads_src
from .sources import schools as schools_src
from .sources import scotland as scotland_src
from .sources import sewage as sewage_src
from .sources import travel as travel_src
from .sources import university as university_src
from .sources import vehicles as vehicles_src

if TYPE_CHECKING:
    from .context import BuildContext

log = logging.getLogger(__name__)

# How often each publisher updates (days a source's period may stay unchanged before it's flagged as overdue).
DAILY, MONTHLY, QUARTERLY, HALF_YEARLY, ANNUAL = 4, 50, 120, 220, 430

Loaded = tuple  # (frames, period) or (frames, period, detail)


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    url: str
    detail: str = ""
    metrics: tuple[MetricMeta, ...] = ()
    load: Callable[["BuildContext"], Loaded] | None = None
    run: Callable[["BuildContext", "Source"], None] | None = None
    when: Callable[["BuildContext"], bool] | None = None
    skip: str | None = None  # the --skip name; defaults to id
    skippable: bool = True  # boundaries and Census 2021 are required
    every: int | None = None  # publisher's update cycle in days (freshness check); None: never changes
    keep: int | None = None  # days a downloaded copy may be reused (cache); None: always download
    stage: str = "main"  # "required" and "post" sources are run by build.py itself, before / after the main loop
    module: str | None = None  # the loader's module, for the cache's code fingerprint
    extra_skips: tuple[str, ...] = ()  # further --skip names it answers to (census: lsoa)

    @property
    def skip_name(self) -> str:
        return self.skip or self.id


def _src(module, sid: str, name: str, url: str, detail: str, metrics, load, **kw) -> Source:
    return Source(sid, name, url, detail, tuple(metrics), load, module=module.__name__, **kw)


# --- loaders needing a little glue -------------------------------------------------------------------------------

def _imd(c: "BuildContext") -> Loaded:
    imd = imd_src.load_imd(c.s)
    if c.lsoa_frames is not None:
        c.lsoa_frames.update(imd_src.lsoa_frames(imd))
        c.imd_deciles = imd["decile"]
    return imd_src.seat_frames(imd, c.lsoa_lookup()), "2025", f"{len(imd)} LSOAs; England only; best-fit to constituencies, population-weighted"


def _fuel(c: "BuildContext") -> Loaded:
    seat_f, lsoa_f, year = fuel_src.load_fuel_poverty(c.s)
    if c.lsoa_frames is not None:
        c.lsoa_frames.update(lsoa_f)  # also shown per neighbourhood
    return seat_f, year


def _claimants(c: "BuildContext") -> Loaded:
    cf, period = nomis.load_claimants(c.s)
    return {"claimant_rate": cf}, period


def _aps(c: "BuildContext") -> Loaded:
    got, c.pop_16_64, period = nomis_extra.load_aps(c.s)
    return got, period


def _police(c: "BuildContext") -> Loaded:
    pf, months = police.load_police(c.s, c.geo, c.population)
    return pf, f"{min(months)} to {max(months)}", f"{len(months)} months; England, Wales & Northern Ireland; annualised"


def _council_control(c: "BuildContext") -> Loaded:
    c.councils, period = council_control_src.load_council_control(c.s, c.council_weights(), c.geo)
    return {}, period, f"Councils covering {len(c.councils['by_seat'])} seats; Great Britain"


def _petitions(c: "BuildContext") -> Loaded:
    frame, c.petitions, detail = petitions_src.load_petitions(c.s, c.electorate())
    return {"petition_signatures_per_1k": frame}, detail


def _census_col(c: "BuildContext", metric: str, part: str):
    return c.census[metric][part] if metric in c.census else None


# --- sources that need their own handling ------------------------------------------------------------------------

def _run_elections(c: "BuildContext", src: Source) -> None:
    try:
        try:
            ef, eattrs = parliament.load_results(c.s)
            name, url = src.name, src.url
        except Exception as exc:  # noqa: BLE001 - the Library file can refuse automated downloads
            log.warning("Commons Library results unavailable (%s); using the Members API", exc)
            ef, eattrs = parliament.load_results_api(c.s, c.names)
            name, url = "2024 general election results (UK Parliament Members API)", "https://members-api.parliament.uk/"
        c.frames.update(ef)
        c.metas += list(src.metrics)
        c.attrs = c.attrs.join(eattrs, how="left")
        c.record(src.id, name, url, "ok", f"{len(eattrs)} constituencies", "4 July 2024")
    except Exception as exc:  # noqa: BLE001
        log.exception("Election results failed")
        c.record(src.id, "2024 general election results", "https://members-api.parliament.uk/", "failed", str(exc))


def _run_members(c: "BuildContext", src: Source) -> None:
    from datetime import datetime, timezone
    try:
        c.members = parliament.match_members(parliament.load_members(c.s), c.names)
        c.record(src.id, src.name, src.url, "ok", f"{len(c.members)} seats matched", datetime.now(timezone.utc).date().isoformat())
    except Exception as exc:  # noqa: BLE001
        log.exception("Members API failed")
        c.record(src.id, src.name, src.url, "failed", str(exc))


S = _src
SOURCES: list[Source] = [
    # Required (run by build.py before everything else)
    Source("boundaries", "ONS Open Geography: Westminster constituencies (July 2024)", "https://geoportal.statistics.gov.uk/",
           stage="required", skippable=False),
    Source("census", "Census 2021 (ONS via Nomis)", "https://www.nomisweb.co.uk/sources/census_2021", stage="required", skippable=False,
           extra_skips=("lsoa",)),
    Source("scotland", "Scotland's Census 2022 (National Records of Scotland)", scotland_src.SOURCE_URL, stage="required",
           keep=60, module=scotland_src.__name__),

    # Main sources, in data.json order
    Source("imd", "English Indices of Deprivation 2025 (MHCLG)", imd_src.PAGE_URL, "", tuple(imd_src.IMD_METRICS), _imd, module=imd_src.__name__),
    S(fuel_src, "fuel_poverty", "Sub-regional fuel poverty (DESNZ)", fuel_src.SOURCE_URL,
      "Low Income Low Energy Efficiency measure; England", fuel_src.FUEL_POVERTY_METRICS, _fuel, every=ANNUAL),
    S(sewage_src, "sewage", "Storm overflow spills (Environment Agency EDM annual return)", sewage_src.SOURCE_URL,
      "Overflows placed in seats by outlet location; England & Wales", sewage_src.SEWAGE_METRICS,
      lambda c: sewage_src.load_sewage(c.s, c.geo), every=ANNUAL, keep=13),
    S(rail_src, "rail", "Estimates of station usage (ORR)", rail_src.ORR_PAGE, "Stations located with DfT NaPTAN; Great Britain",
      rail_src.RAIL_METRICS, lambda c: rail_src.load_rail(c.s, c.geo, c.population), keep=13),
    S(courts_src, "courts", "Criminal court statistics: Crown Court (MoJ)", courts_src.SOURCE_URL,
      "By police force area (London combined; South Wales includes Gwent and Dyfed-Powys); England & Wales",
      courts_src.COURT_METRICS, lambda c: courts_src.load_courts(c.s, c.lsoa_lookup(), c.population), every=QUARTERLY),
    S(nomis, "claimants", "ONS Claimant Count (Nomis)", "https://www.nomisweb.co.uk/sources/cc", "", CLAIMANT_METRICS, _claimants, every=MONTHLY),
    S(nomis_extra, "aps", "Annual Population Survey (ONS via Nomis)", nomis_extra.APS_URL, "Great Britain; 12-month survey estimates",
      nomis_extra.APS_METRICS, _aps, every=QUARTERLY),
    S(nomis_extra, "ashe", "Annual Survey of Hours and Earnings (ONS via Nomis)", nomis_extra.ASHE_URL, "Great Britain; medians",
      nomis_extra.ASHE_METRICS, lambda c: nomis_extra.load_ashe(c.s), every=ANNUAL),
    S(nomis_extra, "bres", "Business Register and Employment Survey (ONS via Nomis)", nomis_extra.BRES_URL, "Great Britain; jobs by workplace",
      nomis_extra.BRES_METRICS, lambda c: nomis_extra.load_bres(c.s, c.pop_16_64), every=ANNUAL),
    S(nomis_extra, "business", "UK Business Counts (ONS via Nomis)", nomis_extra.BUSINESS_URL, "Local units; per-resident rate GB only",
      nomis_extra.BUSINESS_METRICS, lambda c: nomis_extra.load_business(c.s, c.pop_16_64), every=ANNUAL),
    S(nomis_extra, "popest", "Small-area population estimates (ONS via Nomis)", nomis_extra.POPEST_URL, "England & Wales",
      nomis_extra.POPEST_METRICS, lambda c: nomis_extra.load_popest(c.s), every=ANNUAL),
    S(schools_src, "gias", "Schools register (DfE Get Information about Schools)", schools_src.GIAS_PAGE,
      "Open schools in England, by July 2024 constituency", schools_src.SCHOOL_METRICS, lambda c: schools_src.load_gias(c.s),
      skip="schools", every=DAILY),
    S(schools_src, "ks4", "GCSE results by constituency (DfE Key stage 4 performance)", schools_src.KS4_PAGE,
      "Pupils' constituency of residence; England", schools_src.KS4_METRICS, lambda c: schools_src.load_ks4(c.s),
      skip="schools", every=ANNUAL),
    S(nhs_src, "nhs", "NHS GP practice data: QOF disease registers and GP Patient Survey (OHID Fingertips)", nhs_src.SOURCE_URL,
      "Practices placed in their constituency by postcode; England", nhs_src.NHS_METRICS, lambda c: nhs_src.load_nhs(c.s),
      every=ANNUAL, keep=6),
    S(epc_src, "epc", "Energy Performance Certificates (MHCLG)", epc_src.SOURCE_URL,
      "Domestic certificates lodged in the last 10 years; England & Wales", epc_src.EPC_METRICS,
      lambda c: epc_src.load_epc(c.s, c.names), keep=6),
    S(police, "police", "police.uk street-level crime", "https://data.police.uk/", "", POLICE_METRICS, _police, every=MONTHLY, keep=6),
    Source("elections", "2024 general election results (House of Commons Library)",
           "https://commonslibrary.parliament.uk/research-briefings/cbp-10009/", metrics=tuple(ELECTION_METRICS), run=_run_elections),
    Source("members", "Current MPs (UK Parliament Members API)", "https://members-api.parliament.uk/", run=_run_members, every=DAILY),
    # After the election results: the change in electors is measured from the 2024 electorate.
    S(electoral_src, "electoral", "Electoral registration (ONS electoral statistics)", electoral_src.SOURCE_URL,
      "Latest 1 December register, current constituencies; UK", electoral_src.ELECTORAL_METRICS,
      lambda c: electoral_src.load_electoral(c.s, c.frames["turnout"]["den"] if "turnout" in c.frames else None), every=ANNUAL),
    S(questions_src, "questions", "Written questions (UK Parliament)", questions_src.SOURCE_URL, "Tabled by each current MP",
      questions_src.QUESTION_METRICS, lambda c: questions_src.load_questions(c.s, c.members), when=lambda c: bool(c.members)),
    S(nhsbsa_src, "dental", "NHS dental activity (NHSBSA)", nhsbsa_src.SOURCE_URL, "Patients seen by dental practices in each seat; England",
      nhsbsa_src.DENTAL_METRICS, lambda c: nhsbsa_src.load_dental(c.s, c.lsoa_lookup(), c.population), every=MONTHLY),
    S(life_src, "life_expectancy", "Life expectancy at birth (OHID Fingertips)", life_src.SOURCE_URL,
      "By council, averaged over the councils each seat covers; England", life_src.LIFE_METRICS,
      lambda c: life_src.load_life_expectancy(c.s, c.council_weights()), every=ANNUAL),
    S(housing_src, "affordability", "Housing affordability (ONS)", housing_src.ONS_PAGE,
      "By council, averaged over the councils each seat covers; England & Wales", housing_src.AFFORDABILITY_METRICS,
      lambda c: housing_src.load_affordability(c.s, c.council_weights()), every=ANNUAL),
    S(housing_src, "homelessness", "Statutory homelessness (MHCLG)", housing_src.HOMELESS_PAGE,
      "By council, shared out across the seats each council covers; England", housing_src.HOMELESS_METRICS,
      lambda c: housing_src.load_homelessness(c.s, c.council_weights()), every=QUARTERLY),
    S(ev_src, "ev", "EV charging infrastructure statistics (DfT, from Zapmap)", ev_src.SOURCE_URL, "Public chargers by constituency; UK",
      ev_src.EV_METRICS, lambda c: ev_src.load_ev(c.s, c.electorate()), every=QUARTERLY),
    S(child_poverty_src, "child_poverty", "Children in low income families (DWP)", child_poverty_src.SOURCE_URL, "By constituency; UK",
      child_poverty_src.CHILD_POVERTY_METRICS, lambda c: child_poverty_src.load_child_poverty(c.s), every=ANNUAL),
    S(housing_stock_src, "housing_stock", "Council Taxbase and net additional dwellings (MHCLG)", housing_stock_src.SOURCE_URL,
      "By council, shared out across the seats each council covers; England", housing_stock_src.HOUSING_STOCK_METRICS,
      lambda c: housing_stock_src.load_housing_stock(c.s, c.council_weights()), every=ANNUAL),
    S(roads_src, "roads", "Road safety data: STATS19 collisions (DfT)", roads_src.SOURCE_URL,
      "Injury collisions placed by neighbourhood or location, last five years; Great Britain", roads_src.ROAD_METRICS,
      lambda c: roads_src.load_roads(c.s, c.geo, c.lsoa_lookup(), c.electorate()), every=ANNUAL, keep=6),
    S(cqc_src, "cqc", "Care Quality Commission ratings (CQC)", cqc_src.SOURCE_URL, "Active registered services placed by location; England",
      cqc_src.CQC_METRICS, lambda c: cqc_src.load_cqc(c.s, c.geo, _census_col(c, "age_65_plus", "num")), keep=6),
    S(buses_src, "buses", "Bus statistics (DfT)", buses_src.SOURCE_URL,
      "By local transport authority, averaged over the authorities each seat covers; England", buses_src.BUS_METRICS,
      lambda c: buses_src.load_buses(c.s, c.council_weights()), every=ANNUAL),
    S(vehicles_src, "vehicles", "Vehicle licensing statistics (DfT)", vehicles_src.SOURCE_URL,
      "Privately kept cars and plug-in vehicles by neighbourhood; England & Wales", vehicles_src.VEHICLE_METRICS,
      lambda c: vehicles_src.load_vehicles(c.s, c.lsoa_lookup(), _census_col(c, "no_car", "den")), every=QUARTERLY, keep=6),
    S(children_src, "children", "SEND and early years (DfE explore education statistics)", children_src.SOURCE_URL,
      "SEN pupils by constituency; EHC plan timeliness and 2-year-old childcare take-up by council; England", children_src.CHILDREN_METRICS,
      lambda c: children_src.load_children(c.s, c.council_weights()), every=ANNUAL),
    S(air_src, "air_pollution", "Air pollution mortality (OHID Fingertips)", air_src.SOURCE_URL,
      "By council, averaged over the councils each seat covers; England", air_src.AIR_METRICS,
      lambda c: air_src.load_air(c.s, c.council_weights()), every=ANNUAL),
    S(air_src, "renewables", "Renewable electricity by local authority (DESNZ)", air_src.RENEWABLES_URL,
      "Solar PV installations by council, shared out across the seats each council covers; England & Wales", air_src.RENEWABLE_METRICS,
      lambda c: air_src.load_renewables(c.s, c.council_weights()), every=ANNUAL),
    S(travel_src, "travel", "Journey time statistics (DfT)", travel_src.SOURCE_URL,
      "Travel times by public transport or walking, by neighbourhood (2019); England", travel_src.TRAVEL_METRICS,
      lambda c: travel_src.load_travel(c.s, c.lsoa_lookup()), keep=60),
    S(energy_src, "energy", "Sub-national gas and electricity consumption (DESNZ)", energy_src.SOURCE_URL,
      "Domestic meters and consumption by neighbourhood; England & Wales", energy_src.ENERGY_METRICS,
      lambda c: energy_src.load_energy(c.s, c.lsoa_lookup()), every=ANNUAL, keep=13),
    S(rents_src, "rents", "Price Index of Private Rents (ONS)", rents_src.SOURCE_URL,
      "By council, averaged over the councils each seat covers; England & Wales", rents_src.RENT_METRICS,
      lambda c: rents_src.load_rents(c.s, c.council_weights()), every=MONTHLY),
    S(road_condition_src, "road_condition", "Road condition statistics (DfT)", road_condition_src.SOURCE_URL,
      "By highway authority, averaged over the authorities each seat covers; England", road_condition_src.ROAD_CONDITION_METRICS,
      lambda c: road_condition_src.load_road_condition(c.s, c.council_weights()), every=ANNUAL),
    S(asylum_src, "asylum", "Immigration system statistics: local authority data (Home Office)", asylum_src.SOURCE_URL,
      "Asylum support and resettlement by council, shared out across the seats each council covers; England & Wales", asylum_src.ASYLUM_METRICS,
      lambda c: asylum_src.load_asylum(c.s, c.council_weights()), every=QUARTERLY),
    S(income_src, "income", "Income and tax by constituency (HMRC)", income_src.SOURCE_URL, "Survey of Personal Incomes, Table 3.15; UK",
      income_src.INCOME_METRICS, lambda c: income_src.load_income(c.s), every=ANNUAL),
    S(public_health_src, "public_health", "Public health indicators (OHID Fingertips)", public_health_src.SOURCE_URL,
      "By council, averaged over the councils each seat covers; England", public_health_src.PUBLIC_HEALTH_METRICS,
      lambda c: public_health_src.load_public_health(c.s, c.council_weights()), every=ANNUAL),
    S(pharmacies_src, "pharmacies", "Consolidated pharmaceutical list (NHSBSA)", pharmacies_src.SOURCE_URL,
      "Community pharmacies placed by postcode; England", pharmacies_src.PHARMACY_METRICS,
      lambda c: pharmacies_src.load_pharmacies(c.s, c.population), every=QUARTERLY),
    S(pupils_src, "pupils", "Pupil absence and KS4 destinations (DfE explore education statistics)", pupils_src.SOURCE_URL,
      "By council, shared out across the seats each council covers; England", pupils_src.PUPIL_METRICS,
      lambda c: pupils_src.load_pupils(c.s, c.council_weights()), every=ANNUAL),
    S(ofsted_src, "ofsted", "School inspection outcomes (Ofsted)", ofsted_src.SOURCE_URL, "State-funded schools by constituency; England",
      ofsted_src.OFSTED_METRICS, lambda c: ofsted_src.load_ofsted(c.s, c.geo), every=MONTHLY),
    S(university_src, "university", "TUNDRA young participation (Office for Students)", university_src.SOURCE_URL,
      "Progression to higher education by neighbourhood; England", university_src.UNIVERSITY_METRICS,
      lambda c: university_src.load_university(c.s, c.lsoa_lookup()), keep=60),
    S(insolvency_src, "insolvency", "Individual insolvencies by constituency (Insolvency Service)", insolvency_src.SOURCE_URL,
      "Latest year; England & Wales", insolvency_src.INSOLVENCY_METRICS, lambda c: insolvency_src.load_insolvency(c.s), every=ANNUAL),
    S(council_tax_src, "council_tax", "Council tax statistics (MHCLG)", council_tax_src.SOURCE_URL,
      "Band D by billing authority, averaged over the councils each seat covers; England", council_tax_src.COUNCIL_TAX_METRICS,
      lambda c: council_tax_src.load_council_tax(c.s, c.council_weights()), every=ANNUAL),
    S(business_demography_src, "business_demography", "Business demography (ONS)", business_demography_src.SOURCE_URL,
      "Business births and deaths by council, shared out across the seats each council covers; England & Wales",
      business_demography_src.BUSINESS_DEMOGRAPHY_METRICS,
      lambda c: business_demography_src.load_business_demography(c.s, c.council_weights()), every=ANNUAL),
    S(floods_src, "floods", "Flood warning areas (Environment Agency)", floods_src.SOURCE_URL, "Warning areas placed by their centre; England",
      floods_src.FLOOD_METRICS, lambda c: floods_src.load_floods(c.s, c.geo)),
    S(green_space_src, "green_space", "Access to gardens and public green space (ONS)", green_space_src.SOURCE_URL,
      "By neighbourhood (2020); England & Wales", green_space_src.GREEN_METRICS,
      lambda c: green_space_src.load_green_space(c.s, c.lsoa_lookup()), keep=60),
    S(heat_pumps_src, "heat_pumps", "Boiler Upgrade Scheme statistics (DESNZ/Ofgem)", heat_pumps_src.SOURCE_URL,
      "Heat pump grants paid by constituency; England & Wales", heat_pumps_src.HEAT_PUMP_METRICS,
      lambda c: heat_pumps_src.load_heat_pumps(c.s, _census_col(c, "no_car", "den")), every=MONTHLY),
    S(police_workforce_src, "police_workforce", "Police workforce (Home Office)", police_workforce_src.SOURCE_URL,
      "Officers per 100,000 people by police force area; England & Wales", police_workforce_src.POLICE_WORKFORCE_METRICS,
      lambda c: police_workforce_src.load_police_workforce(c.s, c.lsoa_lookup(), c.population), every=HALF_YEARLY),
    S(fire_src, "fire", "Fire statistics: response times (Home Office)", fire_src.SOURCE_URL,
      "By fire and rescue authority, averaged over each seat's councils; England", fire_src.FIRE_METRICS,
      lambda c: fire_src.load_fire(c.s, c.council_weights()), every=ANNUAL),
    S(council_control_src, "council_control", "Councillors and council control (Open Council Data UK)", council_control_src.SOURCE_URL,
      "", (), _council_control, every=ANNUAL),
    S(petitions_src, "petitions", "Parliament petitions", petitions_src.SOURCE_URL,
      "Open petitions with more than 100,000 signatures; per 1,000 on the 2024 electoral register", petitions_src.PETITION_METRICS,
      _petitions),

    # After the seats are assembled (run by build.py)
    Source("neighbourhoods", "Neighbourhood (LSOA) census profiles", "https://geoportal.statistics.gov.uk/", stage="post"),
    Source("debates", "Upcoming Commons debates (UK Parliament What's On)", debates_src.SOURCE_URL, stage="post", every=DAILY),
    Source("policing", "Neighbourhood policing priorities (police.uk)", priorities_src.SOURCE_URL, stage="post", every=MONTHLY, keep=7,
           module=priorities_src.__name__),
    Source("foi_police", "FOI: police.uk crime by force", foi_police_src.SOURCE_URL, stage="post", module=foi_police_src.__name__),
    Source("foi", "FOI reference: police force areas, courts and tribunals, NHS trusts and areas", foi_src.SOURCE_URL, stage="post"),
]

BY_ID = {s.id: s for s in SOURCES}


def skip_names() -> list[str]:
    """Every name accepted by ``--skip``, in source order."""
    out: list[str] = []
    for s in SOURCES:
        for name in ((s.skip_name,) if s.skippable else ()) + s.extra_skips:
            if name and name not in out:
                out.append(name)
    return out


def expected_days() -> dict[str, int]:
    """Source id -> days its period may stay unchanged (freshness check)."""
    return {s.id: s.every for s in SOURCES if s.every}


def all_metrics() -> list[MetricMeta]:
    """Every metric the main sources can provide (census metrics are separate: see metrics.CENSUS_METRICS)."""
    return [m for s in SOURCES for m in s.metrics]


def code_files(module: str | None) -> list[Path]:
    """The files whose code a source's saved copy depends on: its module and the pipeline modules it imports
    directly (one level), plus the shared HTTP and metric definitions."""
    root = Path(__file__).parent
    base = [root / "http.py", root / "metrics.py"]
    if not module:
        return base
    path = root / Path(*module.split(".")[1:]).with_suffix(".py")
    if not path.exists():
        return base
    files = {path, *base}
    for m in re.finditer(r"^from (\.+)([\w.]*) import (\([^)]*\)|[^\n]*)", path.read_text(), re.M):
        dots, mod, names = m.group(1), m.group(2), m.group(3)
        folder = path.parent if len(dots) == 1 else path.parent.parent
        targets = [mod] if mod else [n.strip() for n in names.replace("(", "").replace(")", "").split(",")]
        for t in targets:
            p = folder / Path(*t.split(".")).with_suffix(".py")
            if p.exists():
                files.add(p)
    return sorted(files)


__all__ = ["Source", "SOURCES", "BY_ID", "skip_names", "expected_days", "all_metrics", "code_files"]
