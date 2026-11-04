"""A minimal OpenDocument spreadsheet (.ods) reader, so the pipeline doesn't need odfpy.

GOV.UK statistics are often published only as .ods. This reads each sheet's
cells as text (repeated rows/columns expanded, trailing blanks trimmed).
"""

from __future__ import annotations

import io
import zipfile
from xml.etree.ElementTree import iterparse

import pandas as pd

_T = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
_X = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
_O = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
MAX_REPEAT = 1000  # blank padding rows/columns can be "repeated" thousands of times


def _cell_text(cell) -> str | None:
    value = cell.get(_O + "value")
    if value is not None:
        return value
    parts = ["".join(p.itertext()) for p in cell.iter(_X + "p")]
    return "\n".join(parts) if parts else None


def read_ods(data: bytes, only: set[str] | None = None) -> dict[str, pd.DataFrame]:
    """All sheets (or just those named in ``only``) of an .ods file as DataFrames of strings (no header row)."""
    content = zipfile.ZipFile(io.BytesIO(data)).open("content.xml")
    sheets: dict[str, pd.DataFrame] = {}
    rows: list[list[str | None]] = []
    keep = True
    for event, el in iterparse(content, events=("start", "end")):
        if event == "start" and el.tag == _T + "table":
            rows = []
            keep = only is None or el.get(_T + "name") in only
        elif event == "end" and el.tag == _T + "table-row" and not keep:
            el.clear()
        elif event == "end" and el.tag == _T + "table-row":
            row: list[str | None] = []
            for cell in el:
                if cell.tag not in (_T + "table-cell", _T + "covered-table-cell"):
                    continue
                n = min(int(cell.get(_T + "number-columns-repeated", "1")), MAX_REPEAT)
                row.extend([_cell_text(cell)] * n)
            while row and row[-1] is None:
                row.pop()
            reps = min(int(el.get(_T + "number-rows-repeated", "1")), MAX_REPEAT)
            rows.extend([row] * (reps if row else 1))
            el.clear()
        elif event == "end" and el.tag == _T + "table" and not keep:
            el.clear()
        elif event == "end" and el.tag == _T + "table":
            while rows and not rows[-1]:
                rows.pop()
            width = max((len(r) for r in rows), default=0)
            sheets[el.get(_T + "name")] = pd.DataFrame([r + [None] * (width - len(r)) for r in rows])
            el.clear()
    return sheets


def find_table(sheet: pd.DataFrame, first_header: str) -> pd.DataFrame:
    """The table in a sheet whose header row starts with ``first_header`` (case-insensitive)."""
    first = sheet.iloc[:, 0].astype(str).str.strip().str.lower()
    row = first[first.str.startswith(first_header.lower())].index[0]
    table = sheet.iloc[row + 1:].copy()
    table.columns = [str(c).strip() if c is not None else f"col{i}" for i, c in enumerate(sheet.iloc[row])]
    return table.reset_index(drop=True)


def sheet_names(data: bytes) -> list[str]:
    """Sheet names of an .ods file, without parsing the cells."""
    import re
    content = zipfile.ZipFile(io.BytesIO(data)).read("content.xml")
    return [n.decode("utf-8") for n in re.findall(rb'<table:table [^>]*?table:name="([^"]+)"', content)]
