import pandas as pd

from whips.sources import lsoa


def test_service_discovery_prefers_detailed_clipped_boundaries_and_latest_wards():
    names = ["Lower_layer_Super_Output_Areas_December_2021_Boundaries_EW_BFC_V10",
             "Lower_layer_Super_Output_Areas_December_2021_Boundaries_EW_BSC_V4",
             "Lower_layer_Super_Output_Areas_December_2021_Boundaries_EW_BGC_V5",
             "LSOA21_WD24_LAD24_EW_LU", "LSOA21_WD26_LAD26_EW_LU", "LSOA21_WD25_LAD25_EW_LU_v2"]
    assert lsoa.find_boundary_services(names) == ("Lower_layer_Super_Output_Areas_December_2021_Boundaries_EW_BFC_V10", None)
    assert lsoa.find_boundary_services(names[1:]) == ("Lower_layer_Super_Output_Areas_December_2021_Boundaries_EW_BGC_V5", None)
    assert "LSOA21_WD26_LAD26_EW_LU" in lsoa.find_ward_service(names)


def test_boundary_service_found_under_its_new_short_name():
    # ONS renamed the layers in 2026 and withdrew BFC/BGC: draw full resolution (BFE), trimmed with the coarse layer.
    names = ["LSOA_2021_EW_BFE_V10_RUC", "LSOA_2021_EW_BSC_V4_RUC", "LSOA21_WD26_LAD26_EW_LU"]
    assert lsoa.find_boundary_services(names) == ("LSOA_2021_EW_BFE_V10_RUC", "LSOA_2021_EW_BSC_V4_RUC")
    assert lsoa.find_boundary_services(["LSOA_2021_EW_BSC_V4_RUC"]) == ("LSOA_2021_EW_BSC_V4_RUC", None)


def test_trim_to_coast_removes_tidal_flats_but_keeps_inland_edges():
    from shapely.geometry import box
    detail = box(0, 0, 1, 1)  # full extent: reaches out over the sands to x=1
    coarse = box(0, 0, 0.5, 1)  # clipped at the coast, x=0.5
    trimmed = lsoa.trim_to_coast(detail, coarse)
    assert abs(trimmed.bounds[2] - (0.5 + lsoa.COAST_MARGIN)) < 1e-9
    assert trimmed.bounds[0] == 0 and trimmed.bounds[1] == 0
    assert lsoa.trim_to_coast(detail, None) is detail


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
