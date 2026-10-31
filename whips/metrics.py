"""Catalogue of themes and metrics shown in the dashboard.

Every metric belongs to one theme (the tabs of the thematic organiser) and is
computed as ``numerator / denominator * scale``. Keeping numerator and
denominator separate lets the pipeline compute a true national figure
(sum of numerators / sum of denominators) rather than an average of averages.

Census metrics are defined against Nomis Census 2021 "TS" tables. Category
labels are matched with regular expressions (case-insensitive) so the pipeline
is robust to small wording differences; see ``whips.sources.nomis`` for the
matching rules (aggregate categories win over their children, so nothing is
double counted).
"""

from __future__ import annotations

from dataclasses import dataclass, field

THEMES: list[dict[str, str]] = [
    {"id": "people", "label": "People", "description": "Population, age, ethnicity, birthplace, passports, language, religion and identity (Census 2021, ONS population estimates)."},
    {"id": "households", "label": "Households", "description": "Household make-up, family types, marital status and household language (Census 2021)."},
    {"id": "housing", "label": "Housing", "description": "Tenure, overcrowding, heating and household deprivation (Census 2021)."},
    {"id": "economy", "label": "Economy & work", "description": "Employment, inactivity, occupations and the monthly claimant count."},
    {"id": "jobs", "label": "Jobs & pay", "description": "Earnings (ASHE), local jobs by industry (BRES), business counts and labour market rates (APS)."},
    {"id": "deprivation", "label": "Deprivation", "description": "English Indices of Deprivation 2025 (MHCLG): neighbourhood scores combined by population. England only."},
    {"id": "health", "label": "Health & care", "description": "Self-reported health, disability and unpaid care (Census 2021)."},
    {"id": "education", "label": "Education & skills", "description": "Adult qualification levels and students (Census 2021)."},
    {"id": "transport", "label": "Transport", "description": "How and how far people travel to work, and car access (Census 2021)."},
    {"id": "policing", "label": "Policing", "description": "Recorded street-level crime and investigation outcomes (police.uk)."},
    {"id": "politics", "label": "Politics", "description": "2024 general election result, turnout and vote shares (House of Commons Library)."},
]

THEME_IDS = [t["id"] for t in THEMES]


@dataclass(frozen=True)
class CensusMetric:
    """A percentage computed from one Census 2021 table on Nomis."""

    id: str
    label: str
    theme: str
    table: str  # e.g. "TS054"
    include: tuple[str, ...]  # regexes; matching categories form the numerator
    complement: bool = False  # numerator = total - matched
    description: str = ""
    polarity: str = "neutral"  # "higher_worse" | "higher_better" | "neutral"
    unit: str = "%"
    is_count: bool = False  # value is the total itself (e.g. population)
    fallback: tuple[str, tuple[str, ...]] | None = None  # (table, include) tried if the main table fails


@dataclass(frozen=True)
class MetricMeta:
    id: str
    label: str
    theme: str
    unit: str
    description: str
    source: str
    polarity: str = "neutral"
    decimals: int = 1
    tags: tuple[str, ...] = field(default_factory=tuple)


