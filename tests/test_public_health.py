import pytest

from whips.sources.public_health import parse

CSV = """Area Code,Area Type,Sex,Category Type,Time period,Time period Sortable,Value
E92000001,England,Persons,,2025/26,20250000,84.0
E92000001,England,Male,,2025/26,20250000,83.0
E06000001,Districts & UAs (from Apr 2023),Persons,,2025/26,20250000,90.5
E06000001,Districts & UAs (from Apr 2023),Persons,,2024/25,20240000,80.0
E06000002,Districts & UAs (from Apr 2023),Persons,,2025/26,20250000,
"""


def test_parse_latest_persons():
    values, national, period = parse(CSV)
    assert period == "2025/26" and national == pytest.approx(84.0)
    assert values.to_dict() == {"E06000001": 90.5}


def test_national_uses_the_councils_age_group():
    from whips.sources.public_health import parse_periods
    csv = """Area Code,Area Type,Sex,Age,Category Type,Time period,Time period Sortable,Value
E92000001,England,Persons,25-29 yrs,,2025,20250000,27.0
E92000001,England,Persons,18+ yrs,,2025,20250000,10.0
E06000001,Districts & UAs (from Apr 2023),Persons,18+ yrs,,2025,20250000,12.0
"""
    (period, values, national), = parse_periods(csv)
    assert national == pytest.approx(10.0) and values.to_dict() == {"E06000001": 12.0}
