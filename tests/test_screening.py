import pandas as pd
import pytest

from whips.sources import nhs


def test_screening_indicators_become_seat_rates():
    rows = pd.DataFrame({"Indicator ID": [92600, 92600, 93717], "Area Code": ["P1", "P2", "P1"],
                         "Count": [70.0, 80.0, 60.0], "Denominator": [100.0, 100.0, 100.0]})
    f = nhs.seat_frames(rows, {"P1": "A", "P2": "A"})
    assert (f["screen_bowel"]["num"] / f["screen_bowel"]["den"]).loc["A"] == pytest.approx(75.0)
    assert (f["screen_cervical"]["num"] / f["screen_cervical"]["den"]).loc["A"] == pytest.approx(60.0)
    assert {"screen_bowel", "screen_cervical", "screen_cervical_50"} <= {m.id for m in nhs.NHS_METRICS}
