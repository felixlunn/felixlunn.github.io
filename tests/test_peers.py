import json

import numpy as np
import pytest

from whips import peers
from whips.demo import build_demo


def test_groups_seats_on_their_census_profile():
    seats = [{"code": c} for c in "ABCDEFGH"]
    metrics = [{"id": m, "label": m.upper(), "unit": "%", "tags": ["census"]} for m in ("x", "y")]
    metrics.append({"id": "z", "label": "Z", "unit": "count", "tags": []})  # not census: ignored
    values = {"x": [10, 11, 12, 30, 31, 32, None, 11], "y": [50, 52, 51, 20, 21, 22, 40, 50], "z": [1] * 8}
    groups, meta = peers.peer_groups(seats, metrics, values, k=2)
    assert groups[6] is None  # incomplete profile
    assert len({groups[i] for i in (0, 1, 2, 7)}) == 1 and len({groups[i] for i in (3, 4, 5)}) == 1 and groups[0] != groups[3]
    assert [g["size"] for g in meta] == [4, 3] and meta[0]["label"] == "Group A"  # largest first
    assert "above average on Y" in meta[0]["description"]


def test_kmeans_separates_clusters():
    Z = np.vstack([np.random.default_rng(1).normal(0, 0.1, (20, 2)), np.random.default_rng(2).normal(5, 0.1, (20, 2))])
    labels, _ = peers.kmeans(Z, 2)
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
