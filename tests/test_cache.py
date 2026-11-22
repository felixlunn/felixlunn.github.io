import pytest

from datadash import cache


def test_reuses_recent_copy_then_refetches(tmp_path):
    calls = []
    load = lambda: calls.append(1) or len(calls)  # noqa: E731
    assert cache.cached("x", load, str(tmp_path), now=0, max_age_days=5) == 1
    assert cache.cached("x", load, str(tmp_path), now=4 * 86400, max_age_days=5) == 1      # still fresh: not fetched again
    assert cache.cached("x", load, str(tmp_path), now=6 * 86400, max_age_days=5) == 2      # too old: fetched


def test_failed_update_falls_back_to_saved_copy_and_is_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "STALE", {})
    cache.cached("x", lambda: "old", str(tmp_path), now=0, max_age_days=1)

    def boom():
        raise RuntimeError("site down")
    assert cache.cached("x", boom, str(tmp_path), now=3 * 86400, max_age_days=1) == "old"
    assert "site down" in cache.STALE["x"] and "1 January 1970" in cache.STALE["x"]
    with pytest.raises(RuntimeError):  # nothing saved for this one: the failure is raised
        cache.cached("y", boom, str(tmp_path), now=0, max_age_days=1)


def test_code_change_discards_saved_copies(tmp_path):
    a, b = tmp_path / "a.py", tmp_path / "b.py"
    a.write_text("x = 1")
    b.write_text("y = 1")
    cache.cached("x", lambda: "old", str(tmp_path), now=0, max_age_days=5, code_files=[a, b])
    b.write_text("y = 2")  # a change to code this source doesn't use would be ignored; this one it uses
    assert cache.cached("x", lambda: "new", str(tmp_path), now=1, max_age_days=5, code_files=[a, b]) == "new"


def test_only_its_own_code_matters(tmp_path):
    a, other = tmp_path / "a.py", tmp_path / "other.py"
    a.write_text("x = 1")
    other.write_text("z = 1")
    cache.cached("x", lambda: "old", str(tmp_path), now=0, max_age_days=5, code_files=[a])
    other.write_text("z = 2")
    assert cache.cached("x", lambda: "new", str(tmp_path), now=1, max_age_days=5, code_files=[a]) == "old"


def test_off_without_folder_or_keep_period(tmp_path, monkeypatch):
    monkeypatch.delenv("DATADASH_SOURCE_CACHE", raising=False)
    n = iter(range(10))
    assert [cache.cached("x", lambda: next(n), max_age_days=5), cache.cached("x", lambda: next(n), max_age_days=5)] == [0, 1]
    assert [cache.cached("y", lambda: next(n), str(tmp_path)), cache.cached("y", lambda: next(n), str(tmp_path))] == [2, 3]
