import pandas as pd
import pytest

from whips.history import MAX_PERIODS, assemble_history, with_history


def frame(vals):
    return pd.DataFrame({"num": vals, "den": 1.0}, index=["A", "B"])


def test_history_values_and_national():
    latest = frame([3.0, 5.0])
    with_history(latest, [("2024", frame([2.0, 4.0]), None), ("2025", latest, 4.5)])
    h = assemble_history(["A", "B", "C"], {"m": latest}, [{"id": "m", "decimals": 1}])["metrics"]["m"]
    assert h["periods"] == ["2024", "2025"]
    assert h["national"] == [pytest.approx(3.0), 4.5]  # sum/sum unless the source gives a national figure
    assert h["values"] == [[2.0, 4.0, None], [3.0, 5.0, None]]


def test_single_period_is_not_history_and_long_series_are_trimmed():
    one = with_history(frame([1.0, 1.0]), [("2025", frame([1.0, 1.0]), None)])
    assert "history" not in one.attrs
    many = with_history(frame([1.0, 1.0]), [(str(y), frame([y, y]), None) for y in range(2000, 2026)])
    assert len(many.attrs["history"]) == MAX_PERIODS and many.attrs["history"][-1][0] == "2025"


def test_new_councils_get_predecessor_figures():
    from whips.history import fill_successors
    v = pd.Series({"E07000027": 10.0, "E07000030": 20.0, "E07000031": 30.0, "E10000006": 99.0, "E06000001": 5.0})
    filled = fill_successors(v)
    assert filled["E06000064"] == pytest.approx((10 + 20 + 30 + 99) / 4) and filled["E06000001"] == 5.0
    assert fill_successors(v, "sum")["E06000064"] == 60.0  # counts: districts only
    assert fill_successors(pd.Series({"E06000064": 1.0, "E07000027": 5.0}))["E06000064"] == 1.0  # never overwritten
