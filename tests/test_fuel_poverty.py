import io

import pandas as pd
import pytest

from whips.sources import fuel_poverty as fp


def workbook() -> bytes:
    """Laid out like the DESNZ tables: a title row, a blank row, then the header."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        pd.DataFrame().to_excel(xl, sheet_name="Title", index=False)
        def table(name, title, cols, rows):
            pd.DataFrame([[title] + [None] * (len(cols) - 1), [None] * len(cols), cols, *rows]).to_excel(
                xl, sheet_name=name, header=False, index=False)
        table("Table 3", "Table 3: Fuel Poverty in England by Parliamentary Constituency, 2024",
              ["Parliamentary Constituency Code", "Nation or Region", "Parliamentary Constituency", "Number of households",
               "Number of households in fuel poverty", "Proportion of households fuel poor (%)"],
              [["E92000001", "ENGLAND", None, 1000, 100, 10], ["E14000001", "NE", "Seat A", 400, 60, 15], ["E14000002", "NE", "Seat B", 600, 40, 6.7]])
        table("Table 4", "Table 4: Fuel Poverty in England by Lower layer Super Output Area (LSOA), 2024",
              ["LSOA Code", "LSOA Name", "Local Authority Code", "Local Authority Name", "Region", "Number of households",
               "Number of households in fuel poverty", "Proportion of households fuel poor (%)"],
              [["E01000001", "x 001A", "E09", "x", "L", 500, 50, 10]])
    return buf.getvalue()


def test_reads_constituency_and_lsoa_tables():
    x = workbook()
    seats = fp.frame(fp.read_table(x, fp.sheet_for(x, "Constituency"), "Constituency Code"), "E14")
    assert list(seats.index) == ["E14000001", "E14000002"]  # England / region rows dropped
    assert (seats["num"] / seats["den"]).tolist() == pytest.approx([15.0, 40 / 6])
    lsoas = fp.frame(fp.read_table(x, fp.sheet_for(x, "LSOA"), "LSOA Code"), "E01")
    assert (lsoas["num"] / lsoas["den"]).loc["E01000001"] == pytest.approx(10.0)
