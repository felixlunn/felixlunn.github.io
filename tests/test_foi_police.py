import pandas as pd

from datadash.sources import foi_police as fp

def test_crime_shared_out_to_force_areas():
    seats = ["A", "B"]
    frames = {"crime_rate": pd.DataFrame({"num": [1000 * 1000.0, 400 * 1000.0], "den": [70_000.0, 70_000.0]}, index=seats),
              "crime_burglary": pd.DataFrame({"num": [100 * 1000.0, 40 * 1000.0], "den": [70_000.0, 70_000.0]}, index=seats),
              "outcome_no_suspect": pd.DataFrame({"num": [50 * 100.0, 20 * 100.0], "den": [100.0, 100.0]}, index=seats)}
    # Area X covers all of A and half of B; Y the other half of B.
    areas = [{"code": "X", "name": "X", "seats": [["A", 1.0], ["B", 0.5]]}, {"code": "Y", "name": "Y", "seats": [["B", 0.5]]}]
    areas += [{"code": f"Z{i}", "name": "Z", "seats": [["A", 0.01]]} for i in range(30)]  # enough areas to count as complete
    d = fp.crime_dataset(frames, areas, "2026-07 to 2026-09", "2026-11-24")
    rows = {r["code"]: r["values"] for r in d["rows"]}
    assert rows["X"]["crime_rate"] == 1200 and rows["Y"]["crime_rate"] == 200 and rows["X"]["crime_burglary"] == 120
    assert rows["X"]["outcome_no_suspect"] == 40.0  # (50 + 10) / (100 + 50)
    assert d["builtin"] == "police.uk" and d["geography"] == "police_force" and d["id"] == "police-uk-crime"
    assert fp.crime_dataset({}, areas, None, "2026-11-24") is None  # no seat figures in this build


def test_missing_categories_keep_their_own_columns():
    frames = {"crime_rate": pd.DataFrame({"num": [1000.0], "den": [1.0]}, index=["A"]),
              "crime_drugs": pd.DataFrame({"num": [2000.0], "den": [1.0]}, index=["A"])}
    areas = [{"code": f"X{i}", "name": "X", "seats": [["A", 1.0]]} for i in range(30)]
    d = fp.crime_dataset(frames, areas, None, "2026-11-24")
    assert [c["key"] for c in d["columns"]] == ["crime_rate", "crime_drugs"]
    assert d["rows"][0]["values"] == {"crime_rate": 1, "crime_drugs": 2}
