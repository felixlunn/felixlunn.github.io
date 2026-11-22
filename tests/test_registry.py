import pandas as pd
import pytest

from whips import registry
from whips.context import BuildContext
from whips.metrics import CENSUS_METRICS, MetricMeta
from whips.registry import SOURCES, Source


def test_ids_skips_and_metrics_are_consistent():
    ids = [s.id for s in SOURCES]
    assert len(ids) == len(set(ids))
    metric_ids = [m.id for m in registry.all_metrics()] + [m.id for m in CENSUS_METRICS]
    assert len(metric_ids) == len(set(metric_ids)), "a metric id is defined twice"
    for s in SOURCES:
        assert s.stage in ("required", "main", "post")
        if s.stage == "main":
            assert (s.load is None) != (s.run is None), f"{s.id}: needs exactly one of load / run"
        assert s.keep is None or s.keep > 0
        assert s.every is None or s.every > 0
    assert "lsoa" in registry.skip_names() and "boundaries" not in registry.skip_names()
    assert registry.BY_ID["gias"].skip_name == registry.BY_ID["ks4"].skip_name == "schools"


def test_code_files_follow_direct_imports():
    files = {p.name for p in registry.code_files("whips.sources.courts")}
    assert {"courts.py", "councils.py", "lsoa.py", "boundaries.py", "http.py", "metrics.py"} <= files
    assert "rail.py" not in files


def ctx():
    c = BuildContext(s=None, out_dir=None, skip=set())
    c.fetch = lambda sid, load, keep, files: load()  # no cache
    return c


M = MetricMeta("x_rate", "X", "economy", "%", "", "Test source", "higher_worse", 1, ())


def test_generic_run_records_success_and_detail():
    c = ctx()
    frame = pd.DataFrame({"num": [1.0], "den": [2.0]}, index=["E1"])
    c.run(Source("x", "X source", "https://x", "default detail", (M,), lambda c: ({"x_rate": frame}, "2025")))
    c.run(Source("y", "Y source", "https://y", "default", (), lambda c: ({}, "2026", "custom detail")))
    assert c.sources == [
        {"id": "x", "name": "X source", "url": "https://x", "status": "ok", "detail": "default detail", "as_of": "2025"},
        {"id": "y", "name": "Y source", "url": "https://y", "status": "ok", "detail": "custom detail", "as_of": "2026"},
    ]
    assert c.metas == [M] and "x_rate" in c.frames


def test_generic_run_records_failures_and_empty_results():
    c = ctx()

    def boom(c):
        raise RuntimeError("site down")
    c.run(Source("a", "A", "u", "", (M,), boom))
    c.run(Source("b", "B", "u", "", (M,), lambda c: ({"x_rate": pd.DataFrame()}, "2025")))
    assert [(s["id"], s["status"], s["detail"]) for s in c.sources] == [("a", "failed", "site down"), ("b", "failed", "no data returned")]
    assert c.metas == []


def test_when_and_custom_run():
    c = ctx()
    c.run(Source("q", "Q", "u", "", (M,), lambda c: pytest.fail("should not load"), when=lambda c: False))
    c.run(Source("r", "R", "u", run=lambda c, src: c.record(src.id, src.name, src.url, "ok")))
    assert [s["id"] for s in c.sources] == ["r"]
