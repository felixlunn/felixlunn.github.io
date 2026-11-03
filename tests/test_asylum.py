import pandas as pd
import pytest

from whips.sources.asylum import counts, seat_frames


def test_asylum_rates_per_10k():
    sheet = pd.DataFrame([["Reg_02"], ["Local authority", "Region / Nation", "LTLA (ONS code)", "Homes for Ukraine - not including super sponsors (arrivals)",
                                       "Supported Asylum (total) (population)", "of which, Supported Asylum - Contingency Accommodation (population)", "Population"],
                          ["A", "NW", "E06000001", "10", "40", "20", "20000"], ["North West", "", "E12000002", "1", "1", "1", "1"]])
    c = counts(sheet)
    assert list(c.index) == ["E06000001"]
    w = pd.DataFrame({"pcon": ["S1"], "lad": ["E06000001"], "of_council": [1.0]})
    f = seat_frames(c, w)
    assert (f["asylum_supported_per_10k"]["num"] / f["asylum_supported_per_10k"]["den"]).loc["S1"] == pytest.approx(20.0)
    assert (f["asylum_contingency_per_10k"]["num"] / f["asylum_contingency_per_10k"]["den"]).loc["S1"] == pytest.approx(10.0)
