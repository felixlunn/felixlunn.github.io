import numpy as np
import pandas as pd

from whips.sources.parliament import only_where_standing


def test_nation_parties_blank_elsewhere():
    f = pd.DataFrame({"num": [0.0, 500.0, 0.0], "den": [100.0] * 3}, index=["E14000001", "S14000001", "W07000001"])
    snp = only_where_standing("SNP", f)
    assert np.isnan(snp.loc["E14000001", "num"]) and snp.loc["S14000001", "num"] == 500 and np.isnan(snp.loc["W07000001", "num"])
    assert only_where_standing("LD", f)["num"].notna().all()