CENSUS_METRICS: list[CensusMetric] = [
    # --- People -------------------------------------------------------------
    CensusMetric("population", "Usual residents", "people", "TS001", (), is_count=True, unit="people",
                 description="Usual resident population, Census 2021."),
    CensusMetric("age_0_14", "Aged 0-14", "people", "TS007A", (r"^aged (4 years and under|5 to 9|10 to 14)",),
                 fallback=("TS007", (r"^aged (under 1 year|[1-9] years?|1[0-4] years)$",)),
                 description="Share of residents aged 0-14."),
    CensusMetric("age_20_34", "Aged 20-34", "people", "TS007A", (r"^aged (20|25|30) to",),
                 fallback=("TS007", (r"^aged (2\d|3[0-4]) years$",)),
                 description="Share of residents aged 20-34 (young adults)."),
    CensusMetric("age_65_plus", "Aged 65+", "people", "TS007A", (r"^aged (65|70|75|80|85)",),
                 fallback=("TS007", (r"^aged (6[5-9]|[7-9]\d|100) years",)),
                 description="Share of residents aged 65 and over."),
    CensusMetric("ethnic_minority", "Not White British", "people", "TS021", (r"^white: english",), complement=True,
                 description="Share of residents in any ethnic group other than White: English, Welsh, Scottish, Northern Irish or British."),
    CensusMetric("born_outside_uk", "Born outside the UK", "people", "TS004", (r"united kingdom",), complement=True,
                 description="Share of residents born outside the United Kingdom."),
    CensusMetric("english_not_main", "English not main language", "people", "TS029", (r"^main language is english",), complement=True,
                 description="Share of residents aged 3+ whose main language is not English (English or Welsh in Wales)."),
    CensusMetric("religion_christian", "Christian", "people", "TS030", (r"^christian",),
                 description="Share of residents who identify as Christian."),
    CensusMetric("religion_muslim", "Muslim", "people", "TS030", (r"^muslim",),
                 description="Share of residents who identify as Muslim."),
    CensusMetric("religion_none", "No religion", "people", "TS030", (r"^no religion",),
                 description="Share of residents reporting no religion."),
    # --- Housing ------------------------------------------------------------
    CensusMetric("owner_occupied", "Owner occupied", "housing", "TS054", (r"^owned",),
                 description="Share of households that own their home outright or with a mortgage."),
    CensusMetric("owned_outright", "Owned outright", "housing", "TS054", (r"owns outright",),
                 description="Share of households owning outright (no mortgage)."),
    CensusMetric("private_rented", "Private rented", "housing", "TS054", (r"^private rented($|: )",), polarity="neutral",
                 description="Share of households renting privately."),
    CensusMetric("social_rented", "Social rented", "housing", "TS054", (r"^social rented",),
                 description="Share of households renting from a council or housing association."),
    CensusMetric("overcrowded", "Overcrowded (bedrooms)", "housing", "TS052", (r"(^|[\s:])-[12]",), polarity="higher_worse",
                 description="Share of households with fewer bedrooms than the bedroom standard requires (occupancy rating -1 or less)."),
    CensusMetric("flats", "Flats & maisonettes", "housing", "TS044", (r"(^flat, maisonette|block of flats|converted or shared house|another converted building|commercial building)",),
                 description="Share of households living in a flat, maisonette or apartment."),
    CensusMetric("no_central_heating", "No central heating", "housing", "TS046", (r"^no central heating",), polarity="higher_worse",
                 description="Share of households without central heating."),
    CensusMetric("deprived_2plus", "Deprived in 2+ dimensions", "housing", "TS011", (r"deprived in (two|three|four) dimensions",),
                 polarity="higher_worse",
                 description="Share of households deprived in two or more of: employment, education, health/disability, housing."),
    # --- Economy ------------------------------------------------------------
    CensusMetric("in_employment", "In employment (16+)", "economy", "TS066", (r"^economically active.*:\s?in employment$",), polarity="higher_better",
                 description="Share of residents aged 16+ in employment (including full-time students who work)."),
    CensusMetric("unemployed", "Unemployed (16+)", "economy", "TS066", (r": unemployed",), polarity="higher_worse",
                 description="Share of residents aged 16+ who were unemployed in the census week."),
    CensusMetric("inactive_sick", "Long-term sick or disabled", "economy", "TS066", (r"long-term sick or disabled",), polarity="higher_worse",
                 description="Share of residents aged 16+ economically inactive because of long-term sickness or disability."),
    CensusMetric("retired", "Retired", "economy", "TS066", (r"inactive: retired",),
                 description="Share of residents aged 16+ who are retired."),
    CensusMetric("nssec_professional", "Managerial & professional", "economy", "TS062", (r"^l1, l2 and l3", r"^l4, l5 and l6"),
                 description="Share of residents aged 16+ in higher or lower managerial, administrative and professional occupations (NS-SeC 1-2)."),
    CensusMetric("nssec_routine", "Routine & semi-routine", "economy", "TS062", (r"^l12", r"^l13"),
                 description="Share of residents aged 16+ in semi-routine or routine occupations (NS-SeC 6-7)."),
    CensusMetric("nssec_self_employed", "Small employers & own-account", "economy", "TS062", (r"^l8 and l9",),
                 description="Share of residents aged 16+ who are small employers or own-account workers (NS-SeC 4)."),
    # --- Health -------------------------------------------------------------
    CensusMetric("bad_health", "Bad or very bad health", "health", "TS037", (r"^(bad|very bad) health",), polarity="higher_worse",
                 description="Share of residents describing their health as bad or very bad."),
    CensusMetric("disabled", "Disabled (Equality Act)", "health", "TS038", (r"^disabled under the equality act",), polarity="higher_worse",
                 description="Share of residents disabled under the Equality Act."),
    CensusMetric("unpaid_carers", "Unpaid carers", "health", "TS039", (r"^provides no unpaid care",), complement=True,
                 description="Share of residents aged 5+ providing any unpaid care."),
    # --- Education ----------------------------------------------------------
    CensusMetric("level4_plus", "Degree-level (Level 4+)", "education", "TS067", (r"^level 4",), polarity="higher_better",
                 description="Share of residents aged 16+ with Level 4 qualifications or above (degree, HND, professional)."),
    CensusMetric("no_qualifications", "No qualifications", "education", "TS067", (r"^no qualifications",), polarity="higher_worse",
                 description="Share of residents aged 16+ with no qualifications."),
    CensusMetric("apprenticeship", "Apprenticeship", "education", "TS067", (r"^apprenticeship",),
                 description="Share of residents aged 16+ whose highest qualification is an apprenticeship."),
    CensusMetric("students", "Full-time students (16+)", "education", "TS062", (r"^l15",),
                 description="Share of residents aged 16+ who are full-time students."),
    # --- Transport ----------------------------------------------------------
    CensusMetric("work_from_home", "Work mainly from home", "transport", "TS061", (r"from home",),
                 description="Share of working residents who mainly worked at or from home (census week, March 2021 - lockdown period)."),
    CensusMetric("commute_car", "Drive to work", "transport", "TS061", (r"^driving a car",),
                 description="Share of working residents who mainly drive a car or van to work."),
    CensusMetric("commute_public", "Public transport to work", "transport", "TS061", (r"^(underground|train|bus)",),
                 description="Share of working residents who mainly travel by underground, train or bus."),
    CensusMetric("commute_active", "Walk or cycle to work", "transport", "TS061", (r"^(on foot|bicycle)",),
                 description="Share of working residents who mainly walk or cycle to work."),
    CensusMetric("commute_30km_plus", "Commute 30km+", "transport", "TS058", (r"^(30|40|60) ?km",),
                 description="Share of working residents travelling 30km or more to work."),
    CensusMetric("no_car", "Households with no car", "transport", "TS045", (r"^no cars",),
                 description="Share of households with no car or van."),
]


