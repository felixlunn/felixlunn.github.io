"""Parsing tests for source adapters, using small fixtures shaped like the real API responses."""

import pandas as pd
import pytest
from shapely.geometry import Polygon

from whips.metrics import CENSUS_METRICS, CensusMetric
from whips.sources import nomis, parliament, police

TENURE_LABELS = [
    (0, "Total: All households", 100),
    (1001, "Owned", 60),
    (1, "Owned: Owns outright", 35),
    (2, "Owned: Owns with a mortgage or loan", 25),
    (3, "Shared ownership", 1),
    (1002, "Social rented", 15),
    (4, "Social rented: Rents from council or Local Authority", 8),
    (5, "Social rented: Other social rented", 7),
    (1003, "Private rented", 23),
    (6, "Private rented: Private landlord or letting agency", 20),
    (7, "Private rented: Other private rented", 3),
    (8, "Lives rent free", 1),
]


def nomis_csv(rows, dim="C2021_TENURE_9"):
    recs = []
    for code, name in [("E14001063", "Aldershot"), ("W07000081", "Bangor Aberconwy")]:
        for cat, label, val in rows:
            recs.append({
                "DATE": 2021, "DATE_NAME": "2021", "GEOGRAPHY": 1, "GEOGRAPHY_NAME": name, "GEOGRAPHY_CODE": code,
                "GEOGRAPHY_TYPE": "parliamentary constituencies 2024", dim: cat, f"{dim}_NAME": label,
                "MEASURES": 20100, "MEASURES_NAME": "Value", "OBS_VALUE": val, "OBS_STATUS": "A", "OBS_STATUS_NAME": "Normal Value",
            })
    return pd.DataFrame(recs)


def metric(mid):
    return next(m for m in CENSUS_METRICS if m.id == mid)


def test_category_column_detection():
    df = nomis_csv(TENURE_LABELS)
    assert nomis.category_columns(df) == ("C2021_TENURE_9", "C2021_TENURE_9_NAME")


def test_aggregate_preferred_over_children():
    labels = [lab for _, lab, _ in TENURE_LABELS]
    assert nomis.select_categories(labels, [r"^private rented"]) == ["Private rented"]
    # Without the aggregate row, children are summed instead.
    no_agg = [lab for lab in labels if lab != "Private rented"]
    assert len(nomis.select_categories(no_agg, [r"^private rented"])) == 2


@pytest.mark.parametrize("mid,expected", [
    ("private_rented", 23.0), ("owner_occupied", 60.0), ("owned_outright", 35.0), ("social_rented", 15.0),
])
def test_tenure_metrics(mid, expected):
    tidy = nomis.tidy_census(nomis_csv(TENURE_LABELS))
    out = nomis.compute_census_metric(tidy, metric(mid))
    assert out.loc["E14001063", "num"] / out.loc["E14001063", "den"] == pytest.approx(expected)


def test_tenure_without_aggregates():
    rows = [r for r in TENURE_LABELS if r[0] < 1000]
    tidy = nomis.tidy_census(nomis_csv(rows))
    out = nomis.compute_census_metric(tidy, metric("private_rented"))
    assert (out["num"] / out["den"]).iloc[0] == pytest.approx(23.0)


def test_complement_metric():
    rows = [(0, "Total: All usual residents", 200), (1, "White: English, Welsh, Scottish, Northern Irish or British", 150),
            (2, "White: Irish", 10), (3, "Asian, Asian British or Asian Welsh: Indian", 40)]
    tidy = nomis.tidy_census(nomis_csv(rows, "C2021_ETH_20"))
    out = nomis.compute_census_metric(tidy, metric("ethnic_minority"))
    assert (out["num"] / out["den"]).iloc[0] == pytest.approx(25.0)


def test_overcrowding_regex():
    labels = ["Total: All households", "Occupancy rating of bedrooms: +2 or more", "Occupancy rating of bedrooms: +1",
              "Occupancy rating of bedrooms: 0", "Occupancy rating of bedrooms: -1", "Occupancy rating of bedrooms: -2 or less"]
    assert nomis.select_categories(labels, metric("overcrowded").include) == labels[4:]


def test_economic_activity_nested():
    labels = [
        "Total: All usual residents aged 16 years and over",
        "Economically active (excluding full-time students)",
        "Economically active (excluding full-time students): In employment",
        "Economically active (excluding full-time students): In employment: Employee: Part-time",
        "Economically active (excluding full-time students): Unemployed",
        "Economically active and a full-time student",
        "Economically active and a full-time student: In employment",
        "Economically active and a full-time student: Unemployed",
        "Economically inactive",
        "Economically inactive: Retired",
        "Economically inactive: Long-term sick or disabled",
    ]
    assert nomis.select_categories(labels, metric("in_employment").include) == [labels[2], labels[6]]
    assert nomis.select_categories(labels, metric("unemployed").include) == [labels[4], labels[7]]
    assert nomis.select_categories(labels, metric("retired").include) == [labels[9]]


