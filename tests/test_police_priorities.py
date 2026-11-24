import pytest
from shapely.geometry import box, mapping

from datadash.sources import police_priorities as pp


def test_points_spread_inside_the_seat():
    seat = box(0, 0, 4, 1)
    pts = pp.sample_points(seat, 6)
    assert len(pts) == 6 and all(seat.contains(p) for p in pts)
    assert max(p.x for p in pts) - min(p.x for p in pts) > 2.5  # spread along the seat, not bunched


def test_priority_text_made_plain():
    raw = "<p><ul><li>Drug dealing at Prewett Street &amp; Somerset Square.</li><li>Anti-social behaviour</li></ul></p>"
    assert pp.plain(raw) == "Drug dealing at Prewett Street & Somerset Square; Anti-social behaviour"
    assert pp.plain("<p>.</p>") == "" and pp.plain(None) == ""
    assert pp.plain("DANGEROUS &amp; ANTISOCIAL DRIVING") == "Dangerous & antisocial driving"
    assert pp.plain("ASB in the CCTV area") == "ASB in the CCTV area"  # ordinary text keeps its capitals
    assert pp.plain("word " * 100).endswith("…") and len(pp.plain("word " * 100)) <= pp.MAX_CHARS + 1


def test_newest_priorities_kept():
    raw = [{"issue": "<p>Old one</p>", "issue-date": "2025-01-01T00:00:00"},
           {"issue": "<p>Shop theft</p>", "action": "<p>.</p>", "issue-date": "2026-11-12T00:00:00"},
           {"issue": "<p>Speeding</p>", "action": "<p>Speed checks weekly</p>", "issue-date": "2026-10-01T00:00:00"},
           {"issue": "<p>x</p>", "issue-date": "2026-12-01T00:00:00"},
           {"issue": "<p>Burglary</p>", "issue-date": "2026-09-01T00:00:00"}]
    assert pp.priorities(raw) == [{"issue": "Shop theft", "date": "2026-11-12"},
                                  {"issue": "Speeding", "date": "2026-10-01"},  # actions left out
                                  {"issue": "Burglary", "date": "2026-09-01"}]


def test_teams_found_across_each_seat(monkeypatch):
    # 120 seats in a row; each seat's west half is team A1, east half team A2 of "kent"; one Scottish seat is skipped.
    feats = [{"type": "Feature", "properties": {"code": f"E14{i:06d}"}, "geometry": mapping(box(i, 0, i + 1, 1))} for i in range(120)]
    feats.append({"type": "Feature", "properties": {"code": "S14000001"}, "geometry": mapping(box(500, 0, 501, 1))})
    calls = []

    def get(self, path, **params):
        calls.append(path)
        if path == "forces":
            return [{"id": "kent", "name": "Kent Police"}]
        if path == "locate-neighbourhood":
            lat, lng = map(float, params["q"].split(","))
            return {"force": "kent", "neighbourhood": f"T{int(lng)}{'A' if lng % 1 < 0.5 else 'B'}"}
        if path.endswith("/priorities"):
            return [{"issue": f"<p>Priority for {path.split('/')[1]}</p>", "issue-date": "2026-11-01T00:00:00"}]
        if path == "kent/neighbourhoods":
            return [{"id": f"T{i}{h}", "name": f"Team T{i}{h}"} for i in range(120) for h in "AB"]
        raise AssertionError(f"unexpected request {path}")

    monkeypatch.setattr(pp._Api, "get", get)
    monkeypatch.setattr(pp._RateLimiter, "wait", lambda self: None)
    out = pp.load_priorities(None, {"features": feats}, workers=4)["seats"]
    assert len(out) == 120 and "S14000001" not in out
    first = out["E14000000"]
    assert {t["team"] for t in first} == {"Team T0A", "Team T0B"}
    assert first[0] == {"force": "Kent Police", "team": first[0]["team"],
                        "priorities": [{"issue": f"Priority for {first[0]['team'][5:]}", "date": "2026-11-01"}]}
    assert calls.count("kent/neighbourhoods") == 1  # names: one request per force, not per team
    assert not any(c.startswith("S") for c in calls)


def test_too_few_seats_is_a_failure(monkeypatch):
    monkeypatch.setattr(pp._Api, "get", lambda self, path, **p: [] if path == "forces" else None)
    monkeypatch.setattr(pp._RateLimiter, "wait", lambda self: None)
    feats = [{"type": "Feature", "properties": {"code": "E14000001"}, "geometry": mapping(box(0, 0, 1, 1))}]
    with pytest.raises(RuntimeError):
        pp.load_priorities(None, {"features": feats})


class _Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise pp.requests.HTTPError(str(self.status_code))


def _api(monkeypatch, replies, budget=20):
    monkeypatch.setattr(pp.time, "sleep", lambda s: None)
    api = pp._Api(None, budget)
    it = iter(replies)
    api.s.get = lambda url, params=None, timeout=None: next(it)
    return api


def test_slows_down_when_police_uk_says_too_many_requests(monkeypatch):
    api = _api(monkeypatch, [_Resp(429), _Resp(429), _Resp(200, {"ok": 1})])
    before = api.rl.interval
    assert api.get("forces") == {"ok": 1}
    assert api.rl.interval == pytest.approx(before * 1.5 * 1.5)  # every 429 slows all requests down


def test_gives_up_on_a_request_after_a_few_refusals(monkeypatch):
    api = _api(monkeypatch, [_Resp(429)] * 4)
    with pytest.raises(pp.requests.HTTPError):
        api.get("forces")


def test_stops_at_the_time_budget(monkeypatch):
    # The live refresh of 24 Nov ran into the workflow's 90-minute limit; now the step stops itself first.
    api = _api(monkeypatch, [_Resp(200, [])], budget=0)
    with pytest.raises(pp.OutOfTime):
        api.get("forces")
