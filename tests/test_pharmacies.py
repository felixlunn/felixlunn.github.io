import pandas as pd
import pytest

from whips.sources.pharmacies import quarter_key, seat_frames


def test_quarter_key_handles_both_name_styles():
    assert quarter_key("CONSOL_PHARMACY_LIST_202526Q4") == (2025, 4)
    assert quarter_key("CONSOL_PHARMACY_LIST_202606Q1") == (2026, 1)
    assert quarter_key("CONSOL_PHARMACY_LIST_202425Q4FINAL") == (2024, 4)


def test_counts_and_change():
    now = pd.Series(["E1", "E1", "E2"], index=["a", "b", "c"])
    then = pd.Series(["E1", "E1", "E1", "E1", "E2"], index=list("vwxyz"))
    f = seat_frames(now, then, pd.Series({"E1": 10_000.0, "E2": 20_000.0, "W1": 5.0}))
    assert (f["pharmacies_per_10k"]["num"] / f["pharmacies_per_10k"]["den"]).to_dict() == pytest.approx({"E1": 2.0, "E2": 0.5})
    assert (f["pharmacies_change"]["num"] / f["pharmacies_change"]["den"]).to_dict() == pytest.approx({"E1": -50.0, "E2": 0.0})
