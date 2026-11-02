import pandas as pd
import pytest

from whips.sources.roads import place, seat_frames


class FakeLocator:
    def seats(self, lons, lats):
        return ["S14000001" for _ in lons]


def test_collisions_placed_and_averaged_per_year():
    d = pd.DataFrame({
        "collision_year": [2024, 2024, 2025, 2025],
        "longitude": [0, 0, -4, None], "latitude": [51, 51, 56, None],
        "collision_severity": [1, 3, 2, 3],
        "lsoa_of_accident_location": ["E01", "E01", "-1", "-1"],
        "collision_adjusted_severity_serious": [0.0, 0.2, 0.9, 0.1],
    })
    seat = place(d, {"E01": "E14000001"}, FakeLocator())
    assert seat.tolist()[:3] == ["E14000001", "E14000001", "S14000001"] and pd.isna(seat.iloc[3])
    f = seat_frames(d, seat, pd.Series({"E14000001": 10_000.0, "S14000001": 20_000.0, "W07000001": 10_000.0}),
                    ["E14000001", "S14000001", "W07000001", "N05000001"])
    rate = lambda k: (f[k]["num"] / f[k]["den"]).to_dict()  # noqa: E731
    assert rate("road_collisions_per_10k") == pytest.approx({"E14000001": 1.0, "S14000001": 0.25, "W07000001": 0.0})
    assert rate("road_ksi_per_10k") == pytest.approx({"E14000001": 0.6, "S14000001": 0.225, "W07000001": 0.0})
    assert f["road_fatal_5y"]["num"].to_dict() == {"E14000001": 1, "S14000001": 0, "W07000001": 0}
