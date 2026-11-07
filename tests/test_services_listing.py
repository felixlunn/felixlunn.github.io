from whips.sources import lsoa


def test_service_listing_combines_incomplete_responses(monkeypatch):
    listings = iter([["A", "B"], ["A", "C"], ["B"]])
    calls = []

    def fake_get_json(s, url, params=None):
        calls.append(url)
        return {"services": [{"name": n, "type": "FeatureServer"} for n in next(listings)] + [{"name": "M", "type": "MapServer"}]}

    monkeypatch.setattr(lsoa, "get_json", fake_get_json)
    monkeypatch.setattr(lsoa, "_SERVICE_CACHE", set())
    assert lsoa._services(None) == ["A", "B", "C"]
    assert lsoa._services(None) == ["A", "B", "C"] and len(calls) == 3  # cached after the first call
