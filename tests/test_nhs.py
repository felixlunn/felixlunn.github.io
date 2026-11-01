import pandas as pd
import pytest

from whips.sources import nhs


def rows():
    return pd.DataFrame([
        # Indicator ID, Area Code, Time period, sortable, Count, Denominator
        (241, "P1", "2023/24", 20230000, 1, 10),        # older year: dropped
        (241, "P1", "2024/25", 20240000, 80, 1000),
        (241, "P2", "2024/25", 20240000, 60, 1000),
        (241, "P3", "2024/25", 20240000, 10, 500),
        (94126, "P1", "2024", 20240000, 700, 1000),
        (94126, "P3", "2024", 20240000, None, 100),    # suppressed: skipped
    ], columns=["Indicator ID", "Area Code", "Time period", "Time period Sortable", "Count", "Denominator"])


def test_latest_and_seat_sums():
    latest, periods = nhs.latest_by_practice(rows())
    assert periods == {241: "2024/25", 94126: "2024"}
    f = nhs.seat_frames(latest, {"P1": "E1", "P2": "E1", "P3": "E2"})
    d = f["nhs_diabetes"]
    assert (d["num"] / d["den"]).to_dict() == pytest.approx({"E1": 7.0, "E2": 2.0})
    g = f["gp_contact_good"]
    assert (g["num"] / g["den"]).to_dict() == pytest.approx({"E1": 70.0})


class FakePostcodes:
    def post(self, url, json, timeout):
        lookup = {"LA9 4AB": "E14001580", "TS18 1HU": "E14001518"}

        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"result": [{"query": p, "result": ({"codes": {"parliamentary_constituency_2024": lookup[p]}} if p in lookup else None)}
                                   for p in json["postcodes"]]}
        return R()


def test_practice_constituencies_by_postcode():
    out = nhs.practice_constituencies(FakePostcodes(), {"P1": "la9 4ab ", "P2": "TS18 1HU", "P3": "ZZ1 1ZZ", "P4": None, "P5": "LA9 4AB"})
    assert out == {"P1": "E14001580", "P5": "E14001580", "P2": "E14001518"}
