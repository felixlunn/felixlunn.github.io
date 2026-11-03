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
