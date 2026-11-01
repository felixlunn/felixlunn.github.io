import pandas as pd
import pytest

from whips.sources import schools


def gias():
    rows = [
        # status, group, code, pupils, fsm
        ("Open", "Academies", "E14000001", 1000, 300),
        ("Open", "Local authority maintained schools", "E14000001", 1000, 100),
        ("Open", "Independent schools", "E14000001", 500, None),
        ("Closed", "Academies", "E14000001", 9999, 9999),       # closed: ignored
        ("Open", "Welsh schools", "W07000081", 800, 200),        # Wales: ignored (different fields)
        ("Open", "Free Schools", "E14000002", 400, 40),
    ]
    return pd.DataFrame(rows, columns=["EstablishmentStatus (name)", "EstablishmentTypeGroup (name)",
                                       "ParliamentaryConstituency (code)", "NumberOfPupils", "FSM"])


def test_gias_frames():
    f = schools.gias_frames(gias())
    val = lambda mid, c: f[mid].loc[c, "num"] / f[mid].loc[c, "den"]  # noqa: E731
    assert val("school_fsm", "E14000001") == pytest.approx(20.0)        # 400 of 2000 state pupils
    assert val("school_academy", "E14000001") == pytest.approx(50.0)
    assert val("school_independent", "E14000001") == pytest.approx(20.0)  # 500 of 2500
    assert val("school_academy", "E14000002") == pytest.approx(100.0)
    assert val("school_independent", "E14000002") == 0
    assert "W07000081" not in f["school_fsm"].index


def test_ks4_frames_maps_locations_and_weights_attainment8():
    rows = [
        {"locations": {"PCON": "a"}, "values": {"eDSuS": "100", "Y26HK": "60", "XLwfK": "40", "PrTeb": "45.0"}},
        {"locations": {"PCON": "b"}, "values": {"eDSuS": "300", "Y26HK": "240", "XLwfK": "150", "PrTeb": "50.0"}},
        {"locations": {"PCON": "unknown"}, "values": {"eDSuS": "5"}},
        {"locations": {"PCON": "c"}, "values": {"eDSuS": "50", "Y26HK": "x", "XLwfK": "x", "PrTeb": "z"}},  # suppressed
    ]
    f = schools.ks4_frames(rows, {"a": "E1", "b": "E2", "c": "E3"})
    em4 = f["gcse_em4"]
    assert (em4["num"] / em4["den"]).loc[["E1", "E2"]].tolist() == pytest.approx([60.0, 80.0])
    a8 = f["gcse_a8"]
    assert a8["num"].sum() / a8["den"].sum() == pytest.approx((45 * 100 + 50 * 300) / 400)  # pupil-weighted
    assert pd.isna(em4.loc["E3", "num"])
