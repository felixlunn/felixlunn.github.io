import numpy as np
from shapely.geometry import box

from datadash.demo import build_demo  # noqa: F401 - imported for the demo FOI check below
from datadash.sources import foi_geo as f


def square(code, x0, y0, x1, y1):
    return {"type": "Feature", "properties": {"code": code, "name": code},
            "geometry": {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}}


GEO = {"type": "FeatureCollection", "features": [square("E1", 0, 0, 1, 1), square("E2", 1, 0, 2, 1), square("S1", 0, 1, 2, 2)]}


def test_pick_service_prefers_latest_year_then_ultra_generalised():
    names = ["Police_Force_Areas_Dec_2023_EW_BGC", "Police_Force_Areas_Dec_2024_EW_BGC", "Police_Force_Areas_Dec_2024_EW_BUC", "PFA_DEC_2025_UK_NC"]
    assert f.pick_service(names, f.LAYERS["police"][0]) == "Police_Force_Areas_Dec_2024_EW_BUC"
    icb = ["Integrated_Care_Boards_April_2023_EN_BSC", "Integrated_Care_Boards_April_2026_Boundaries_EN_BSC", "ICB_APR_2026_EN_NC"]
    assert f.pick_service(icb, f.LAYERS["icb"][0]) == "Integrated_Care_Boards_April_2026_Boundaries_EN_BSC"


def test_names_and_kinds():
    assert f.title_name("THE NEWCASTLE UPON TYNE HOSPITALS NHS FOUNDATION TRUST") == "The Newcastle upon Tyne Hospitals NHS Foundation Trust"
    assert f.title_name("BIRMINGHAM AND SOLIHULL MENTAL HEALTH NHS FOUNDATION TRUST") == "Birmingham and Solihull Mental Health NHS Foundation Trust"
    assert f.title_name("ST GEORGE'S UNIVERSITY HOSPITALS NHS FOUNDATION TRUST").startswith("St George's")
    assert f.trust_kind("North West Ambulance Service NHS Trust") == "Ambulance"
    assert f.trust_kind("Avon and Wiltshire Mental Health Partnership NHS Trust") == "Mental health & community"
    assert f.trust_kind("Royal United Hospitals Bath NHS Foundation Trust") == "Acute & specialist"
    assert "Metropolitan Police Service" in f.police_aliases("Metropolitan Police")
    assert "Kent Police" in f.police_aliases("Kent")


def test_assemble_links_areas_and_points_to_seats():
    police = [{"code": "P1", "name": "West", "geometry": box(0, 0, 1, 2)}, {"code": "P2", "name": "East", "geometry": box(1, 0, 2, 2)}]
    health = [{"code": "H1", "name": "All", "geometry": box(0, 0, 2, 2)}]
    courts = [{"id": "c1", "name": "West Crown Court", "types": ["Crown Court"], "lat": 0.5, "lon": 0.5, "codes": []}]
    trusts = [{"code": "T1", "name": "East Trust", "postcode": "", "kind": "Acute & specialist", "lat": 0.5, "lon": 1.5}]
    seats = [{"code": c, "name": c} for c in ("E1", "E2", "S1")]
    ref, areas = f.assemble(GEO, seats, {"E1": 100, "E2": 100, "S1": 200}, police, health, courts, trusts, "2026-11-20")
    west = next(a for a in ref["layers"]["police"]["areas"] if a["code"] == "P1")
    assert dict(map(tuple, west["seats"])) == {"E1": 1.0, "S1": 0.5}
    assert west["population"] == 200  # all of E1 and half of S1
    assert ref["points"]["courts"][0] | {"area": "P1", "seat": "E1"} == ref["points"]["courts"][0]
    assert ref["points"]["trusts"][0]["seat"] == "E2" and ref["points"]["trusts"][0]["area"] == "H1"
    assert {ft["properties"]["layer"] for ft in areas["features"]} == {"police", "health", "land"}


def test_demo_reference_is_complete():
    from datadash.demo import _hex
    geo = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"code": f"D{i}", "name": f"D{i}"}, "geometry": {"type": "Polygon", "coordinates": [_hex(i % 10 * 0.3, i // 10 * 0.3, 0.09)]}}
        for i in range(60)]}
    seats = [{"code": f"D{i}", "name": f"D{i}"} for i in range(60)]
    ref, areas = f.demo_reference(geo, seats, {s["code"]: 1000 for s in seats}, np.random.default_rng(0))
    assert ref["layers"]["police"]["areas"] and ref["layers"]["health"]["areas"]
    assert all(c["seat"] for c in ref["points"]["courts"])
    layers = [ft["properties"]["layer"] for ft in areas["features"]]
    assert layers.count("police") == len(ref["layers"]["police"]["areas"]) and layers.count("land") >= 1
    with_catchment = [t for t in ref["points"]["trusts"] if t.get("catchment")]
    assert with_catchment and layers.count("trust") == len(with_catchment)


def test_catchments_from_first_past_the_post_rows():
    import pandas as pd
    sheet = pd.DataFrame([
        ["Table 2: Patients admitted by MSOA", None, None, None, None, None],
        ["Catchment\nyear", "Trust\ncode", "Trust\nname", "MSOA21CD", "Patients\nadmitted", "First past\nthe post (FPTP)"],
        ["2023", "RA1", "Old Trust", "E02000001", "500", "TRUE"],
        ["2024", "RA1", "West Trust", "E02000001", "400", "TRUE"],
        ["2024", "RB2", "East Trust", "E02000001", "100", "FALSE"],
        ["2024", "RB2", "East Trust", "E02000002", "300", "TRUE"],
        ["2024", "RB2", "East Trust", "E02000003", "300", "TRUE"],
    ])
    fptp = f.parse_fptp(sheet)
    assert sorted(map(tuple, fptp.values.tolist())) == [("RA1", "West Trust", "E02000001"), ("RB2", "East Trust", "E02000002"), ("RB2", "East Trust", "E02000003")]
    shapes = {"E02000001": box(0, 0, 1, 1), "E02000002": box(1, 0, 2, 1), "E02000003": box(2, 0, 3, 1)}
    areas = {a["code"]: a for a in f.catchment_areas(fptp, shapes)}
    assert abs(areas["RB2"]["geometry"].area - 2) < 1e-6 and areas["RA1"]["geometry"].bounds == (0, 0, 1, 1)
