import pandas as pd
import pytest

from whips.sources.income import parse


def test_parse_income_table():
    h = ["Parliamentary Constituency Codes", "Parliamentary Constituency", "Total income: Number of individuals", "Total income: Median",
         "Higher rate: Number of individuals", "Additional rate: Number of individuals"]
    sheet = pd.DataFrame([["Table 3.15"], h, ["E12000001", "North East", "1000", "27000", "100", "10"],
                          ["E14000001", "A", "40", "30000", "8", "[Not available]"], ["E14000002", "B", "60", "20000", "3", "1"]])
    frames, national = parse(sheet)
    assert frames["taxpayer_income_median"]["num"].to_dict() == {"E14000001": 30000, "E14000002": 20000}
    hr = frames["higher_rate_taxpayers"]
    assert (hr["num"] / hr["den"]).to_dict() == pytest.approx({"E14000001": 20.0, "E14000002": 400 / 60})
    assert national["taxpayer_income_median"] == 20000  # weighted middle: B holds 60 of 100 taxpayers
