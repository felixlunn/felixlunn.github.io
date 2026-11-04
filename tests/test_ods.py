

def test_only_named_sheets_and_names():
    import io, zipfile
    from whips.ods import read_ods, sheet_names
    xml = ('<?xml version="1.0"?><office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
           'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
           '<office:body><office:spreadsheet>'
           '<table:table table:name="2018"><table:table-row><table:table-cell><text:p>a</text:p></table:table-cell></table:table-row></table:table>'
           '<table:table table:name="2019"><table:table-row><table:table-cell><text:p>b</text:p></table:table-cell></table:table-row></table:table>'
           '</office:spreadsheet></office:body></office:document-content>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("content.xml", xml)
    assert sheet_names(buf.getvalue()) == ["2018", "2019"]
    sheets = read_ods(buf.getvalue(), only={"2019"})
    assert list(sheets) == ["2019"] and sheets["2019"].iloc[0, 0] == "b"
