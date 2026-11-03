import pandas as pd
import pytest

from whips.sources.travel import seat_frame, times


def test_times_weighted_by_service_population():
    sheet = pd.DataFrame([["Table"], ["GP005", "GP001"], ["LSOA_code", "Region", "GP_pop", "GPPTt", "GPPT15n"],
                          ["E01", "L", "100", "10", "1"], ["E02", "L", "300", "20", "1"], ["E03", "L", "50", "x", "1"]])
    t = times(sheet)
    assert list(t.index) == ["E01", "E02"]
    f = seat_frame(t, {"E01": "A", "E02": "A"})
    assert (f["num"] / f["den"]).loc["A"] == pytest.approx(17.5)
