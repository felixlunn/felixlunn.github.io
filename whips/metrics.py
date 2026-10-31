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
    {"id": "people", "label": "People", "description": "Population, age, ethnicity, birthplace, language and religion (Census 2021)."},
    {"id": "housing", "label": "Housing", "description": "Tenure, overcrowding, heating and household deprivation (Census 2021)."},
    {"id": "economy", "label": "Economy & work", "description": "Employment, inactivity, occupations and the monthly claimant count."},
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
                 description="Share of residents aged 0-14."),
    CensusMetric("age_20_34", "Aged 20-34", "people", "TS007A", (r"^aged (20|25|30) to",),
                 description="Share of residents aged 20-34 (young adults)."),
    CensusMetric("age_65_plus", "Aged 65+", "people", "TS007A", (r"^aged (65|70|75|80|85)",),
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
    CensusMetric("private_rented", "Private rented", "housing", "TS054", (r"^private rented",), polarity="neutral",
                 description="Share of households renting privately."),
    CensusMetric("social_rented", "Social rented", "housing", "TS054", (r"^social rented",),
                 description="Share of households renting from a council or housing association."),
    CensusMetric("overcrowded", "Overcrowded (bedrooms)", "housing", "TS052", (r"(^|[\s:])-[12]",), polarity="higher_worse",
                 description="Share of households with fewer bedrooms than the bedroom standard requires (occupancy rating -1 or less)."),
    CensusMetric("flats", "Flats & maisonettes", "housing", "TS044", (r"^flat, maisonette",),
                 description="Share of households living in a flat, maisonette or apartment."),
    CensusMetric("no_central_heating", "No central heating", "housing", "TS046", (r"^no central heating",), polarity="higher_worse",
                 description="Share of households without central heating."),
    CensusMetric("deprived_2plus", "Deprived in 2+ dimensions", "housing", "TS011", (r"deprived in (two|three|four) dimensions",),
                 polarity="higher_worse",
                 description="Share of households deprived in two or more of: employment, education, health/disability, housing."),
    # --- Economy ------------------------------------------------------------
    CensusMetric("in_employment", "In employment (16+)", "economy", "TS066", (r"in employment",), polarity="higher_better",
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
