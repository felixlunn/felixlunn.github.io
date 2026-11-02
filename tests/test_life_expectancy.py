from whips.sources import life_expectancy as L

CSV = """Indicator ID,Area Code,Area Type,Sex,Age,Category Type,Category,Time period,Value,Time period Sortable
90366,E92000001,England,Male,All ages,,,2022 - 24,79.5,20220000
90366,E92000001,England,Male,All ages,,,2023 - 25,79.7,20230000
90366,E92000001,England,Female,All ages,,,2023 - 25,83.5,20230000
90366,E06000001,Districts & UAs (from Apr 2023),Male,All ages,,,2023 - 25,77.0,20230000
90366,E06000001,Districts & UAs (from Apr 2023),Female,All ages,,,2023 - 25,81.0,20230000
90366,E06000001,Districts & UAs (from Apr 2023),Male,All ages,,,2025,99.0,20250000
90366,E06000001,Districts & UAs (from Apr 2023),Male,All ages,LSOA21 deprivation deciles,Most deprived,2023 - 25,70.0,20230000
"""


def test_latest_three_year_period_and_england_values():
    values, national, period = L.parse(CSV)
    assert period == "2023 - 25"  # the single year "2025" and deprivation breakdowns are ignored
    assert values["Male"].to_dict() == {"E06000001": 77.0} and values["Female"].to_dict() == {"E06000001": 81.0}
    assert national == {"Male": 79.7, "Female": 83.5}
