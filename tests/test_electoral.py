import io

import pandas as pd

from datadash.sources import electoral


def workbook(codes, title="Table 1: Electoral registrations, 1 December 2025: Westminster Parliamentary constituencies"):
    rows = [[title, None, None, None, None], ["Does this meet your needs?", None, None, None, None],
            ["Code", "Area name", "Constituency type", "Electoral registrations", "(of which)\nAttainers"],
            ["K02000001", "UNITED KINGDOM", ".", 47_000_000, 170_000]]
    rows += [[c, f"Seat {i}", "B", 70_000 + i, 100 + i] for i, c in enumerate(codes)]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        pd.DataFrame([["Cover"]]).to_excel(xl, sheet_name="Cover sheet", header=False, index=False)
        pd.DataFrame(rows).to_excel(xl, sheet_name="Table 1", header=False, index=False)
    return pd.ExcelFile(io.BytesIO(buf.getvalue()))


NEW = [f"E14{1063 + i:06d}" for i in range(543)] + [f"W07{i:06d}" for i in range(32)] + \
      [f"S14{i:06d}" for i in range(57)] + [f"N05{i:06d}" for i in range(18)]


def test_reads_the_current_constituencies():
    t, when = electoral.parse_table(workbook(NEW))
    assert len(t) == 650 and when == "December 2025"
    assert t.loc["E14001063", "electors"] == 70_000 and t.loc["E14001063", "attainers"] == 100


def test_skips_editions_on_the_old_boundaries():
    old = [f"E14{530 + i:06d}" for i in range(533)] + [f"W07{i:06d}" for i in range(40)] + [f"S14{i:06d}" for i in range(59)]
    assert electoral.parse_table(workbook(old, "Table 2: Electoral registers, 1 December 2023")) is None


def test_metrics_including_change_since_the_election():
    t = pd.DataFrame({"electors": [72_000.0, 68_000.0, 70_000.0], "attainers": [144.0, 34.0, 700.0]}, index=["E14001063", "E14001064", "S14000001"])
    f = electoral.seat_frames(t, pd.Series({"E14001063": 70_000.0, "E14001064": 80_000.0, "S14000001": 70_000.0}))
    val = {k: (v["num"] / v["den"]).round(2).to_dict() for k, v in f.items()}
    assert val["electors"] == {"E14001063": 72_000.0, "E14001064": 68_000.0, "S14000001": 70_000.0}
    assert val["attainers_per_1000"] == {"E14001063": 2.0, "E14001064": 0.5}  # England only
    assert val["electors_change"] == {"E14001063": 2.86, "E14001064": -15.0, "S14000001": 0.0}
    assert "electors_change" not in electoral.seat_frames(t, None)  # no election results: that figure is left out


def test_finds_workbook_links_newest_first():
    html = '<a href="/file?uri=/x/december2025/a.xlsx">x</a><a href="/file?uri=/x/2019/b.xls">y</a>'
    assert electoral.editions(html) == ["https://www.ons.gov.uk/file?uri=/x/december2025/a.xlsx", "https://www.ons.gov.uk/file?uri=/x/2019/b.xls"]
