from datetime import date

from whips import freshness, report


def src(sid, as_of, status="ok", **kw):
    return {"id": sid, "name": sid.title(), "url": "https://example.org", "status": status, "detail": "", "as_of": as_of, **kw}


def test_since_carries_forward_until_the_period_changes():
    prev = {"sources": [src("police", "2026-07 to 2026-09", since="2026-10-20"), src("ashe", "2025", since="2025-11-01")]}
    now = [src("police", "2026-08 to 2026-10"), src("ashe", "2025"), src("rents", "October 2026")]
    freshness.stamp(now, prev, date(2026, 11, 20))
    assert now[0]["since"] == "2026-11-20"  # new period: counted from today
    assert now[1]["since"] == "2025-11-01"  # same period: date carried forward
    assert now[2]["since"] == "2026-11-20"  # new source
    assert not any(s["overdue"] for s in now)  # 384 days < annual allowance


def test_overdue_after_the_usual_cycle_and_failures_keep_their_date():
    prev = {"sources": [src("claimants", "August 2026", since="2026-09-15"), src("courts", "Q2", since="2026-01-01")]}
    now = [src("claimants", "August 2026"), src("courts", None, status="failed"), src("census", "March 2021")]
    freshness.stamp(now, prev, date(2026, 11, 20))
    assert now[0]["overdue"] is True  # monthly series unchanged for 66 days
    assert now[1]["since"] == "2026-01-01" and now[1]["overdue"] is True
    assert now[2]["overdue"] is False  # never changes: not tracked
    out = report.overdue_sources({"sources": now})
    assert [s["id"] for s in out] == ["claimants"]  # failed sources are reported as failures instead


def test_report_lists_overdue_sources(tmp_path, capsys):
    import json
    p = tmp_path / "data.json"
    p.write_text(json.dumps({"sources": [src("claimants", "August 2026", since="2026-09-15", overdue=True)]}))
    report.main([str(p)])
    out = capsys.readouterr().out
    assert "longer than usual" in out and "Claimants" in out and "since 2026-09-15" in out