def _c(id, label, theme, table, *include, **kw) -> CensusMetric:
    return CensusMetric(id, label, theme, table, tuple(include), **kw)


# Further census metrics. Category labels verified against the Nomis tables (England & Wales totals).
CENSUS_METRICS += [
    # --- People -------------------------------------------------------------
    _c("density", "Population density", "people", "TS006", is_count=True, unit="per sq km",
       description="Usual residents per square kilometre, Census 2021."),
    _c("female", "Female", "people", "TS008", r"^female$", description="Share of residents who are female."),
    _c("age_35_49", "Aged 35-49", "people", "TS007A", r"^aged (35|40|45) to", description="Share of residents aged 35-49."),
    _c("age_50_64", "Aged 50-64", "people", "TS007A", r"^aged (50|55|60) to", description="Share of residents aged 50-64."),
    _c("age_80_plus", "Aged 80+", "people", "TS007A", r"^aged (80 to|85 years)", description="Share of residents aged 80 and over."),
    _c("eth_asian", "Asian", "people", "TS021", r"^asian, asian british",
       description="Share of residents in the Asian, Asian British or Asian Welsh ethnic group."),
    _c("eth_indian", "Indian", "people", "TS021", r"^asian.*: indian$", description="Share of residents of Indian ethnicity."),
    _c("eth_pakistani", "Pakistani", "people", "TS021", r"^asian.*: pakistani$", description="Share of residents of Pakistani ethnicity."),
    _c("eth_bangladeshi", "Bangladeshi", "people", "TS021", r"^asian.*: bangladeshi$", description="Share of residents of Bangladeshi ethnicity."),
    _c("eth_black", "Black", "people", "TS021", r"^black, black british",
       description="Share of residents in the Black, Black British, Black Welsh, Caribbean or African ethnic group."),
    _c("eth_black_african", "Black African", "people", "TS021", r"^black.*: african$", description="Share of residents of Black African ethnicity."),
    _c("eth_black_caribbean", "Black Caribbean", "people", "TS021", r"^black.*: caribbean$", description="Share of residents of Black Caribbean ethnicity."),
    _c("eth_mixed", "Mixed or multiple", "people", "TS021", r"^mixed or multiple", description="Share of residents in a Mixed or Multiple ethnic group."),
    _c("eth_white_other", "Other White", "people", "TS021", r"^white: (other white|irish|roma|gypsy)",
       description="Share of residents who are White but not White British (Irish, Gypsy or Irish Traveller, Roma, Other White)."),
    _c("religion_hindu", "Hindu", "people", "TS030", r"^hindu", description="Share of residents who identify as Hindu."),
    _c("religion_sikh", "Sikh", "people", "TS030", r"^sikh", description="Share of residents who identify as Sikh."),
    _c("religion_jewish", "Jewish", "people", "TS030", r"^jewish", description="Share of residents who identify as Jewish."),
    _c("passport_none", "No passport", "people", "TS005", r"^no passport held", description="Share of residents holding no passport."),
    _c("passport_eu", "EU passport", "people", "TS005", r"eu member countries$", description="Share of residents holding an EU member country passport."),
    _c("arrived_since_2011", "Arrived in UK since 2011", "people", "TS015", r"^arrived (2011|2014|2017|2020)",
       description="Share of residents born abroad who arrived in the UK in 2011 or later."),
    _c("lgb_plus", "Gay, lesbian, bisexual or other", "people", "TS077", r"^(gay or lesbian|bisexual|all other sexual)",
       description="Share of residents aged 16+ identifying as gay or lesbian, bisexual or another minority sexual orientation."),
    _c("trans", "Gender identity differs from sex at birth", "people", "TS078", r"^(gender identity different|trans |all other gender)",
       description="Share of residents aged 16+ whose gender identity differs from their sex registered at birth."),
    # --- Households ---------------------------------------------------------
    _c("hh_one_person", "One-person households", "households", "TS003", r"^one-person household",
       description="Share of households with one person."),
    _c("hh_alone_66", "Living alone aged 66+", "households", "TS003", r"^one-person household: aged 66",
       description="Share of households that are one person aged 66 or over."),
    _c("hh_pensioner", "Pensioner households", "households", "TS003", r"^(one-person household: aged 66|single family household: all aged 66)",
       description="Share of households where everyone is aged 66 or over (single people and families)."),
    _c("hh_dependent_children", "Households with dependent children", "households", "TS003", r"(^|: )(with )?dependent children$",
       description="Share of households with at least one dependent child."),
    _c("hh_lone_parent", "Lone parents with dependent children", "households", "TS003", r"lone parent family: with dependent children",
       description="Share of households that are lone-parent families with dependent children."),
    _c("hh_large", "Households of 5+ people", "households", "TS017", r"^([5-7] people|8 or more)",
       description="Share of households with five or more people."),
    _c("married", "Married or civil partnership", "households", "TS002", r"^married or in a registered",
       description="Share of residents aged 16+ who are married or in a registered civil partnership."),
    _c("divorced", "Divorced", "households", "TS002", r"^divorced", description="Share of residents aged 16+ who are divorced or whose civil partnership was dissolved."),
    _c("hh_no_english", "No one has English as main language", "households", "TS025", r"^no people in household have english",
       description="Share of households where nobody's main language is English (English or Welsh in Wales)."),
    # --- Housing ------------------------------------------------------------
    _c("mortgage", "Owned with a mortgage", "housing", "TS054", r"^owned: owns with a mortgage",
       description="Share of households buying their home with a mortgage or loan."),
    _c("shared_ownership", "Shared ownership", "housing", "TS054", r"^shared ownership$", description="Share of households in shared ownership."),
    _c("detached", "Detached houses", "housing", "TS044", r"^detached", description="Share of households living in a detached house or bungalow."),
    _c("semi_detached", "Semi-detached houses", "housing", "TS044", r"^semi-detached", description="Share of households living in a semi-detached house or bungalow."),
    _c("terraced", "Terraced houses", "housing", "TS044", r"^terraced", description="Share of households living in a terraced house."),
    _c("caravan", "Caravans & mobile homes", "housing", "TS044", r"^a caravan", description="Share of households living in a caravan or other mobile or temporary structure."),
    _c("bedrooms_4plus", "4+ bedrooms", "housing", "TS050", r"^4 or more bedrooms", description="Share of households with four or more bedrooms."),
    _c("bedrooms_1", "1 bedroom", "housing", "TS050", r"^1 bedroom", description="Share of households with one bedroom."),
    _c("under_occupied", "Under-occupied (2+ spare bedrooms)", "housing", "TS052", r"\+2 or more",
       description="Share of households with at least two more bedrooms than the bedroom standard requires."),
    _c("heat_gas", "Mains gas heating", "housing", "TS046", r"^mains gas only", description="Share of households heated only by mains gas."),
    _c("heat_oil", "Oil heating (off gas grid)", "housing", "TS046", r"^oil only", description="Share of households heated only by oil."),
    _c("heat_electric", "Electric heating", "housing", "TS046", r"^electric only", description="Share of households heated only by electricity."),
    _c("heat_renewable", "Renewable heating", "housing", "TS046", r"(^renewable energy only|\(including renewable energy\))",
       description="Share of households whose central heating includes renewable energy (e.g. heat pumps, solar thermal)."),
    _c("deprived_any", "Deprived in any dimension", "housing", "TS011", r"deprived in (one|two|three|four) dimension", polarity="higher_worse",
       description="Share of households deprived in at least one of: employment, education, health/disability, housing."),
    # --- Economy ------------------------------------------------------------
    _c("self_employed", "Self-employed", "economy", "TS066", r":\s?in employment:\s?self-employed with(out)? employees$",
       description="Share of residents aged 16+ who are self-employed (with or without employees)."),
    _c("looking_after_home", "Looking after home or family", "economy", "TS066", r"looking after home",
       description="Share of residents aged 16+ economically inactive because they look after the home or family."),
    _c("part_time", "Part-time workers", "economy", "TS059", r"^part-time$", description="Share of working residents working 30 hours a week or less."),
    _c("long_hours", "Work 49+ hours a week", "economy", "TS059", r"49 or more hours", description="Share of working residents working 49 or more hours a week."),
    _c("never_worked", "Never worked (of those not working)", "economy", "TS065", r"never worked", polarity="higher_worse",
       description="Share of residents aged 16+ not in employment who have never worked."),
    _c("occ_professional", "Professional occupations", "economy", "TS063", r"^2\. professional", description="Share of working residents in professional occupations (SOC 2)."),
    _c("occ_skilled_trades", "Skilled trades", "economy", "TS063", r"^5\. skilled trades", description="Share of working residents in skilled trades (SOC 5)."),
    _c("occ_caring", "Caring, leisure & service jobs", "economy", "TS063", r"^6\. caring", description="Share of working residents in caring, leisure and other service occupations (SOC 6)."),
    _c("occ_elementary", "Elementary occupations", "economy", "TS063", r"^9\. elementary", description="Share of working residents in elementary occupations (SOC 9)."),
    # --- Health -------------------------------------------------------------
    _c("very_good_health", "Very good health", "health", "TS037", r"^very good health", polarity="higher_better",
       description="Share of residents describing their health as very good."),
    _c("disabled_a_lot", "Activities limited a lot", "health", "TS038", r"limited a lot", polarity="higher_worse",
       description="Share of residents disabled under the Equality Act whose day-to-day activities are limited a lot."),
    _c("carers_50h", "Unpaid care 50+ hours a week", "health", "TS039", r"50 or more hours",
       description="Share of residents aged 5+ providing 50 or more hours of unpaid care a week."),
    # --- Education ----------------------------------------------------------
    _c("level3", "A-level or equivalent (Level 3)", "education", "TS067", r"^level 3", description="Share of residents aged 16+ whose highest qualification is Level 3."),
    _c("level1_2", "GCSE-level (Levels 1-2)", "education", "TS067", r"^level (1|2)", description="Share of residents aged 16+ whose highest qualification is Level 1, entry level or Level 2."),
    _c("in_education", "In education (aged 5+)", "education", "TS068", r"^student$", description="Share of residents aged 5+ who are schoolchildren or students in full-time education."),
    # --- Transport ----------------------------------------------------------
    _c("cars_2plus", "Households with 2+ cars", "transport", "TS045", r"^(2|3 or more) cars", description="Share of households with two or more cars or vans."),
    _c("commute_train", "Train or metro to work", "transport", "TS061", r"^(underground|train)", description="Share of working residents who mainly travel to work by train, underground, metro, light rail or tram."),
    _c("commute_bus", "Bus to work", "transport", "TS061", r"^bus", description="Share of working residents who mainly travel to work by bus, minibus or coach."),
    _c("commute_cycle", "Cycle to work", "transport", "TS061", r"^bicycle", description="Share of working residents who mainly cycle to work."),
    _c("commute_under_2km", "Commute under 2km", "transport", "TS058", r"^less than 2km", description="Share of working residents travelling less than 2km to work."),
]

