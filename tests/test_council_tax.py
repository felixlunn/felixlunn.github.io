import pandas as pd

from whips.sources.council_tax import latest


def test_latest_band_d_by_billing_authority():
    sheet = pd.DataFrame([["Table 5"], ["Code", "ONS Code", "Authority", "Current", "Class", "2025 to 2026", "2026 to 2027", "Notes"],
                          ["Eng", "[z]", "England", "YES", "TE", "2280", "2391.5", ""],
                          ["E0931", "E07000026", "Allerdale", "NO", "SD", "[z]", "[z]", ""],
                          ["X", "E06000064", "Westmorland and Furness UA", "YES", "UA", "2389", "2508", ""]])
    values, national, year = latest(sheet)
    assert year == "2026 to 2027" and national == 2391.5 and values.to_dict() == {"E06000064": 2508.0}
