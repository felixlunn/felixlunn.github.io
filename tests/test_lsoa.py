import pandas as pd

from whips.sources import lsoa


def test_service_discovery_prefers_generalised_boundaries_and_latest_wards():
    names = ["Lower_layer_Super_Output_Areas_December_2021_Boundaries_EW_BFC_V10",
             "Lower_layer_Super_Output_Areas_December_2021_Boundaries_EW_BSC_V4",
             "Lower_layer_Super_Output_Areas_December_2021_Boundaries_EW_BGC_V5",
             "LSOA21_WD24_LAD24_EW_LU", "LSOA21_WD26_LAD26_EW_LU", "LSOA21_WD25_LAD25_EW_LU_v2"]
    assert lsoa.find_boundary_service(names).endswith("Lower_layer_Super_Output_Areas_December_2021_Boundaries_EW_BGC_V5/FeatureServer/0")
    assert "LSOA21_WD26_LAD26_EW_LU" in lsoa.find_ward_service(names)


def test_seat_file_values_percentiles_and_order():
    frames = {
        "private_rented": pd.DataFrame({"num": [10.0, 20.0, 30.0, 40.0], "den": [100.0, 100.0, 100.0, 100.0]},
                                       index=["A1", "A2", "B1", "B2"]),
        "empty_here": pd.DataFrame({"num": [None, None, 5.0, 6.0], "den": [1.0, 1.0, 1.0, 1.0]}, index=["A1", "A2", "B1", "B2"]),
    }
    vals, pct = lsoa.metric_values(frames)
    wards = {"A1": {"name": "Seat 001A", "ward": "Zed", "council": "C"}, "A2": {"name": "Seat 001B", "ward": "Alpha", "council": "C"}}
    geoms = {"A1": {"type": "Point", "coordinates": [0, 0]}}
    doc = lsoa.seat_file("E1", "Seat", ["A1", "A2"], vals, pct, wards, geoms)
    assert [l["code"] for l in doc["lsoas"]] == ["A2", "A1"]  # ordered by ward name
    assert doc["metrics"] == ["private_rented"]  # metrics with no data in this seat are left out
    assert doc["values"]["private_rented"] == [0.2, 0.1]
    assert doc["pct"]["private_rented"] == [50, 25]  # ranked against every LSOA, not just this seat's
    assert [f["properties"]["code"] for f in doc["geo"]["features"]] == ["A1"]
