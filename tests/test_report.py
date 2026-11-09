from whips.report import failed_sources, markdown


def test_lists_only_failed_sources():
    data = {"sources": [{"id": "a", "name": "A", "status": "ok", "detail": ""},
                        {"id": "b", "name": "B source", "status": "failed", "detail": "404 Not Found"}]}
    failed = failed_sources(data)
    assert [s["id"] for s in failed] == ["b"]
    assert markdown(failed) == "- **B source** (`b`): 404 Not Found"
    assert markdown([]) == ""


def test_flags_figures_that_vanished_or_shrank():
    from whips.report import lost_data
    old = {"metrics": [{"id": "a", "label": "A", "coverage": 500}, {"id": "b", "label": "B", "coverage": 500},
                       {"id": "c", "label": "C", "coverage": 500}]}
    new = {"metrics": [{"id": "a", "label": "A", "coverage": 495}, {"id": "b", "label": "B", "coverage": 300}]}
    out = lost_data(new, old)
    assert len(out) == 2 and "covers 300 seats, down from 500" in out[0] and "no longer produced" in out[1]
