

def test_unpublished_forces_are_blank_not_zero():
    import pandas as pd
    from whips.sources.police import unpublished
    rate = pd.Series({"A": 80.0, "B": 95.0, "C": 70.0, "GMP1": 0.0, "GMP2": 4.0, "Quiet": 30.0})
    assert unpublished(rate) == ["GMP1", "GMP2"]
