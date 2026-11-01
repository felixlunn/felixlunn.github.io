from datetime import date

import pytest

from whips.sources import questions


class FakeSession:
    def __init__(self, counts):
        self.counts, self.params = counts, []

    def get(self, url, timeout, params):
        self.params.append(params)
        n = self.counts[params["askingMemberId"]]

        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"totalResults": n, "results": []}
        return R()


def test_counts_per_seat_since_a_year_ago():
    s = FakeSession({11: 120, 22: 0})
    f, period = questions.load_questions(s, {"E1": {"mp_id": 11}, "E2": {"mp_id": 22}, "E3": {"mp": "Vacant"}},
                                         today=date(2026, 11, 1), workers=1)
    q = f["wq_last_year"]
    assert (q["num"] / q["den"]).to_dict() == {"E1": 120, "E2": 0}
    assert {p["tabledWhenFrom"] for p in s.params} == {"2025-11-01"} and period == "Tabled since 2025-11-01"


def test_no_members():
    with pytest.raises(ValueError):
        questions.load_questions(FakeSession({}), {})
