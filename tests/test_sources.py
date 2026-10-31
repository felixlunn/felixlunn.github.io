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


def test_tenure_ignores_combined_subtotals():
    # Real TS054 also carries derived subtotals that would double count.
    rows = TENURE_LABELS + [(9996, "Owns with a mortgage or loan or shared ownership", 26),
                            (9997, "Private rented or lives rent free", 24)]
    tidy = nomis.tidy_census(nomis_csv(rows))
    out = nomis.compute_census_metric(tidy, metric("private_rented"))
    assert (out["num"] / out["den"]).iloc[0] == pytest.approx(23.0)
    out = nomis.compute_census_metric(tidy, metric("mortgage"))
    assert (out["num"] / out["den"]).iloc[0] == pytest.approx(25.0)


def test_economic_activity_real_label_spacing():
    # Nomis writes TS066 aggregates without a space after the colon ("...students):In employment").
    labels = [
        "Total: All usual residents aged 16 years and over",
        "Economically active (excluding full-time students)",
        "Economically active (excluding full-time students):In employment",
        "Economically active (excluding full-time students):In employment:Employee",
        "Economically active (excluding full-time students): In employment: Employee: Part-time",
        "Economically active (excluding full-time students):In employment:Self-employed with employees",
        "Economically active (excluding full-time students): In employment: Self-employed with employees: Full-time",
        "Economically active (excluding full-time students):In employment:Self-employed without employees",
        "Economically active and a full-time student:In employment",
        "Economically active and a full-time student:In employment:Self-employed without employees",
        "Economically active and a full-time student: In employment: Self-employed without employees: Part-time",
    ]
    assert nomis.select_categories(labels, metric("in_employment").include) == [labels[2], labels[8]]
    assert nomis.select_categories(labels, metric("self_employed").include) == [labels[5], labels[7], labels[9]]


def test_flats_and_renewable_heating_labels():
    acc = ["Total", "Detached", "Semi-detached", "Terraced", "In a purpose-built block of flats or tenement",
           "Part of a converted or shared house, including bedsits", "Part of another converted building, for example, former school, church or warehouse",
           "In a commercial building, for example, in an office building, hotel or over a shop", "A caravan or other mobile or temporary structure"]
    assert nomis.select_categories(acc, metric("flats").include) == acc[4:8]
    heat = ["Total: All households", "Mains gas only", "Renewable energy only",
            "Two or more types of central heating (not including renewable energy)",
            "Two or more types of central heating (including renewable energy)"]
    assert nomis.select_categories(heat, metric("heat_renewable").include) == [heat[2], heat[4]]


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


def test_single_year_age_fallback_regexes():
    labels = ["Total: All usual residents", "Aged under 1 year", "Aged 1 year", "Aged 2 years", "Aged 14 years", "Aged 15 years",
              "Aged 20 years", "Aged 34 years", "Aged 35 years", "Aged 64 years", "Aged 65 years", "Aged 99 years", "Aged 100 years and over"]
    pick = lambda mid: nomis.select_categories(labels, metric(mid).fallback[1])  # noqa: E731
    assert pick("age_0_14") == ["Aged under 1 year", "Aged 1 year", "Aged 2 years", "Aged 14 years"]
    assert pick("age_20_34") == ["Aged 20 years", "Aged 34 years"]
    assert pick("age_65_plus") == ["Aged 65 years", "Aged 99 years", "Aged 100 years and over"]


