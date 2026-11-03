import pandas as pd
import pytest

from whips.sources.child_poverty import seat_table


def test_seat_table_uses_latest_year():
    rows = [["Table 3"], [None],
            ["Westminster Parliamentary Constituency [note 2]", "Area Code", "Number of children\nFYE 2024",
             "Number of children\nFYE 2025", "Percentage of children\nFYE 2024\n(%)", "Percentage of children\nFYE 2025\n(%)"],
            ["United Kingdom", "K02000001", "300", "260", "0.30", "0.26"],
            ["Seat A", "E14000001", "100", "200", "0.1", "0.25"],
            ["Seat B", "W07000002", "50", "0", "0.1", "0"]]
    frame, uk, year = seat_table(pd.DataFrame(rows))
    assert year == "FYE 2025" and uk == pytest.approx(26.0)
    assert (frame["num"] / frame["den"]).to_dict() == pytest.approx({"E14000001": 25.0})  # zero share dropped
    assert frame["den"].loc["E14000001"] == pytest.approx(800)
