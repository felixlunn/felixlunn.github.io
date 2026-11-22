import re

from datadash import arcgis


def fake(monkeypatch, listings):
    it, calls = iter(listings), []

    def get_json(s, url, params=None):
        calls.append(url)
        return {"services": [{"name": n, "type": "FeatureServer"} for n in next(it, [])] + [{"name": "M", "type": "MapServer"}]}

    monkeypatch.setattr(arcgis, "get_json", get_json)
    monkeypatch.setattr(arcgis, "_SERVICES", set())
    monkeypatch.setattr(arcgis.time, "sleep", lambda _: None)
    return calls


def test_service_listing_combines_incomplete_responses(monkeypatch):
    calls = fake(monkeypatch, [["A", "B"], ["A", "C"], ["B"]])
    assert arcgis.services(None) == ["A", "B", "C"]
    assert arcgis.services(None) == ["A", "B", "C"] and len(calls) == 3  # cached after the first call


def test_listing_again_until_a_wanted_service_appears(monkeypatch):
    # The 20 Nov 2026 failure: several listings in a row left out the police force areas.
    calls = fake(monkeypatch, [["A"], ["A"], ["A"], ["A"], ["Police_Force_Areas_Dec_2024_EW_BUC"]])
    names = arcgis.services(None, re.compile(r"^Police_Force_Areas_"))
    assert "Police_Force_Areas_Dec_2024_EW_BUC" in names and len(calls) == 5


def test_gives_up_after_the_limit(monkeypatch):
    calls = fake(monkeypatch, [["A"]] * 20)
    assert arcgis.services(None, re.compile("never")) == ["A"]
    assert len(calls) == arcgis.MAX_LISTINGS
