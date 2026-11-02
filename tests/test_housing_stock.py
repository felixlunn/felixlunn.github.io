import pandas as pd
import pytest

from whips.sources.housing_stock import net_additions, taxbase_table


def test_taxbase_table_picks_total_of_named_table():
    rows = [
        ["Council Taxbase Data", None, None, None, None, None, None, None],
        [None, None, None, "Table 1.01 Total dwellings", None, None, "Table 1.11 Second homes", None],
        ["E-code", "ONS Code", "Region", "Band A", "Total", None, "Band A", "Total"],
        ["E1", "E07000001", "NW", "5", "100", None, "1", "7"],
        ["E2", "E06000002", "SW", "5", "50", None, "1", "[x]"],
    ]
    sheet = pd.DataFrame(rows)
    assert taxbase_table(sheet, "1.01").to_dict() == {"E07000001": 100, "E06000002": 50}
    assert taxbase_table(sheet, "1.11").to_dict() == {"E07000001": 7}


def test_net_additions_averages_latest_years():
    rows = [["title"], ["DCLG code", "Former ONS code", "Current ONS code", "Authority data", "2022-23", "2023-24 [r]", "2024-25 [p]"],
            [None, None, "E92000001", "England", "1", "2", "3"],
            ["A", "00A", "E06000001", "A UA", "10", "20", "30"],
            ["B", "00B", "E06000064", "New council", "[x]", "[x]", "40"]]
    net, period = net_additions(pd.DataFrame(rows), years=2)
    assert period == "2023-24 to 2024-25"
    assert net.to_dict() == pytest.approx({"E06000001": 25.0, "E06000064": 40.0})
