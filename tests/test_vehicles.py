import pandas as pd
import pytest

from whips.sources.vehicles import latest_counts, seat_frames

CSV = b"""LSOA21CD,LSOA21NM,BodyType,Keepership,LicenceStatus,2026 Q2,2026 Q1
E01,a,Cars,Private,Licensed,100,90
E01,a,Cars,Company,Licensed,999,1
E02,b,Cars,Private,Licensed,[c],5
E02,b,Cars,Private,SORN,7,7
E03,c,Cars,Private,Licensed,50,50
"""


def test_latest_quarter_private_licensed_cars():
    cars, quarter = latest_counts(CSV, {"BodyType": "Cars", "Keepership": "Private", "LicenceStatus": "Licensed"})
    assert quarter == "2026 Q2"
    assert cars.to_dict() == {"E01": 100, "E02": 0, "E03": 50}


def test_seat_frames():
    f = seat_frames(pd.Series({"E01": 100.0, "E02": 0.0, "E03": 50.0}), pd.Series({"E01": 10.0}),
                    {"E01": "A", "E02": "A", "E03": "B"}, pd.Series({"A": 50.0, "B": 25.0}))
    assert (f["plugin_share_private"]["num"] / f["plugin_share_private"]["den"]).to_dict() == pytest.approx({"A": 10.0, "B": 0.0})
    assert (f["cars_per_household"]["num"] / f["cars_per_household"]["den"]).to_dict() == pytest.approx({"A": 2.0, "B": 2.0})
