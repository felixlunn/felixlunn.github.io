import io

import pandas as pd
import pytest

from whips.sources.air_energy import parse_air, renewable_counts

AIR = """Indicator ID,Area Code,Area Type,Category Type,Time period,Time period Sortable,Value
93861,E92000001,England,,2023,20230000,5.2
93861,E92000001,England,,2024,20240000,5.3
93861,E92000001,England,,2024,20240000,5.3
93861,E06000001,Districts & UAs (from Apr 2023),,2024,20240000,4.1
93861,E06000001,Districts & UAs (from Apr 2023),Deprivation,2024,20240000,9.9
"""


def test_parse_air_latest_year():
    values, national, period = parse_air(AIR)
    assert period == "2024" and national == pytest.approx(5.3)
    assert values.to_dict() == {"E06000001": 4.1}


def test_renewable_counts_latest_sites_sheet():
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as w:
        for year, solar in [(2024, 1), (2025, 5)]:
            pd.DataFrame([["Notes"], ["Local Authority Code", "Local Authority Name", "Estimated number of households", "Solar PV"],
                          ["E06000001", "A", 100, solar], ["S12000033", "Aberdeen", 50, 9]]).to_excel(
                w, sheet_name=f"LA - Sites {year}", header=False, index=False)
    c, year = renewable_counts(pd.ExcelFile(buf))
    assert year == "2025"
    assert c.to_dict("index") == {"E06000001": {"households": 100, "solar_sites": 5}}
