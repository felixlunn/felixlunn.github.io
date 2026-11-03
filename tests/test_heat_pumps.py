import io

import pandas as pd

from whips.sources.heat_pumps import by_constituency


def test_heat_pump_grants_by_constituency():
    rows = [["Table Q1.3"], ["notes"], ["Area Codes", "Country or Region", "Westminster Parliamentary Constituency",
                                        "Heat pump technologies [note 2]", "Biomass boilers"],
            ["E14000001", "North East", "Seat", 120, 1], ["W07000001", "Wales", "Seat W", "[c]", 0], ["E12000001", "NE", "", 9, 9]]
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, sheet_name="Q1.3", header=False, index=False)
    n = by_constituency(pd.ExcelFile(buf))
    assert n.loc["E14000001"] == 120 and pd.isna(n.loc["W07000001"]) and "E12000001" not in n.index
