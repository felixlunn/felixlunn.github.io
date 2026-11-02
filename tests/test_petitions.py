import pandas as pd
import pytest

from whips.sources import petitions as P


def test_summarise_rates_top_and_over_represented():
    petitions = [{"id": 1, "title": "Big national", "signatures": 3000}, {"id": 2, "title": "Local issue", "signatures": 300}]
    counts = {1: {"E1": 1000, "E2": 2000}, 2: {"E1": 290, "E2": 10}}
    electorate = pd.Series({"E1": 50_000.0, "E2": 50_000.0})
    frame, brief = P.summarise(petitions, counts, electorate)
    assert (frame["num"] / frame["den"]).to_dict() == pytest.approx({"E1": 1290 * 1000 / 50_000, "E2": 2010 * 1000 / 50_000})
    e1 = brief["by_seat"]["E1"]
    assert [t[:2] for t in e1["top"]] == [[0, 1000], [1, 290]]
    # Petition 2: E1 has 290 of 300 signatures but half the electorate -> index 290 / 150
    assert e1["local"] == [[1, 290, pytest.approx(290 / 150, abs=0.01)]]
    assert brief["by_seat"]["E2"]["local"] == []  # nothing over-represented enough
    assert brief["items"][1]["url"].endswith("/petitions/2")
