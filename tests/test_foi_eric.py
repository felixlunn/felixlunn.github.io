import gzip

import pandas as pd

from datadash.sources import foi_eric as fe


def returns(tmp_path, rows):
    cols = ["Year", "Trust Code", "Trust Name", "Trust Type", "Fires recorded (No.)", "Income from car parking - patients and visitors (£)",
            "Estates Development Strategy (Yes/No)", "Average occupancy (%)"]
    p = tmp_path / "eric.csv.gz"
    with gzip.open(p, "wt") as f:
        pd.DataFrame(rows, columns=cols).to_csv(f, index=False)
    return fe.load_returns(p)


def test_themes_cover_every_measure_and_lead_with_a_long_series():
    raw = pd.read_csv(fe.DATA, dtype=str, nrows=5)
    measures = [c for c in raw.columns if c not in fe.ID_COLUMNS and fe.split_unit(c)[1] not in fe.SKIP_UNITS]
    themes = {m: fe.theme_of(m)[0] for m in measures}
    assert themes["Income from car parking - patients and visitors (£)"] == "parking"
    assert themes["Fires recorded (No.)"] == "fire"
    assert themes["Capital investment for new build (£)"] == "capital"
    assert fe.theme_of("Percentage of clinical space monitored for temperatures (%)") == ("incidents", "higher_better")
    assert fe.split_unit("Energy managers (WTE)") == ("Energy managers", "WTE")


def test_merged_trusts_add_up_income_is_positive_and_answers_are_skipped(tmp_path):
    long = returns(tmp_path, [
        ["2018/19", "OLD", "OLD TRUST", "ACUTE", "2", "1,000", "Yes", "Not Applicable"],
        ["2018/19", "NEW", "NEW TRUST", "ACUTE", "3", "500", "Yes", "80"],
        ["2025/26", "NEW", "NEW TRUST", "ACUTE", "4", "-2000", "No", "No Data Provided"],
        ["2025/26", "GONE", "GONE TRUST", "ACUTE", "1", "-10", "No", ""],
    ])
    assert "Estates Development Strategy (Yes/No)" not in set(long["measure"])
    members = {"nhs_trust": {"NEW"} | {f"T{i}" for i in range(5)}, "mh_trust": set(), "ambulance_trust": set()}
    filler = pd.DataFrame([{"Year": "2025/26", "Trust Code": f"T{i}", "Trust Name": "T", "measure": "Fires recorded (No.)", "value": 1.0} for i in range(5)])
    sets, unmatched = fe.build_datasets(pd.concat([long, filler]), members, {"OLD": "NEW"}, {"NEW": "New Trust"}, "2026-11-27")
    assert unmatched == ["GONE TRUST"]
    by = {d["id"]: d for d in sets}
    fire = by["eric-fire-nhs_trust"]
    row = next(r for r in fire["rows"] if r["code"] == "NEW")
    keys = {c["period"]: c["key"] for c in fire["columns"]}
    assert row["values"][keys["2018/19"]] == 5 and row["values"][keys["2025/26"]] == 4  # OLD's 2 added to NEW's 3
    assert {c["series"] for c in fire["columns"]} == {"Fires recorded"} and fire["builtin"] == "ERIC"
    assert "eric-parking-nhs_trust" not in by  # only one trust has figures: too few to compare
    long2 = long[long["measure"].str.startswith("Income")]
    assert sorted(long2["value"]) == [10, 500, 1000, 2000]  # 2025/26's negatives made positive


def test_the_real_file_builds():
    long = fe.load_returns()
    assert set(long["Year"]) >= {"2016/17", "2025/26"}
    assert (long.loc[long["measure"].str.startswith("Income from car parking"), "value"] >= 0).mean() > 0.95
