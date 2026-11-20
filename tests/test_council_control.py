import pandas as pd

from whips.sources import council_control as cc


def members(parties):
    return pd.DataFrame({"Party Name": parties, "Next Election": ["2027-05-06"] * len(parties)})


def test_control_needs_over_half_of_filled_seats():
    out = cc.control(members(["Liberal Democrats"] * 6 + ["Labour Party"] * 4 + ["Vacant"]))
    assert out["control"] == "Liberal Democrat" and out["largest_seats"] == 6 and out["seats"] == 11
    assert out["next_election"] == "2027-05-06"
    assert cc.control(members(["Liberal Democrats"] * 5 + ["Labour Party"] * 5))["control"] == "No overall control"
    assert cc.control(members(["Independent / Other"] * 7 + ["Labour Party"] * 3))["control"] == "Independents"


def test_council_names_match_ons_names():
    assert cc.norm("Herefordshire, County of") == cc.norm("Herefordshire")
    assert cc.norm("County Durham") == cc.norm("Durham")
    assert cc.norm("City of Edinburgh") == cc.norm("Edinburgh")
    assert cc.norm("Brighton & Hove") == cc.norm("Brighton and Hove")


def test_seats_get_their_councils_and_county():
    weights = pd.DataFrame({"pcon": ["S1", "S1", "S2"], "lad": ["E07000001", "E07000002", "E06000001"],
                            "of_seat": [0.95, 0.05, 1.0]})
    links = cc.seat_councils(weights, {"E07000001": "E10000001", "E07000002": "E10000001"})
    names = {"E07000001": "Northtown", "E07000002": "Southtown", "E10000001": "Shire", "E06000001": "Unitaryshire"}
    info = lambda n: {"name": n, "control": {"control": "Labour", "largest": "Labour", "largest_seats": 3, "seats": 5,  # noqa: E731
                                            "parties": {}, "next_election": None}}
    out = cc.by_seat(links, names, {cc.norm(n): info(n) for n in names.values()})
    assert [(c["name"], c["tier"]) for c in out["S1"]] == [("Northtown", "council"), ("Shire", "county")]  # Southtown < 10%
    assert [c["name"] for c in out["S2"]] == ["Unitaryshire"]
