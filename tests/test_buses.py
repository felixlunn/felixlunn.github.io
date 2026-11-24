import pandas as pd
import pytest

from datadash.sources.buses import authority_weights, journeys_per_head, miles_change


def test_miles_change_uses_totals_since_2010():
    rows = [["Table"], ["LA Code", "Local Authority", "Service type", "2010", "2024", "2025", "Notes"],
            ["E92000001", "England", "Total", "100", "90", "80", ""],
            ["E10000006", "Cumbria", "Commercial", "10", "5", "5", ""],
            ["E10000006", "Cumbria", "Total", "20", "15", "15", ""],
            ["E06000001", "Hartlepool", "Total", "[x]", "1", "1", ""]]
    change, nat, year = miles_change(pd.DataFrame(rows))
    assert year == "2025" and nat == pytest.approx(-20.0)
    assert change.to_dict() == pytest.approx({"E10000006": -25.0})


def test_the_november_2026_layout():
    # DfT renamed the headers and added combined authority (E47) rows; many councils are still listed too.
    miles = [["Table BUS02d_mi"], ["Million"],
             ["Area code", "Area name [note 4] [note 7]", "Included in LTA breakdown? [note 9]", "Service type [note 3]", "2010", "2025", "2026", "Notes"],
             ["E92000001", "England", "[z]", "Total", "100", "85", "80", "[z]"],
             ["E47000014", "North East MSA", "Yes", "Total", "70", "62", "60", ""],
             ["E06000047", "County Durham", "No", "Commercial", "10", "9", "9", ""],
             ["E06000047", "County Durham", "No", "Total", "20", "15", "14", ""],
             ["E12000007", "London", "Yes", "Publicly controlled", "300", "290", "280", ""],
             ["E12000007", "London", "Yes", "Total", "300", "290", "280", ""]]
    change, nat, year = miles_change(pd.DataFrame(miles))
    assert year == "2026" and nat == pytest.approx(-20.0)
    # Combined authority (E47) rows are kept: some areas (e.g. West Midlands) are only reported that way now.
    assert change.to_dict() == pytest.approx({"E47000014": -14.2857, "E06000047": -30.0, "E12000007": -6.6667}, rel=1e-3)
    journeys = [["Table BUS01f"], ["Passenger journeys per head"],
                ["Area code", "Area name [note 6]", "Included in LTA breakdown? [note 9]", "2010", "2025", "2026", "Notes"],
                ["E92000001", "England", "[z]", "88.4", "62.7", "60.7", "[r]"],
                ["E47000014", "North East MSA", "Yes", "70", "50", "49", ""],
                ["E06000047", "County Durham", "No", "40", "30", "29", ""]]
    per_head, england, year = journeys_per_head(pd.DataFrame(journeys))
    assert year == "2026" and england == pytest.approx(60.7) and per_head.to_dict() == {"E47000014": 49.0, "E06000047": 29.0}


def test_authority_weights_group_london_counties_and_new_unitaries():
    w = pd.DataFrame({"pcon": ["A", "A", "B", "C"], "lad": ["E09000001", "E09000002", "E07000001", "E06000064"],
                      "n": [1, 1, 2, 3]})
    out = authority_weights(w, {"E07000001": "E10000001"}, {}, {"E12000007", "E10000001", "E10000006"})
    assert set(zip(out["pcon"], out["lad"], out["n"])) == {("A", "E12000007", 2), ("B", "E10000001", 2), ("C", "E10000006", 3)}


def test_each_council_takes_the_authority_the_table_lists():
    w = pd.DataFrame({"pcon": ["A", "B", "C", "D"], "lad": ["E08000025", "E08000038", "E06000066", "E06000047"], "n": [1, 1, 1, 1]})
    county = {"E08000025": "E11000005", "E08000038": "E11000003"}
    cauth = {"E08000025": "E47000007", "E08000038": "E47000002", "E06000047": "E47000014"}
    # Birmingham: no West Midlands county row, so the combined authority; Barnsley likewise; Somerset now listed itself
    # (not its former county); County Durham listed itself, so not its combined authority.
    listed = {"E47000007", "E47000002", "E06000066", "E10000027", "E06000047", "E47000014"}
    out = authority_weights(w, county, cauth, listed)
    assert dict(zip(out["pcon"], out["lad"])) == {"A": "E47000007", "B": "E47000002", "C": "E06000066", "D": "E06000047"}
