import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from whips import engine
from whips.demo import build_demo


def tiny():
    seats = [{"code": c, "name": c.lower(), "country": "England", "region": r}
             for c, r in [("A", "North"), ("B", "North"), ("C", "South"), ("D", "South"), ("E", "South")]]
    metrics = [{"id": m, "label": m, "unit": "%", "tags": ["census"], "national": None} for m in ("x", "y")]
    values = {"x": [10, 11, 30, 31, None], "y": [50, 52, 20, 21, 40]}
    return engine.Dataset.from_json({"seats": seats, "metrics": metrics, "values": values})


def test_rank_handles_missing_and_ties():
    ds = tiny()
    r = ds.rank("x", "D")
    assert r == {"value": 31.0, "rank": 1, "of": 4, "percentile": 100.0}
    assert ds.rank("x", "E")["rank"] is None


@pytest.mark.parametrize("method", ["euclidean", "cosine"])
def test_twins_finds_nearest(method):
    ds = tiny()
    out = engine.twins(ds, "A", method=method, top_n=2)
    assert out[0]["code"] == "B"
    assert all(o["code"] not in ("A", "E") for o in out)  # self and incomplete excluded


def test_twins_region_filter():
    out = engine.twins(tiny(), "A", region="South", top_n=5)
    assert {o["code"] for o in out} == {"C", "D"}


def test_composite_index_signs():
    ds = tiny()
    up = engine.composite_index(ds, {"x": 1})
    assert up[0]["code"] == "D" and up[0]["rank"] == 1
    down = engine.composite_index(ds, {"x": -1})
    assert down[0]["code"] == "A"
    with pytest.raises(ValueError):
        engine.composite_index(ds, {"x": 0})


def test_kmeans_separates_clusters():
    Z = np.vstack([np.random.default_rng(1).normal(0, 0.1, (20, 2)), np.random.default_rng(2).normal(5, 0.1, (20, 2))])
    labels, _ = engine.kmeans(Z, 2)
    assert len(set(labels[:20])) == 1 and len(set(labels[20:])) == 1 and labels[0] != labels[-1]


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    build_demo(out)
    return out


def test_demo_build_outputs(demo):
    data = json.loads((demo / "data.json").read_text())
    assert data["demo"] is True
    assert len(data["seats"]) == 650
    for m in data["metrics"]:
        assert len(data["values"][m["id"]]) == 650
    assert sum(g["size"] for g in data["peer_groups"]) == sum(s["peer_group"] is not None for s in data["seats"])
    geo = json.loads((demo / "boundaries.geojson").read_text())
    assert len(geo["features"]) == 650
    assert (demo / "constituencies.csv").exists()


def test_api(demo, monkeypatch):
    from whips import api
    monkeypatch.setenv("WHIPS_DATA", str(demo / "data.json"))
    api.dataset.cache_clear()
    c = TestClient(api.app)
    assert c.get("/api/v1/constituencies/DEMO-001").json()["metrics"]["private_rented"]["of"] > 0
    tw = c.get("/api/v1/twins/DEMO-001?top_n=5").json()
    assert len(tw) == 5
    idx = c.post("/api/v1/index", json={"private_rented": 0.5, "level4_plus": 0.5}).json()
    assert idx[0]["rank"] == 1
    assert c.get("/api/v1/constituencies/NOPE").status_code == 404
    api.dataset.cache_clear()
