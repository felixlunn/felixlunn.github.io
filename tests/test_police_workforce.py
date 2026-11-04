import pandas as pd
import pytest

from whips.sources.police_workforce import by_force, seat_frames


def test_force_rates_grouped_like_court_areas():
    sheet = pd.DataFrame([["Table H4"], ["PFA code", "Police Force Area", "Total officers (FTE)", "Total officers per 100,000 population"],
                          ["E23000001", "Metropolitan Police", "30000", "300"], ["E23000034", "London, City of", "1000", "1000"],
                          ["W15000002", "Gwent", "1500", "250"], ["K04000001", "England and Wales", "145000", "236"]])
    forces, national = by_force(sheet)
    assert national == 236 and set(forces.index) == {"london", "south wales"}
    f = seat_frames(forces, {"E14000001": "london", "E14000002": "nowhere"}, pd.Series({"E14000001": 100.0, "E14000002": 50.0}))
    rate = (f["num"] / f["den"])
    assert rate.loc["E14000001"] == pytest.approx(31000 * 100_000 / (10_000_000 + 100_000))
    assert pd.isna(rate.loc["E14000002"])
