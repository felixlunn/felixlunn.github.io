import pandas as pd
import pytest

from whips.sources.ofsted import seat_frames


def test_pupil_weighted_good_share_and_concerns():
    d = pd.DataFrame({"Parliamentary constituency": ["Seat A", "Seat A", "Seat A", "Seat B"],
                      "Total number of pupils": [300, 100, 50, 200],
                      "Latest OEIF overall effectiveness": ["2", "4", "Not judged", None],
                      "Most recent category of concern": [None, "SM", None, None]})
    f = seat_frames(d, {"seat a": "E14000001", "seat b": "E14000002"})
    good = f["ofsted_good_pupils"]
    assert (good["num"] / good["den"]).loc["E14000001"] == pytest.approx(75.0)
    assert pd.isna((good["num"] / good["den"]).loc["E14000002"])  # no graded school: no data, not 0%
    assert f["ofsted_concern_schools"]["num"].to_dict() == {"E14000001": 1, "E14000002": 0}
