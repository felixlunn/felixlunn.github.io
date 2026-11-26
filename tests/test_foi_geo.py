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


def test_closed_and_merged_trusts_left_out_with_their_names_kept():
    # ODS keeps merged trusts "Active": Hammersmith Hospitals (RQN) closed in 2007 and became Imperial (RYJ);
    # Basildon (RDD) merged into Mid and South Essex (RAJ) in 2020.
    rec = lambda end=None, succ=None: {"Date": [{"Type": "Operational", "Start": "1994-04-01"}, {"Type": "Legal", "Start": "1994-04-01", "End": end}],  # noqa: E731
                                       "Succs": {"Succ": [{"Type": "Successor", "Target": {"OrgId": {"extension": succ}}}] if succ else []}}
    trusts = [{"code": c, "name": n} for c, n in [("RQN", "Hammersmith Hospitals NHS Trust"), ("RYJ", "Imperial College Healthcare NHS Trust"),
                                                  ("RDD", "Basildon and Thurrock University Hospitals NHS Foundation Trust"),
                                                  ("RAJ", "Mid and South Essex NHS Foundation Trust"), ("XX1", "Old Trust"), ("XX2", "Middle Trust")]]
    records = {"RQN": rec("2007-09-30", "RYJ"), "RYJ": rec(), "RDD": rec("2020-03-31", "RAJ"), "RAJ": rec(),
               "XX1": rec("2010-03-31", "XX2"), "XX2": rec("2015-03-31", "RAJ")}  # closed twice over: ends up at RAJ
    out = {t["code"]: t for t in f.current_trusts(trusts, records, "2026-11-26")}
    assert sorted(out) == ["RAJ", "RYJ"]
    assert out["RYJ"]["aliases"] == ["Hammersmith Hospitals NHS Trust", "RQN"]
    assert set(out["RAJ"]["aliases"]) == {"Basildon and Thurrock University Hospitals NHS Foundation Trust", "RDD", "Old Trust", "XX1", "Middle Trust", "XX2"}
    assert f.closed(rec("2030-01-01"), "2026-11-26") == (False, None)  # a future legal end hasn't happened yet


def test_trust_kinds():
    assert f.trust_kind("East London NHS Foundation Trust") == "Mental health & community"
    assert f.trust_kind("Mersey Care NHS Foundation Trust") == "Mental health & community"
    assert f.trust_kind("Mid and South Essex NHS Foundation Trust", acute_catchment=True) == "Acute & specialist"
    assert f.trust_kind("Alder Hey Children's NHS Foundation Trust") == "Acute & specialist"
    assert f.trust_kind("Hull University Teaching Hospitals NHS Trust") == "Acute & specialist"
    assert f.trust_kind("North East Ambulance Service NHS Foundation Trust") == "Ambulance"
    assert f.trust_kind("Bridgewater Community Healthcare NHS Foundation Trust") == "Mental health & community"
    assert f.trust_kind("Central London Community Healthcare NHS Trust") == "Mental health & community"
    assert f.trust_kind("Hertfordshire Community NHS Trust") == "Community"
    assert f.trust_kind("Greater Manchester Mental Health NHS Foundation Trust") == "Mental health & community"  # not "chest"
    assert f.trust_kind("Liverpool Heart and Chest Hospital NHS Foundation Trust") == "Acute & specialist"


def test_catchments_filed_under_a_merged_trust_go_to_its_successor():
    from shapely.geometry import box
    from datadash.sources.foi_geo.assemble import catchments_of_current
    trusts = [{"code": "RAJ", "name": "Mid and South Essex", "aliases": ["Basildon and Thurrock", "RDD"]}, {"code": "RYJ", "name": "Imperial"}]
    catch = [{"code": "RAJ", "name": "x", "geometry": box(0, 0, 1, 1)}, {"code": "RDD", "name": "old", "geometry": box(1, 0, 2, 1)},
             {"code": "RYJ", "name": "y", "geometry": box(5, 5, 6, 6)}, {"code": "ZZZ", "name": "gone", "geometry": box(9, 9, 10, 10)}]
    out = {c["code"]: c for c in catchments_of_current(catch, trusts)}
    assert sorted(out) == ["RAJ", "RYJ"] and out["RAJ"]["geometry"].area == 2.0 and out["RAJ"]["name"] == "Mid and South Essex"


def test_map_shapes_stay_valid_after_simplifying():
    from shapely.geometry import Polygon, shape as to_shape
    from datadash.sources.foi_geo.assemble import to_feature
    # A thin shape whose simplified, rounded outline would cross itself.
    zig = Polygon([(0, 0), (0.01, 0.00002), (0.02, 0), (0.02, 0.00003), (0.01, 0.00001), (0, 0.00003)])
    g = to_shape(to_feature({"code": "X", "name": "X", "geometry": zig.buffer(0.0001)}, "trust")["geometry"])
    assert g.is_valid
