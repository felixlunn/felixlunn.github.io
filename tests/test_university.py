import pytest

from whips.sources.university import parse, seat_frame


def test_cohort_weighted_progression():
    lsoa = parse(b"lsoa11,total_pop,progression_rate,quintile\nE01,100,0.5,3\nE02,300,0.3,2\nE03,,,\n")
    assert list(lsoa.index) == ["E01", "E02"]
    f = seat_frame(lsoa, {"E01": "A", "E02": "A"})
    assert (f["num"] / f["den"]).loc["A"] == pytest.approx(35.0)
