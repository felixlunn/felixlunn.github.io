import io

import pandas as pd

from whips.sources.rents import latest


def test_latest_month_per_area():
    rows = [["Price Index of Private Rents"], ["notes"],
            ["Time period", "Area code", "Area name", "Rental price", "Annual change"],
            ["2026-08-01", "E06000001", "A", 500, 2.0], ["2026-09-01", "E06000001", "A", 510, 3.0],
            ["2026-09-01", "K02000001", "UK", 1400, "[x]"]]
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, sheet_name="Table 1", header=False, index=False)
    t, month = latest(pd.ExcelFile(buf))
    assert month == "September 2026"
    assert t.loc["E06000001"].tolist() == [510, 3.0]
    assert pd.isna(t.loc["K02000001", "change"])
