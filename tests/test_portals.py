"""The shared ONS ArcGIS and GOV.UK helpers."""

import pytest

from whips import arcgis, govuk


def test_features_follows_pagination(monkeypatch):
    pages = [
        {"features": [{"attributes": {"A": 1}}, {"attributes": {"A": 2}}], "exceededTransferLimit": True},
        {"features": [{"attributes": {"A": 3}}]},
    ]
    calls = []

    def get_json(s, url, params=None, timeout=None):
        calls.append((url, dict(params)))
        return pages[len(calls) - 1]

    monkeypatch.setattr(arcgis, "get_json", get_json)
    assert arcgis.rows(None, arcgis.layer("Svc")) == [{"A": 1}, {"A": 2}, {"A": 3}]
    assert calls[0][0] == f"{arcgis.ROOT}/Svc/FeatureServer/0/query"
    assert [c[1]["resultOffset"] for c in calls] == [0, 2]
    assert calls[0][1]["returnGeometry"] == "false" and calls[0][1]["f"] == "json"


def test_geojson_pages_flag_truncation_in_properties(monkeypatch):
    pages = [
        {"features": [{"properties": {"X": 1}}], "properties": {"exceededTransferLimit": True}},
        {"features": [{"properties": {"X": 2}}], "properties": {}},
        {"features": [{"properties": {"X": 3}}]},  # never reached
    ]
    calls = []

    def get_json(s, url, params=None, timeout=None):
        calls.append(params)
        return pages[len(calls) - 1]

    monkeypatch.setattr(arcgis, "get_json", get_json)
    out = arcgis.features(None, "L", where="X > 0", fields="X", geojson=True)
    assert [f["properties"]["X"] for f in out] == [1, 2]
    assert calls[0]["f"] == "geojson" and calls[0]["outSR"] == "4326" and calls[0]["where"] == "X > 0"


def test_first_layer_is_not_always_zero(monkeypatch):
    monkeypatch.setattr(arcgis, "get_json", lambda s, url, params=None: {"layers": [{"id": 3}]})
    assert arcgis.first_layer(None, "LSOA_BFE").endswith("/LSOA_BFE/FeatureServer/3")


def test_field_matches_any_year():
    row = {"lad23cd": "E06000001", "LAD23NM": "Hartlepool"}
    assert arcgis.field(row, r"LAD\d{2}CD") == "E06000001"
    assert arcgis.field(row, r"CTY\d{2}CD") is None


def test_round_coords():
    assert arcgis.round_coords([[[-1.123456, 51.987654]]], 3) == [[[-1.123, 51.988]]]


@pytest.mark.parametrize("page", [
    "/government/collections/x",
    "https://www.gov.uk/government/collections/x",
    "https://www.gov.uk/api/content/government/collections/x",
])
def test_govuk_pages_named_any_way(page):
    assert govuk.api_url(page) == "https://www.gov.uk/api/content/government/collections/x"


def test_govuk_rejects_other_sites():
    with pytest.raises(ValueError):
        govuk.api_url("https://example.org/x")


def test_govuk_attachments_documents_and_search(monkeypatch):
    seen = []

    def get_json(s, url, params=None, **kw):
        seen.append((url, params))
        if url == govuk.SEARCH:
            return {"results": [{"link": "/government/statistics/a"}]}
        return {"details": {"attachments": [{"url": "f.xlsx"}]}, "links": {"documents": [{"base_path": "/b"}]}}

    monkeypatch.setattr(govuk, "get_json", get_json)
    assert govuk.attachments(None, "/government/statistics/a") == [{"url": "f.xlsx"}]
    assert govuk.documents(None, "/government/collections/c") == [{"base_path": "/b"}]
    assert govuk.search(None, "trust catchments", count=5) == [{"link": "/government/statistics/a"}]
    assert seen[-1] == (govuk.SEARCH, {"q": "trust catchments", "count": 5})
    # Missing sections read as empty, not errors.
    monkeypatch.setattr(govuk, "get_json", lambda s, url, **kw: {})
    assert govuk.attachments(None, "/x") == [] and govuk.documents(None, "/x") == []
