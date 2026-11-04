import pandas as pd

from whips.sources.floods import seat_frames


def test_counts_with_zero_for_english_seats_without_areas():
    areas = pd.DataFrame({"code": ["a", "b", "c"]})
    f = seat_frames(areas, ["E14000001", "E14000001", None], ["E14000001", "E14000002", "S14000001"])
    assert f["flood_warning_areas"]["num"].to_dict() == {"E14000001": 2, "E14000002": 0}
