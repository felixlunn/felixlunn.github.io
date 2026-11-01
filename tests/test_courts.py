import io
import zipfile

import pandas as pd
import pytest

from whips.sources import courts


def test_area_keys_group_like_the_court_data():
    assert courts.area_key("South East London LCJB") == "london"
    assert courts.area_key("Metropolitan Police") == courts.area_key("London, City of") == "london"
    assert courts.area_key("Gwent") == courts.area_key("Dyfed-Powys") == courts.area_key("South Wales LCJB") == "south wales"
    assert courts.area_key("Devon & Cornwall") == courts.area_key("Devon and Cornwall LCJB")
    assert courts.area_key("Hampshire and Isle of Wight LCJB") == courts.area_key("Hampshire")


def pivot_xlsx() -> bytes:
    """A minimal workbook with a pivot cache shaped like MoJ's tool."""
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    defn = f"""<pivotCacheDefinition {ns}><cacheFields count="6">
      <cacheField name="year"><sharedItems><n v="2025"/><n v="2026"/></sharedItems></cacheField>
      <cacheField name="quarter"><sharedItems><s v="Q2"/></sharedItems></cacheField>
      <cacheField name="lcjb_area"><sharedItems><s v="Kent LCJB"/><s v="Central London LCJB"/><s v="South East London LCJB"/></sharedItems></cacheField>
      <cacheField name="rdos"><sharedItems><s v="1. Receipts"/><s v="3. Open"/></sharedItems></cacheField>
      <cacheField name="offence_group"><sharedItems><s v="00: All offences"/><s v="01: Violence"/></sharedItems></cacheField>
      <cacheField name="value"><sharedItems/></cacheField></cacheFields></pivotCacheDefinition>"""
    recs = [  # year, quarter, area, rdos, offence, value
        (1, 0, 0, 1, 0, 120), (0, 0, 0, 1, 0, 100),   # Kent open: 120 now, 100 a year ago
        (1, 0, 1, 1, 0, 50), (1, 0, 2, 1, 0, 150),    # London open now: 200
        (0, 0, 1, 1, 0, 100), (0, 0, 2, 1, 0, 150),   # London a year ago: 250
        (1, 0, 0, 0, 0, 999), (1, 0, 0, 1, 1, 999),   # receipts / a single offence group: ignored
    ]
    body = "".join(f'<r><x v="{y}"/><x v="{q}"/><x v="{a}"/><x v="{r}"/><x v="{o}"/><n v="{v}"/></r>' for y, q, a, r, o, v in recs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/pivotCache/pivotCacheDefinition1.xml", defn)
        z.writestr("xl/pivotCache/pivotCacheRecords1.xml", f"<pivotCacheRecords {ns}>{body}</pivotCacheRecords>")
    return buf.getvalue()


def test_reads_pivot_cache_and_open_cases_by_area():
    areas, latest = courts.open_by_area(courts.read_pivot_cache(pivot_xlsx()))
    assert latest == "2026 Q2"
    assert areas.loc["kent"].tolist() == [120, 100]
    assert areas.loc["london"].tolist() == [200, 250]


def test_seat_frames_area_values_and_true_national_rates():
    areas = pd.DataFrame({"open": [120.0, 200.0], "open_prior": [100.0, 250.0]}, index=["kent", "london"])
    seat_area = {"K1": "kent", "K2": "kent", "L1": "london"}
    pop = pd.Series({"K1": 30_000.0, "K2": 90_000.0, "L1": 100_000.0})
    f = courts.seat_frames(areas, seat_area, pop)
    rate = f["court_open_per_1k"]
    assert (rate["num"] / rate["den"]).to_dict() == pytest.approx({"K1": 1.0, "K2": 1.0, "L1": 2.0})  # area-wide
    assert rate["num"].sum() / rate["den"].sum() == pytest.approx(320 * 1000 / 220_000)
    ch = f["court_backlog_change"]
    assert (ch["num"] / ch["den"]).to_dict() == pytest.approx({"K1": 20.0, "K2": 20.0, "L1": -20.0})
    assert ch["num"].sum() / ch["den"].sum() == pytest.approx((320 - 350) / 350 * 100)
