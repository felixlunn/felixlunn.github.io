import io
from datetime import time, timedelta

import pandas as pd
import pytest

from whips.geo import SeatLocator, ngr_to_en
from whips.sources import sewage


def test_grid_references():
    assert ngr_to_en("SP6419046470") == (464190, 246470)
    assert ngr_to_en("TQ 30000 80000") == (530000, 180000)
    assert ngr_to_en("NT2547073500") == (325470, 673500)
    assert ngr_to_en("SU123") is None and ngr_to_en("nonsense") is None


def test_durations_in_any_format():
    assert sewage.hours("123:30:00") == pytest.approx(123.5)
    assert sewage.hours(timedelta(hours=30, minutes=15)) == pytest.approx(30.25)
    assert sewage.hours(time(5, 30)) == pytest.approx(5.5)
    assert sewage.hours(7) == 7 and sewage.hours(None) is None and sewage.hours("n/a") is None


def workbook() -> bytes:
    buf = io.BytesIO()
    head = ["Unique ID", "Water Company Name", "Outlet Discharge NGR\n(EA Consents Database)",
            "Total Duration (hh:mm:ss) all spills prior to processing through 12-24h count method",
            "Counted spills using 12-24h count method"]
    rows = [["EDM STORM OVERFLOW REGULATORY ANNUAL RETURN"] + [None] * 4, [None] * 5, head,
            ["A1", "X Water", "TQ3000080000", "10:00:00", 5],   # central London
            ["A2", "X Water", "TQ3000080000", "02:30:00", 1],
            ["A3", "X Water", "SP6419046470", "1:00:00", 2],    # outside the test seats
            ["A4", "X Water", None, "1:00:00", 9]]               # no location
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        pd.DataFrame(rows).to_excel(xl, sheet_name="All WaSC", header=False, index=False)
    return buf.getvalue()


def test_parse_and_count_per_seat():
    overflows = sewage.parse_return(workbook())
    assert len(overflows) == 3 and overflows["hours"].tolist() == pytest.approx([10, 2.5, 1])
    geo = {"features": [
        {"properties": {"code": "E1"}, "geometry": {"type": "Polygon", "coordinates": [[[-0.2, 51.4], [0.0, 51.4], [0.0, 51.6], [-0.2, 51.6], [-0.2, 51.4]]]}},
        {"properties": {"code": "W2"}, "geometry": {"type": "Polygon", "coordinates": [[[-4, 52], [-3.9, 52], [-3.9, 52.1], [-4, 52.1], [-4, 52]]]}},
        {"properties": {"code": "S3"}, "geometry": {"type": "Polygon", "coordinates": [[[-3, 56], [-2.9, 56], [-2.9, 56.1], [-3, 56.1], [-3, 56]]]}},
    ]}
    loc = SeatLocator(geo)
    f = sewage.seat_frames(overflows, loc, loc.codes)
    assert f["sewage_spills"]["num"].to_dict() == {"E1": 6, "W2": 0}  # Scotland isn't covered
    assert f["sewage_hours"]["num"].to_dict() == pytest.approx({"E1": 12.5, "W2": 0})