# Non-census metrics: populated by their own source modules.
CLAIMANT_METRICS = [
    MetricMeta("claimant_rate", "Claimant rate (16-64)", "economy", "%",
               "Claimants of unemployment-related benefits as a share of residents aged 16-64 (latest month, ONS claimant count via Nomis).",
               "ONS Claimant Count (Nomis)", "higher_worse"),
]

POLICE_CATEGORIES: dict[str, tuple[str, str]] = {
    # police.uk category id -> (metric id, label)
    "all-crime": ("crime_rate", "All recorded crime"),
    "violent-crime": ("crime_violence", "Violence & sexual offences"),
    "anti-social-behaviour": ("crime_asb", "Anti-social behaviour"),
    "burglary": ("crime_burglary", "Burglary"),
    "shoplifting": ("crime_shoplifting", "Shoplifting"),
    "vehicle-crime": ("crime_vehicle", "Vehicle crime"),
    "drugs": ("crime_drugs", "Drugs"),
}

POLICE_METRICS = [
    *[
        MetricMeta(mid, f"{label} per 1,000", "policing", "per 1,000",
                   f"{label} recorded by police.uk within the constituency boundary, annualised per 1,000 residents.",
                   "police.uk", "higher_worse")
        for mid, label in POLICE_CATEGORIES.values()
    ],
    MetricMeta("outcome_no_suspect", "Closed: no suspect identified", "policing", "%",
               "Of crimes with a final recorded outcome, the share closed with no suspect identified. Recent months are provisional.",
               "police.uk", "higher_worse"),
    MetricMeta("outcome_charged", "Charged / court outcome", "policing", "%",
               "Of crimes with a final recorded outcome, the share where a suspect was charged or the case went to court. Recent months are provisional.",
               "police.uk", "higher_better"),
]

