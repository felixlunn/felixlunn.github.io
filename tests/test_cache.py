import pytest

from whips import cache


def test_reuses_recent_copy_then_refetches(tmp_path, monkeypatch):
    monkeypatch.setitem(cache.MAX_AGE_DAYS, "x", 5)
    calls = []
    load = lambda: calls.append(1) or len(calls)  # noqa: E731
    assert cache.cached("x", load, str(tmp_path), now=0) == 1
    assert cache.cached("x", load, str(tmp_path), now=4 * 86400) == 1      # still fresh: not fetched again
    assert cache.cached("x", load, str(tmp_path), now=6 * 86400) == 2      # too old: fetched


def test_failed_update_falls_back_to_saved_copy_and_is_flagged(tmp_path, monkeypatch):
    monkeypatch.setitem(cache.MAX_AGE_DAYS, "x", 1)
    monkeypatch.setattr(cache, "STALE", {})
    cache.cached("x", lambda: "old", str(tmp_path), now=0)

    def boom():
        raise RuntimeError("site down")
    assert cache.cached("x", boom, str(tmp_path), now=3 * 86400) == "old"
    assert "site down" in cache.STALE["x"] and "1 January 1970" in cache.STALE["x"]
    with pytest.raises(RuntimeError):  # nothing saved for this one: the failure is raised
        cache.cached("y", boom, str(tmp_path), now=0) if not monkeypatch.setitem(cache.MAX_AGE_DAYS, "y", 1) else None


def test_code_change_discards_saved_copies(tmp_path, monkeypatch):
    monkeypatch.setitem(cache.MAX_AGE_DAYS, "x", 5)
    cache.cached("x", lambda: "old", str(tmp_path), now=0)
    monkeypatch.setattr(cache, "_code_version", lambda: "different")
    assert cache.cached("x", lambda: "new", str(tmp_path), now=1) == "new"


def test_off_without_folder_and_for_unlisted_sources(tmp_path, monkeypatch):
    monkeypatch.delenv("WHIPS_SOURCE_CACHE", raising=False)
    monkeypatch.setitem(cache.MAX_AGE_DAYS, "x", 5)
    n = iter(range(10))
    assert [cache.cached("x", lambda: next(n)), cache.cached("x", lambda: next(n))] == [0, 1]
    assert [cache.cached("unlisted", lambda: next(n), str(tmp_path)), cache.cached("unlisted", lambda: next(n), str(tmp_path))] == [2, 3]
