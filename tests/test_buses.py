import pandas as pd
import pytest

from whips.sources.buses import authority_weights, miles_change


def test_miles_change_uses_totals_since_2010():
    rows = [["Table"], ["LA Code", "Local Authority", "Service type", "2010", "2024", "2025", "Notes"],
            ["E92000001", "England", "Total", "100", "90", "80", ""],
            ["E10000006", "Cumbria", "Commercial", "10", "5", "5", ""],
            ["E10000006", "Cumbria", "Total", "20", "15", "15", ""],
            ["E06000001", "Hartlepool", "Total", "[x]", "1", "1", ""]]
    change, nat, year = miles_change(pd.DataFrame(rows))
    assert year == "2025" and nat == pytest.approx(-20.0)
    assert change.to_dict() == pytest.approx({"E10000006": -25.0})


def test_authority_weights_group_london_counties_and_new_unitaries():
    w = pd.DataFrame({"pcon": ["A", "A", "B", "C"], "lad": ["E09000001", "E09000002", "E07000001", "E06000064"],
                      "n": [1, 1, 2, 3]})
    out = authority_weights(w, {"E07000001": "E10000001"})
    assert set(zip(out["pcon"], out["lad"], out["n"])) == {("A", "E12000007", 2), ("B", "E10000001", 2), ("C", "E10000006", 3)}
