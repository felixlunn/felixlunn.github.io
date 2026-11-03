import pandas as pd

from whips.sources.road_condition import latest_by_authority


def test_latest_year_by_highway_authority():
    sheet = pd.DataFrame([["Percentage"], ["ONS Area Code", "Region", "Local Authority", "FYE 2025", "FYE 2026", "Notes"],
                          ["E92000001", "", "England", "5", "4", ""], ["E10000006", "NW", "Cumbria", "3", "[x]", ""],
                          ["E06000064", "NW", "Westmorland and Furness", "", "6", ""]])
    s, year = latest_by_authority(sheet)
    assert year == "FYE 2026" and s.to_dict() == {"E06000064": 6.0} and s.attrs["national"] == 4.0
