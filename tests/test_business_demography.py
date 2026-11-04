import io

import pandas as pd

from whips.sources.business_demography import counts, latest_sheet


def test_counts_latest_year():
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as w:
        for name in ["Table 1.1a", "Table 1.1d"]:
            pd.DataFrame([["Table"], ["notes"], [None, None, 2023, 2024], ["K04000001", "E&W", 10, 20],
                          ["E06000001", "Hartlepool", 1, 2]]).to_excel(w, sheet_name=name, header=False, index=False)
    book = pd.ExcelFile(buf)
    assert latest_sheet(book, 1) == "Table 1.1d"
    c, year = counts(book, "Table 1.1d")
    assert year == "2024" and c.to_dict() == {"K04000001": 20, "E06000001": 2}
