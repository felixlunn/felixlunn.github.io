import pandas as pd
import pytest

from whips.sources.green_space import seat_frames


def test_msoa_gardens_shared_across_lsoas_and_park_access():
    p = pd.DataFrame({"msoa": ["M1", "M1"], "postcodes": [10.0, 30.0], "near": [5.0, 3.0]}, index=["L1", "L2"])
    g = pd.DataFrame({"addresses": [200.0], "with_space": [150.0]}, index=["M1"])
    f = seat_frames(p, g, {"L1": "A", "L2": "B"})
    assert (f["no_garden"]["num"] / f["no_garden"]["den"]).to_dict() == pytest.approx({"A": 25.0, "B": 25.0})
    assert (f["park_within_300m"]["num"] / f["park_within_300m"]["den"]).to_dict() == pytest.approx({"A": 50.0, "B": 10.0})
