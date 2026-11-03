import pandas as pd
import pytest

from whips.sources.energy import seat_frames


def test_off_gas_grid_from_meter_counts():
    gas = pd.DataFrame({"meters": [80.0], "kwh": [800_000.0]}, index=["E01"])
    elec = pd.DataFrame({"meters": [100.0, 50.0], "kwh": [300_000.0, 200_000.0]}, index=["E01", "E02"])
    f = seat_frames(gas, elec, {"E01": "A", "E02": "B"})
    rate = lambda k: (f[k]["num"] / f[k]["den"]).to_dict()  # noqa: E731
    assert rate("off_gas_grid") == pytest.approx({"A": 20.0, "B": 100.0})
    assert rate("gas_kwh_per_home")["A"] == pytest.approx(10_000.0) and pd.isna(rate("gas_kwh_per_home")["B"])
    assert rate("elec_kwh_per_home") == pytest.approx({"A": 3000.0, "B": 4000.0})
