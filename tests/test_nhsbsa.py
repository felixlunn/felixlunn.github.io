import pandas as pd
import pytest

from whips.sources import nhsbsa


def fake_sql(responses):
    def sql(s, resource, query):
        for key, rows in responses.items():
            if key in query:
                return rows
        return []
    return sql


def test_prescribing_per_1000_patients_matches_practices(monkeypatch):
    monkeypatch.setattr(nhsbsa, "latest_resource", lambda s, p, prefix: prefix + "202608")
    monkeypatch.setattr(nhsbsa, "sql", fake_sql({
        "LIKE '0403%'": [{"PRACTICE_CODE": "P1", "items": 100}, {"PRACTICE_CODE": "P2", "items": 50},
                         {"PRACTICE_CODE": "P9", "items": 999}],  # P9: no list size, so excluded
    }))
    frames, month = nhsbsa.load_prescribing(None, {"P1": "E1", "P2": "E1", "P3": "E2", "P9": "E2"},
                                            pd.Series({"P1": 1000.0, "P2": 1000.0, "P3": 500.0}))
    assert month == "2026-08"
    f = frames["rx_antidepressants"]
    assert (f["num"] / f["den"]).to_dict() == pytest.approx({"E1": 75.0, "E2": 0.0})
    assert set(frames) == set(nhsbsa.PRESCRIBING)


def test_dental_counts_by_lsoa(monkeypatch):
    monkeypatch.setattr(nhsbsa, "latest_resource", lambda s, p, prefix: prefix + "202607")
    monkeypatch.setattr(nhsbsa, "sql", fake_sql({"ADULT_24M_COUNT": [
        {"LSOA21_CODE": "L1", "ADULT_24M_COUNT": "300", "CHILD_12M_COUNT": "100"},
        {"LSOA21_CODE": "L2", "ADULT_24M_COUNT": "100", "CHILD_12M_COUNT": ""},
        {"LSOA21_CODE": "Lx", "ADULT_24M_COUNT": "999", "CHILD_12M_COUNT": "999"},  # not in the lookup
    ]}))
    frames, _ = nhsbsa.load_dental(None, {"L1": "E1", "L2": "E1"}, pd.Series({"E1": 2000.0, "E2": 1000.0, "W3": 500.0}))
    a = frames["dental_adults_per_1k"]
    assert (a["num"] / a["den"]).to_dict() == pytest.approx({"E1": 200.0, "E2": 0.0})  # England only
    c = frames["dental_children_per_1k"]
    assert (c["num"] / c["den"]).loc["E1"] == pytest.approx(50.0)
