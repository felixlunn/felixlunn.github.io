import io

import pandas as pd

from whips.sources.insolvency import table


def test_latest_year_and_england_wales_rate():
    rows = [["Table 1b"], ["Back"], ["Code", "Name", "Geography", 2024.0, 2025.0, "Notes"],
            ["K04000001", "ENGLAND AND WALES", "Country", 24.0, 25.8, ""],
            ["E14000001", "Seat", "Parliamentary Constituency", 10.0, 12.5, ""],
            ["E12000001", "NORTH EAST", "Electoral Region", 30.0, 33.0, ""]]
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, sheet_name="Table_1b", header=False, index=False)
    s, year, national = table(pd.ExcelFile(buf), "Table_1b")
    assert year == "2025" and national == 25.8 and s.to_dict() == {"E14000001": 12.5}
