import pandas as pd
import pytest

from whips.sources import imd


def file7():
    # Headers as published in File 7 (IoD 2025).
    return pd.DataFrame({
        "LSOA code (2021)": ["A1", "A2", "B1"],
        "LSOA name (2021)": ["x", "y", "z"],
        "Index of Multiple Deprivation (IMD) Score": [40.0, 10.0, 20.0],
        "Index of Multiple Deprivation (IMD) Rank (where 1 is most deprived)": [1, 3, 2],
        "Index of Multiple Deprivation (IMD) Decile (where 1 is most deprived 10% of LSOAs)": [1, 9, 2],
        "Income Score (rate)": [0.5, 0.1, 0.2],
        "Employment Score (rate)": [0.3, 0.1, 0.2],
        "Income Deprivation Affecting Children Index (IDACI) Score (rate)": [0.6, 0.2, 0.3],
        "Income Deprivation Affecting Older People (IDAOPI) Score (rate)": [0.4, 0.1, 0.2],
        "Total population: mid 2022": [1000, 3000, 2000],
        "Dependent Children aged 0-15: mid 2022": [300, 300, 400],
        "Older population aged 60 and over: mid 2022": [100, 900, 500],
        "Working age population 18-66 (for use with Employment Deprivation Domain): mid 2022": [600, 1800, 1100],
    })


def test_seat_frames_population_weighted():
    data = imd.parse_file7(file7())
    out = imd.seat_frames(data, {"A1": "P1", "A2": "P1", "B1": "P2"})
    val = lambda mid, p: out[mid].loc[p, "num"] / out[mid].loc[p, "den"]  # noqa: E731
    assert val("imd_most_deprived_10", "P1") == pytest.approx(25.0)  # 1000 of 4000 residents in decile 1
    assert val("imd_most_deprived_20", "P2") == pytest.approx(100.0)
    assert val("imd_score", "P1") == pytest.approx((40 * 1000 + 10 * 3000) / 4000)
    assert val("income_deprived", "P1") == pytest.approx((0.5 * 1000 + 0.1 * 3000) / 4000 * 100)
    assert val("idaci", "P1") == pytest.approx((0.6 * 300 + 0.2 * 300) / 600 * 100)  # weighted by children
    assert val("idaopi", "P1") == pytest.approx((0.4 * 100 + 0.1 * 900) / 1000 * 100)  # weighted by over-60s


def test_lsoa_frames_and_missing_columns():
    data = imd.parse_file7(file7())
    f = imd.lsoa_frames(data)
    assert (f["income_deprived"]["num"] / f["income_deprived"]["den"]).to_dict() == pytest.approx({"A1": 50.0, "A2": 10.0, "B1": 20.0})
    with pytest.raises(ValueError):
        imd.parse_file7(file7().drop(columns=["Income Score (rate)"]))
