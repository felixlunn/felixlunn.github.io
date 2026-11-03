import pandas as pd
import pytest

from whips.sources.children import councils_frame, education_weights


def test_councils_frame_drops_tiny_returns_and_sets_national():
    d = pd.DataFrame({"level": ["LA", "LA", "NAT"], "code": ["E10000020", "E06000001", "E92000001"],
                      "num": [0.0, 30.0, 50.0], "den": [1.0, 60.0, 100.0]}).set_index(["level", "code"])
    w = pd.DataFrame({"pcon": ["A", "B"], "lad": ["E10000020", "E06000001"], "n": [1, 1], "of_seat": [1.0, 1.0],
                      "of_council": [1.0, 1.0]})
    f = councils_frame(d, w, min_den=20)
    assert (f["num"] / f["den"]).to_dict() == pytest.approx({"B": 50.0})
    assert f.attrs["national"] == pytest.approx(50.0)


def test_education_weights_join_districts_to_counties_only():
    w = pd.DataFrame({"pcon": ["A", "A", "B"], "lad": ["E07000001", "E07000002", "E08000001"], "n": [1, 2, 3]})
    out = education_weights(w, {"E07000001": "E10000001", "E07000002": "E10000001", "E08000001": "E11000001"})
    assert set(zip(out["pcon"], out["lad"], out["n"])) == {("A", "E10000001", 3), ("B", "E08000001", 3)}
