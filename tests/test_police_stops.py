from collections import Counter

import pandas as pd

from datadash.sources import police_stops as ps


def test_months_with_stop_and_search_and_who_published():
    dates = [{"date": "2026-09", "stop-and-search": ["kent", "dorset"]}, {"date": "2026-10", "stop-and-search": []},
             {"date": "2026-08", "stop-and-search": ["kent"]}, {"date": "2026-07", "stop-and-search": ["kent", "dorset"]}]
    months, published = ps.stop_months(dates, 2)
    assert months == ["2026-09", "2026-08"]  # October has none yet
    assert published == {"2026-09": {"kent", "dorset"}, "2026-08": {"kent"}}


def test_outcomes():
    assert ps.outcome_bucket({"outcome": "Arrest", "outcome_object": {"id": "bu-arrest"}}) == "arrest"
    assert ps.outcome_bucket({"outcome": "A no further action disposal", "outcome_object": {"id": "bu-no-further-action"}}) == "no_action"
    assert ps.outcome_bucket({"outcome": "Community resolution", "outcome_object": {"id": "bu-community-resolution"}}) == "other"
    assert ps.outcome_bucket({"outcome": None}) == "other"
    assert ps.summarise([{"outcome": "Arrest"}, {"outcome": "A no further action disposal"}]) == Counter(arrest=1, no_action=1, all=2)


def test_seats_of_forces_not_publishing_are_left_blank():
    counts = {"A": Counter(all=60, no_action=45, arrest=6), "B": Counter(all=5, no_action=5), "C": Counter(),
              "D": Counter(all=30, no_action=10, arrest=3)}
    forces = {"A": "kent", "B": "kent", "C": "greater-manchester", "D": "metropolitan"}  # GMP doesn't publish
    months = ["2026-09", "2026-08", "2026-07", "2026-06", "2026-05", "2026-04"]
    published = {m: {"kent"} | ({"metropolitan"} if m != "2026-08" else set()) for m in months}  # the Met missed a month
    out, blank = ps.seat_frames(counts, forces, published, pd.Series({"A": 100_000.0, "B": 50_000.0, "C": 80_000.0, "D": 50_000.0}))
    val = {k: (v["num"] / v["den"]).round(2).to_dict() for k, v in out.items()}
    assert blank == ["C"]
    # A: 60 stops in 6 months -> 120 a year per 100,000 -> 1.2 per 1,000. D: 30 in the Met's 5 months -> 72 a year.
    assert val["stops_per_1k"] == {"A": 1.2, "B": 0.2, "D": 1.44}
    assert val["stops_no_action"] == {"A": 75.0, "D": 33.33}  # B has too few stops for shares
    assert val["stops_arrest"] == {"A": 10.0, "D": 10.0}


def test_too_few_months_published_is_blank():
    published = {m: ({"kent"} if m in ("2026-09", "2026-08") else set()) for m in ["2026-09", "2026-08", "2026-07", "2026-06"]}
    out, blank = ps.seat_frames({"A": Counter(all=40)}, {"A": "kent"}, published, pd.Series({"A": 100_000.0}))
    assert blank == ["A"] and out["stops_per_1k"].empty
