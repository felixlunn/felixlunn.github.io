import io
import zipfile

import pandas as pd
import pytest

from whips.ods import find_table, read_ods
from whips.sources import ev

NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
      'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
      'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"')


def cell(v=None, num=False, repeat=1):
    rep = f' table:number-columns-repeated="{repeat}"' if repeat > 1 else ""
    if v is None:
        return f"<table:table-cell{rep}/>"
    val = f' office:value-type="float" office:value="{v}"' if num else ""
    return f"<table:table-cell{rep}{val}><text:p>{v}</text:p></table:table-cell>"


def ods(rows: list[list[str]]) -> bytes:
    body = "".join(f"<table:table-row>{''.join(r)}</table:table-row>" for r in rows)
    xml = (f'<office:document-content {NS}><office:body><office:spreadsheet>'
           f'<table:table table:name="EVCI0103a">{body}'
           f'<table:table-row table:number-rows-repeated="5000"><table:table-cell table:number-columns-repeated="900"/></table:table-row>'
           f'</table:table></office:spreadsheet></office:body></office:document-content>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("content.xml", xml)
    return buf.getvalue()


def sample() -> bytes:
    return ods([
        [cell("EVCI0103a: Public electric vehicle chargers by parliamentary constituency")],
        [],
        [cell("Code"), cell("Parliamentary constituency"), cell("1 April 2026"), cell("1 July 2026\n[note 3]")],
        [cell("E14000001"), cell("Seat A"), cell(10, True), cell(12, True)],
        [cell("W07000001"), cell("Seat W"), cell(3, True), cell(4, True)],
        [cell("K02000001"), cell("United Kingdom"), cell(13, True), cell(16, True)],  # not a seat
        [cell("S14000001"), cell("Seat S"), cell(5, True, repeat=2)],                 # one cell repeated across both dates
    ])


def test_ods_reader_handles_repeats_and_padding():
    sheet = read_ods(sample())["EVCI0103a"]
    assert sheet.shape == (7, 4)  # 5,000 padding rows x 900 blank columns trimmed away
    table = find_table(sheet, "Code")
    assert table.columns[-1] == "1 July 2026\n[note 3]" and table.iloc[3, 3] == "5"


def test_counts_use_latest_column_and_all_nations():
    c, when = ev.counts(read_ods(sample())["EVCI0103a"])
    assert when == "1 July 2026"
    assert c.to_dict() == {"E14000001": 12, "W07000001": 4, "S14000001": 5}
