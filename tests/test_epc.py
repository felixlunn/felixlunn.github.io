from datetime import date

import pandas as pd
import pytest

from whips.sources import epc


class Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    """Answers like the API: totalRecords per (constituency, band); 404 when none."""
    def __init__(self, table):
        self.table, self.calls = table, []

    def get(self, url, timeout, headers, params):
        self.calls.append(params)
        n = self.table.get((params["constituency[]"], params["efficiency_rating[]"]), 0)
        if not n:
            return Resp(404)
        return Resp(200, {"data": [{}], "pagination": {"totalRecords": n, "currentPage": 1}})


def test_load_epc_counts_bands_and_shares(monkeypatch):
    monkeypatch.setenv("EPC_TOKEN", "t")
    table = {("Seat A", "B"): 10, ("Seat A", "C"): 30, ("Seat A", "D"): 40, ("Seat A", "F"): 15, ("Seat A", "G"): 5}
    s = FakeSession(table)
    frames, period = epc.load_epc(s, {"E1": "Seat A ", "S9": "Scottish seat", "W2": "Seat B"}, today=date(2026, 11, 1), workers=1)
    val = lambda mid, c: frames[mid].loc[c, "num"] / frames[mid].loc[c, "den"]  # noqa: E731
    assert val("epc_a_c", "E1") == pytest.approx(40.0)
    assert val("epc_f_g", "E1") == pytest.approx(20.0)
    assert pd.isna(frames["epc_a_c"].loc["W2", "den"])  # no certificates: no value, not 0%
    assert "S9" not in frames["epc_a_c"].index  # Scotland isn't covered
    assert {c["constituency[]"] for c in s.calls} == {"Seat A", "Seat B"}  # names trimmed
    assert s.calls[0]["date_end"] == "2026-10-31" and s.calls[0]["date_start"] == "2016-10-31"
    assert period == "2016-10-31 to 2026-10-31"


def test_load_epc_needs_token(monkeypatch):
    monkeypatch.delenv("EPC_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="EPC_TOKEN"):
        epc.load_epc(FakeSession({}), {"E1": "Seat A"})
