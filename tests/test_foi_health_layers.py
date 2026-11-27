from collections import Counter

from shapely.geometry import box

from datadash.sources.foi_geo import health_layers as hl

TRUSTS = [
    {"code": "RWK", "name": "East London NHS Foundation Trust"},
    {"code": "RW1", "name": "Hampshire and Isle of Wight Healthcare NHS Foundation Trust"},
    {"code": "RW4", "name": "Mersey Care NHS Foundation Trust", "aliases": ["North West Boroughs Healthcare NHS Foundation Trust", "RTV"]},
    {"code": "RX9", "name": "East Midlands Ambulance Service NHS Trust"},
    {"code": "R1F", "name": "Isle of Wight NHS Trust"},
    {"code": "RYJ", "name": "Imperial College Healthcare NHS Trust"},
    {"code": "RXT", "name": "Birmingham and Solihull Mental Health NHS Foundation Trust"},
]


def test_list_names_matched_to_current_trusts():
    lists = {"hospital": ["Imperial College Healthcare NHS Trust", "Isle Of Wight NHS Trust"],
             "mental_health": ["East London NHS Foundation Trust", "Southern Health NHS Foundation Trust",
                               "North West Boroughs Healthcare NHS Foundation Trust", "Nowhere Partnership NHS Trust"],
             "ambulance": ["East Midlands Ambulance Service NHS Trust", "Isle of Wight NHS Trust"],
             "renamed": {"Southern Health NHS Foundation Trust": "RW1"}}
    groups, missing = hl.resolve_groups(TRUSTS, lists)
    assert groups["RWK"] == {"mental_health"} and groups["RW1"] == {"mental_health"}  # renamed
    assert groups["RW4"] == {"mental_health"}  # by a former name
    assert groups["R1F"] == {"hospital", "ambulance"}  # on two lists, on both layers
    assert missing == [("mental_health", "Nowhere Partnership NHS Trust")]


def test_trusts_on_no_list_go_on_the_trusts_layer():
    out = hl.trust_groups(TRUSTS, {"RXT": "Mental health & community", "RX9": "Ambulance", "RYJ": "Acute & specialist"},
                          {"hospital": [], "mental_health": [], "ambulance": []})
    assert out["RX9"] == ["ambulance"] and out["RYJ"] == ["hospital"]
    assert out["RXT"] == ["hospital"]  # only the list puts trusts on the mental health layer


def test_ambulance_services_by_region_and_county():
    k = hl.ambulance_key
    assert k("E06000046", "E12000008", None) == "isle of wight"
    assert k("E07000110", "E12000008", "E10000016") == "south east coast"  # Maidstone, Kent
    assert k("E06000043", "E12000008", None) == "south east coast"  # Brighton and Hove
    assert k("E06000045", "E12000008", None) == "south central"  # Southampton
    assert k("E06000013", "E12000003", None) == "east midlands"  # North Lincolnshire: from the East Midlands
    assert k("E08000035", "E12000003", None) == "yorkshire"  # Leeds
    assert k("W06000015", None, None) == "W" and k("S12000036", None, None) == "S" and k("N09000003", None, None) == "N"


def test_ambulance_areas_named_after_their_trusts():
    lads = [{"code": "E06000046", "name": "Isle of Wight", "geometry": box(0, 0, 1, 1)},
            {"code": "E06000016", "name": "Leicester", "geometry": box(5, 5, 6, 6)},
            {"code": "W06000015", "name": "Cardiff", "geometry": box(-5, 0, -4, 1)}]
    regions = [{"code": "E12000004", "name": "East Midlands", "geometry": box(4, 4, 7, 7)}]
    owner, names = hl.ambulance_owners(lads, regions, {}, TRUSTS)
    assert owner == {"E06000046": "R1F", "E06000016": "RX9", "W06000015": "W-AMB"}
    assert names["W-AMB"].startswith("Welsh Ambulance")


def test_mental_health_councils_go_to_the_trust_with_most_sites():
    # A row of five councils: trust X runs sites in 1-2, Y in 4-5 (and one in 2); council 3 has none and borders both.
    lads = [{"code": f"E0600000{i}", "name": str(i), "geometry": box(i, 0, i + 1, 1 if i != 3 else 0.5)} for i in range(1, 6)]
    counts = {"X": Counter({"E06000001": 5, "E06000002": 3}), "Y": Counter({"E06000002": 1, "E06000004": 4, "E06000005": 2})}
    owner = hl.mh_owners(lads, counts, fixed={})
    assert owner["E06000001"] == "X" and owner["E06000002"] == "X" and owner["E06000004"] == "Y"
    assert owner["E06000003"] in ("X", "Y")  # filled from a neighbour
    areas = {a["code"]: a for a in hl.areas_from_councils(owner, lads, {"X": "Trust X", "Y": "Trust Y"})}
    assert areas["X"]["name"] == "Trust X" and areas["X"]["geometry"].area >= 2


def test_isle_of_wight_ambulance_is_the_isle_of_wight_trust():
    trusts = TRUSTS + [{"code": "RW1x", "name": "Hampshire and Isle of Wight Healthcare NHS Foundation Trust"}]
    lads = [{"code": "E06000046", "name": "Isle of Wight", "geometry": box(0, 0, 1, 1)}]
    owner, _ = hl.ambulance_owners(lads, [], {}, trusts)
    assert owner == {"E06000046": "R1F"}


def test_a_council_can_be_set_by_hand():
    lads = [{"code": "E06000021", "name": "Stoke-on-Trent", "geometry": box(0, 0, 1, 1)}]
    counts = {"RRE": Counter({"E06000021": 9}), "RLY": Counter({"E06000021": 4})}
    assert hl.mh_owners(lads, counts) == {"E06000021": "RLY"}  # from trust_groups.json: most sites isn't always right
