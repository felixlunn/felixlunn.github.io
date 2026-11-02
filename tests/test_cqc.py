import pandas as pd
import pytest

from whips.sources.cqc import seat_frames


def test_poor_rating_shares_and_beds():
    t = pd.DataFrame({
        "Dormant (Y/N)": ["N", "N", "N", "Y", "N", "N"],
        "Care home?": ["Y", "Y", "Y", "Y", "N", "N"],
        "Care homes beds": ["40", "20", "10", "99", "0", "0"],
        "Location Primary Inspection Category": ["Residential social care"] * 4 + ["GP Practices"] * 2,
        "Location Latest Overall Rating": ["Good", "Inadequate", "Not Rated", "Inadequate", "Requires improvement", "Outstanding"],
    })
    seat = pd.Series(["E14000001"] * 6)
    f = seat_frames(t, seat, pd.Series({"E14000001": 1000.0, "E14000002": 500.0}), ["E14000001", "E14000002", "S14000001"])
    rate = lambda k: (f[k]["num"] / f[k]["den"])  # noqa: E731
    assert rate("care_homes_poor").loc["E14000001"] == pytest.approx(50.0)  # unrated and dormant left out
    assert pd.isna(rate("care_homes_poor").loc["E14000002"])
    assert rate("gp_practices_poor").loc["E14000001"] == pytest.approx(50.0)
    assert rate("care_home_beds_per_1k_65").to_dict() == pytest.approx({"E14000001": 70.0, "E14000002": 0.0})