def test_population_is_count():
    rows = [(0, "Total: All usual residents", 1000), (1, "Lives in a household", 990)]
    tidy = nomis.tidy_census(nomis_csv(rows, "C2021_RESTYPE_3"))
    out = nomis.compute_census_metric(tidy, metric("population"))
    assert (out["num"] / out["den"]).iloc[0] == 1000


def test_unmatched_metric_raises():
    tidy = nomis.tidy_census(nomis_csv(TENURE_LABELS))
    with pytest.raises(ValueError):
        nomis.compute_census_metric(tidy, CensusMetric("x", "x", "housing", "TS054", (r"^nothing here",)))


def test_pick_pcon_type():
    codes = [{"value": "TYPE460", "description": {"value": "westminster parliamentary constituencies 2010"}},
             {"value": 172, "description": {"value": "2024 parliamentary constituencies"}}]
    assert nomis.pick_pcon_type(codes) == "TYPE172"


def test_parse_claimants():
    df = pd.DataFrame([
        {"DATE_NAME": "September 2026", "GEOGRAPHY_CODE": "E1", "MEASURE_NAME": "Claimant count", "OBS_VALUE": 2000},
        {"DATE_NAME": "September 2026", "GEOGRAPHY_CODE": "E1", "MEASURE_NAME": "Claimants as a proportion of residents aged 16-64", "OBS_VALUE": 4.0},
    ])
    out, period = nomis.parse_claimants(df)
    assert period == "September 2026"
    assert out.loc["E1", "num"] / out.loc["E1", "den"] == pytest.approx(4.0)


def test_police_summary_and_outcomes():
    crimes = [
        {"persistent_id": "a", "category": "burglary", "outcome_status": {"category": "Investigation complete; no suspect identified"}},
        {"persistent_id": "a", "category": "burglary", "outcome_status": {"category": "Investigation complete; no suspect identified"}},
        {"persistent_id": "b", "category": "violent-crime", "outcome_status": {"category": "Awaiting court outcome"}},
        {"persistent_id": "c", "category": "violent-crime", "outcome_status": {"category": "Under investigation"}},
        {"persistent_id": "", "id": 9, "category": "anti-social-behaviour", "outcome_status": None},
    ]
    s = police.summarise(crimes)
    assert s["all-crime"] == 4  # duplicate "a" removed
    assert s["violent-crime"] == 2
    assert s["outcome_resolved"] == 2
    assert s["outcome_no_suspect"] == 1 and s["outcome_charged"] == 1


def test_police_poly_format_and_split():
    p = Polygon([(-1.0, 51.0), (-0.9, 51.0), (-0.9, 51.1), (-1.0, 51.1)])
    assert police.poly_param(p).startswith("51.00000,-1.00000:")
    halves = police.split(p)
    assert len(halves) == 2
    assert sum(h.area for h in halves) == pytest.approx(p.area)


def test_parse_results():
    df = pd.DataFrame([{
        "ONS ID": "E14001063", "Constituency name": "Aldershot", "Region name": "South East", "Country name": "England",
        "Member first name": "Alex", "Member surname": "Baker", "Result": "Lab gain from Con",
        "First party": "Lab", "Second party": "Con", "Electorate": "78,000", "Valid votes": "48,000", "Majority": "5,683",
        "Con": 14000, "Lab": 19683, "LD": 5000, "RUK": 6000, "Green": 2000, "SNP": 0, "PC": 0,
    }])
    metrics, attrs = parliament.parse_results(df)
    assert metrics["turnout"].iloc[0]["num"] / metrics["turnout"].iloc[0]["den"] == pytest.approx(48000 / 78000 * 100)
    assert metrics["vote_lab"].iloc[0]["num"] / metrics["vote_lab"].iloc[0]["den"] == pytest.approx(19683 / 480)
    assert attrs.loc["E14001063", "mp_2024"] == "Alex Baker"
    assert attrs.loc["E14001063", "region"] == "South East"


def test_member_matching():
    members = parliament.parse_members([
        {"value": {"id": 1, "nameDisplayAs": "A MP", "latestParty": {"name": "Labour", "backgroundColour": "d50000"},
                   "latestHouseMembership": {"membershipFrom": "Ynys Môn", "membershipEndDate": None}}},
        {"value": {"id": 2, "nameDisplayAs": "B MP", "latestParty": {"name": "Conservative"},
                   "latestHouseMembership": {"membershipFrom": "Brighton Pavilion & Hove", "membershipEndDate": None}}},
    ])
    out = parliament.match_members(members, {"W1": "Ynys Mon", "E1": "Brighton Pavilion and Hove"})
    assert out["W1"]["party_colour"] == "#d50000"
    assert out["E1"]["mp"] == "B MP"
