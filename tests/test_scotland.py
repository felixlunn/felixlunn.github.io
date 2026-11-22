import struct

import pandas as pd
import pytest

from datadash.metrics import CENSUS_METRICS, SCOTLAND_CENSUS
from datadash.sources import scotland as sc

TABLE = '''"Scotland's Census 2022 - National Records of Scotland"
"Table UV404 - Household tenure - Households"
"All occupied households"
,"All occupied households","Owned: Total","Owned: Owned outright","Private rented: Total","Social Rented: Council (LA) or Housing Association"
"S00000001",100,60,40,30,10
"S00000002",50,-,-,20,30
"In order to protect against disclosure"
'''


def test_read_table_and_sum_to_seats():
    t = sc.read_table(TABLE)
    assert list(t.index) == ["S00000001", "S00000002"] and t.loc["S00000002", "owned: total"] == 0
    f = sc.seat_frames({"UV404": t}, pd.Series({"S00000001": "S14000001", "S00000002": "S14000001"}))
    rate = lambda k: (f[k]["num"] / f[k]["den"]).loc["S14000001"]  # noqa: E731
    assert rate("private_rented") == pytest.approx(50 / 150 * 100)
    assert rate("social_rented") == pytest.approx(40 / 150 * 100)


def test_two_header_rows_are_combined():
    text = '''"x"
"Table UV102b - Age (20) by sex"
"All people"
,"All people","All people","Female"
,"All people","0 - 4","All people"
"S00000001",10,2,6
'''
    t = sc.read_table(text)
    assert list(t.columns) == ["all people: all people", "all people: 0 - 4", "female: all people"]


def test_centroid_dbf():
    fields = [(b"code", b"C", 9), (b"easting", b"C", 6), (b"northing", b"C", 7)]
    rec_len = 1 + sum(f[2] for f in fields)
    header = struct.pack("<BBBBIHH20x", 3, 0, 0, 0, 1, 32 + 32 * len(fields) + 1, rec_len)
    desc = b"".join(n.ljust(11, b"\0") + t + b"\0" * 4 + bytes([ln]) + b"\0" * 15 for n, t, ln in fields)
    dbf = header + desc + b"\r" + b" " + b"S00000001" + b"393865" + b"0806312"
    c = sc.centroids(dbf)
    assert c.loc["S00000001"].tolist() == [393865.0, 806312.0]


def test_every_scottish_figure_is_a_census_figure():
    ids = {m.id for m in CENSUS_METRICS}
    assert set(sc.MAPPING) | {"population"} == SCOTLAND_CENSUS and SCOTLAND_CENSUS <= ids
