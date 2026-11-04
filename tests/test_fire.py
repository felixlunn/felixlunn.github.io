import pandas as pd
import pytest

from whips.sources.fire import key, response_times


def test_fire_authority_names_match_lookup():
    assert key("London Fire and Emergency Planning Authority") == key("Greater London")
    assert key("Devon & Somerset") == key("Devon and Somerset")


def test_latest_full_year_in_minutes():
    d = pd.DataFrame({"FINANCIAL_YEAR": ["2025/26", "2025/26", "2025/26", "2026/27", "2026/27"],
                      "FIRE_TYPE": ["Dwellings"] * 5,
                      "LOCATION_CATEGORY": ["England", "Avon", "Kent", "England", "Avon"],
                      "TOTAL_RESPONSE_TIME": [8 / 1440, 9 / 1440, 7 / 1440, 1, 1]})
    s, national, year = response_times(d, "dwellings")
    assert year == "2025/26" and national == pytest.approx(8.0) and s["avon"] == pytest.approx(9.0)