def test_load_census_skips_failed_table_and_uses_fallback(monkeypatch):
    tenure = nomis.tidy_census(nomis_csv(TENURE_LABELS))
    pop = nomis.tidy_census(nomis_csv([(0, "Total: All usual residents", 1000)], "C2021_RESTYPE_3"))
    ages = nomis.tidy_census(nomis_csv([(0, "Total: All usual residents", 100), (66, "Aged 65 years", 30)], "C2021_AGE_102"))
    tables = {"TS001": pop, "TS054": tenure, "TS007": ages}
    monkeypatch.setattr(nomis, "find_dataset", lambda s, code: code)
    monkeypatch.setattr(nomis, "find_pcon_type", lambda s, ds: "TYPE172")

    def fake_fetch(s, ds, params):
        if ds not in tables:
            raise ValueError("Nomis returned an empty response")
        return "raw:" + ds

    monkeypatch.setattr(nomis, "fetch_csv", fake_fetch)
    monkeypatch.setattr(nomis, "tidy_census", lambda raw: tables[raw[4:]])
    wanted = [metric(m) for m in ("population", "private_rented", "age_65_plus", "bad_health")]
    out, _names, prov = nomis.load_census(None, wanted)
    assert set(out) == {"population", "private_rented", "age_65_plus"}
    assert (out["age_65_plus"]["num"] / out["age_65_plus"]["den"]).iloc[0] == pytest.approx(30.0)
    assert "TS007A" in prov["failed"] and "TS037" in prov["failed"]


def test_aggregate_lsoa_and_lookup_parsing():
    from whips.sources import boundaries
    lookup = boundaries.parse_lookup([
        {"attributes": {"LSOA21CD": "E01000001", "PCON24CD": "E14000001", "ObjectId": 1}},
        {"attributes": {"lsoa21cd": "E01000002", "pcon24cd": "E14000001"}},
        {"attributes": {"LSOA21CD": "E01000003", "PCON24CD": "E14000002"}},
    ])
    assert lookup == {"E01000001": "E14000001", "E01000002": "E14000001", "E01000003": "E14000002"}
    lsoa = pd.DataFrame({
        "code": ["E01000001", "E01000001", "E01000002", "E01000002", "E01000003", "E01000003", "W01999999"],
        "name": "x", "cat": [0, 1, 0, 1, 0, 1, 0],
        "label": ["Total: All households", "Private rented"] * 3 + ["Total: All households"],
        "value": [10, 2, 30, 6, 50, 25, 99],
    })
    agg = nomis.aggregate_lsoa(lsoa, lookup)
    out = nomis.compute_census_metric(agg, metric("private_rented"))
    assert out.loc["E14000001", "num"] / out.loc["E14000001", "den"] == pytest.approx(20.0)
    assert out.loc["E14000002", "num"] / out.loc["E14000002", "den"] == pytest.approx(50.0)


def test_empty_constituency_table_falls_back_to_lsoas(monkeypatch):
    calls = []
    pop = nomis_csv([(0, "Total: All usual residents", 1000)], "C2021_RESTYPE_3")
    lsoa_tenure = pd.DataFrame([
        {"GEOGRAPHY_CODE": lsoa, "GEOGRAPHY_NAME": lsoa, "C2021_TENURE_9": cat, "C2021_TENURE_9_NAME": label,
         "MEASURES": 20100, "OBS_VALUE": v}
        for lsoa, cat, label, v in [("L1", 0, "Total: All households", 40), ("L1", 1003, "Private rented", 10),
                                    ("L2", 0, "Total: All households", 60), ("L2", 1003, "Private rented", 20)]
    ])
    monkeypatch.setattr(nomis, "find_dataset", lambda s, code: code)
    monkeypatch.setattr(nomis, "find_pcon_type", lambda s, ds: "TYPE172")
    monkeypatch.setattr(nomis, "find_lsoa_type", lambda s, ds: "TYPE151")

    def fake_fetch(s, ds, params):
        calls.append((ds, params["geography"]))
        if ds == "TS001":
            return pop
        if params["geography"] == "TYPE172":
            raise nomis.EmptyResponse("empty")
        return lsoa_tenure

    monkeypatch.setattr(nomis, "fetch_csv", fake_fetch)
    out, _n, prov = nomis.load_census(None, [metric("population"), metric("private_rented")],
                                      lambda: {"L1": "E14001063", "L2": "E14001063"})
    assert (out["private_rented"]["num"] / out["private_rented"]["den"]).loc["E14001063"] == pytest.approx(30.0)
    assert prov["aggregated_from_lsoa"] == ["TS054"]
    assert ("TS054", "TYPE151") in calls