ELECTION_PARTIES = {
    # CSV column -> (metric id, label)
    "Lab": ("vote_lab", "Labour vote share"),
    "Con": ("vote_con", "Conservative vote share"),
    "LD": ("vote_ld", "Liberal Democrat vote share"),
    "RUK": ("vote_reform", "Reform UK vote share"),
    "Green": ("vote_green", "Green vote share"),
    "SNP": ("vote_snp", "SNP vote share"),
    "PC": ("vote_pc", "Plaid Cymru vote share"),
}

ELECTION_METRICS = [
    MetricMeta("majority_pct", "Majority", "politics", "%", "Winning majority as a share of valid votes, 2024 general election.",
               "House of Commons Library"),
    MetricMeta("turnout", "Turnout", "politics", "%", "Valid votes as a share of the electorate, 2024 general election.",
               "House of Commons Library", "higher_better"),
    *[
        MetricMeta(mid, label, "politics", "%", f"{label}, 2024 general election.", "House of Commons Library")
        for mid, label in ELECTION_PARTIES.values()
    ],
]


def census_meta(m: CensusMetric) -> MetricMeta:
    return MetricMeta(
        id=m.id,
        label=m.label,
        theme=m.theme,
        unit=m.unit,
        description=m.description,
        source=f"Census 2021 {m.table} (ONS via Nomis)",
        polarity=m.polarity,
        decimals=0 if m.is_count else 1,
        tags=("census",),
    )
