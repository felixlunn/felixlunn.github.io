import pandas as pd
import pytest

from whips.sources import councils, housing


def weights():
    # Seat A: 3 LSOAs in council X; seat B: 1 LSOA in X and 2 in Y.
    lsoa_pcon = {"l1": "A", "l2": "A", "l3": "A", "l4": "B", "l5": "B", "l6": "B"}
    lsoa_lad = {"l1": "X", "l2": "X", "l3": "X", "l4": "X", "l5": "Y", "l6": "Y"}
    return councils.seat_council_weights(lsoa_pcon, lsoa_lad)


def test_apportion_counts_and_average_rates():
    w = weights()
    counts = councils.apportion(pd.Series({"X": 400.0, "Y": 100.0}), w)
    assert counts.to_dict() == pytest.approx({"A": 300.0, "B": 200.0})  # X split 3:1, all of Y to B
    rate = councils.averaged(pd.Series({"X": 10.0, "Y": 4.0}), w)
    assert (rate["num"] / rate["den"]).to_dict() == pytest.approx({"A": 10.0, "B": 6.0})  # B: (10 + 2*4) / 3


def test_homeless_counts_keep_councils_only():
    def sheet(cols, rows):
        return pd.DataFrame([["Table"] + [None] * (len(cols) - 1), cols, *rows])
    sheets = {
        "TA1": sheet(["Organisation Identification Code", "Area Name", "Households in TA\n\nTotal", "Households in area\n\n(thousands)"],
                     [["E92000001", "ENGLAND", "500", "100"], ["E06000001", "X", "40", "10"], ["E07000002", "Y", "[x]", "5"]]),
        "A1": sheet(["Organisation Identification Code", "Area Name", "Assessed as owed a duty\n\nOwed a prevention or relief duty\n\nTotal"],
                    [["E92000001", "ENGLAND", "300"], ["E06000001", "X", "30"], ["E07000002", "Y", "12"]]),
    }
    c = housing.homeless_counts(sheets)
    assert list(c.index) == ["E06000001", "E07000002"]
    assert c.loc["E06000001"].tolist() == [40, 10_000, 30]
    assert pd.isna(c.loc["E07000002", "ta"]) and c.loc["E07000002", "owed"] == 12