def test_fetch_csv_retries_empty_then_raises(monkeypatch):
    class R:
        text = ""
        url = "u"

        def raise_for_status(self):
            pass

    n = {"calls": 0}

    class S:
        def get(self, *a, **k):
            n["calls"] += 1
            return R()

    monkeypatch.setattr(nomis, "EMPTY_RETRY_WAITS", (0, 0))
    with pytest.raises(nomis.EmptyResponse):
        nomis.fetch_csv(S(), "NM_1_1", {})
    assert n["calls"] == 3


def test_bres_industry_shares_and_density():
    from whips.sources import nomis_extra
    rows = []
    for code, total, manuf, health in [("E1", 1000, 100, 200), ("E2", 500, None, 50)]:
        rows += [{"GEOGRAPHY_CODE": code, "INDUSTRY": 37748736, "value": total},
                 {"GEOGRAPHY_CODE": code, "INDUSTRY": 910, "value": manuf},
                 {"GEOGRAPHY_CODE": code, "INDUSTRY": 911, "value": 0},
                 {"GEOGRAPHY_CODE": code, "INDUSTRY": 986, "value": health}]
    df = pd.DataFrame(rows)
    out = nomis_extra.bres_frames(df, {10: "910", 11: "911", 86: "986"}, pd.Series({"E1": 2000.0, "E2": 250.0}))
    m = out["jobs_manufacturing"]
    assert (m["num"] / m["den"]).to_dict() == pytest.approx({"E1": 10.0, "E2": 0.0})
    h = out["jobs_health"]
    assert (h["num"] / h["den"]).to_dict() == pytest.approx({"E1": 20.0, "E2": 10.0})
    d = out["jobs_density"]
    assert (d["num"] / d["den"]).to_dict() == pytest.approx({"E1": 0.5, "E2": 2.0})
    assert "jobs_ict" not in out  # no divisions known for that group


def test_census_cache_only_reused_for_covered_patterns(tmp_path, monkeypatch):
    monkeypatch.setenv("WHIPS_CENSUS_CACHE", str(tmp_path))
    tidy = nomis.tidy_census(nomis_csv(TENURE_LABELS))
    nomis.store_table("TS054", tidy, [("^owned",)])
    assert nomis.cached_table("TS054", [("^owned",)]) is not None
    assert nomis.cached_table("TS054", [("^owned",), ("^social rented",)]) is None  # new pattern: refetch
    nomis.store_table("TS054", tidy, None)  # whole table covers anything
    got = nomis.cached_table("TS054", [("^social rented",)])
    assert got is not None and got["code"].iloc[0] == "E14001063" and len(got) == len(tidy)


def test_parse_api_results_matches_csv_shape():
    party = lambda a: {"abbreviation": a}  # noqa: E731
    results = {
        "E1": {"electorate": 1000, "majority": 100, "result": "LD Gain", "candidates": [
            {"party": party("LD"), "votes": 300, "rankOrder": 1},
            {"party": party("Con"), "votes": 200, "rankOrder": 2},
            {"party": party("Lab Co-op"), "votes": 60, "rankOrder": 3},
            {"party": party("Lab"), "votes": 40, "rankOrder": 4},
        ]},
    }
    metrics, attrs = parliament.parse_api_results(results)
    val = lambda mid: metrics[mid].loc["E1", "num"] / metrics[mid].loc["E1", "den"]  # noqa: E731
    assert val("majority_pct") == pytest.approx(100 / 600 * 100)
    assert val("turnout") == pytest.approx(60.0)
    assert val("vote_ld") == pytest.approx(50.0)
    assert val("vote_lab") == pytest.approx(100 / 600 * 100)  # Labour and Labour Co-op combined
    assert val("vote_snp") == 0
    assert attrs.loc["E1"].to_dict() == {"first_party": "LD", "second_party": "Con", "result": "LD Gain"}
