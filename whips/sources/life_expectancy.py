"""Life expectancy at birth by council (OHID Fingertips), averaged over the councils each seat covers. England.

Uses the latest three-year period (more stable than single years for small
councils). National figures are OHID's England values.
"""

from __future__ import annotations

import io
import logging

import pandas as pd
import requests

from ..metrics import MetricMeta
from .councils import averaged

log = logging.getLogger(__name__)

FINGERTIPS = "https://fingertips.phe.org.uk/api/all_data/csv/by_indicator_id"
SOURCE_URL = "https://fingertips.phe.org.uk/search/life%20expectancy"
INDICATOR = 90366       # Life expectancy at birth
COUNCILS = 501          # Districts & unitary authorities (from April 2023)
ENGLAND = 15

LIFE_METRICS = [
    MetricMeta(f"life_expectancy_{sex.lower()}", f"Life expectancy at birth ({sex.lower()})", "health", "years",
               f"Average years a newborn {sex.lower()} would live at current death rates (OHID, three-year period). "
               "Council-level figures, averaged over the councils the constituency covers.",
               "OHID Fingertips", "higher_better", 1, ("life_expectancy",))
    for sex in ("Male", "Female")
]


def parse(text: str) -> tuple[dict[str, pd.Series], dict[str, float], str]:
    """(values by council for each sex, England values, period) for the latest three-year period."""
    d = pd.read_csv(io.StringIO(text), low_memory=False)
    d = d[d["Category Type"].isna() & d["Time period"].astype(str).str.contains(" - ")]
    latest = d["Time period Sortable"].max()
    d = d[d["Time period Sortable"].eq(latest)]
    period = str(d["Time period"].iloc[0])
    values, national = {}, {}
    for sex in ("Male", "Female"):
        rows = d[d["Sex"].eq(sex)]
        councils = rows[~rows["Area Type"].eq("England")]
        values[sex] = pd.Series(councils["Value"].values, index=councils["Area Code"].astype(str)).dropna()
        eng = rows.loc[rows["Area Type"].eq("England"), "Value"]
        national[sex] = float(eng.iloc[0]) if len(eng) else None
    return values, national, period


def load_life_expectancy(s: requests.Session, weights: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], str]:
    r = s.get(FINGERTIPS, timeout=300, params={"indicator_ids": INDICATOR, "child_area_type_id": COUNCILS,
                                              "parent_area_type_id": ENGLAND})
    r.raise_for_status()
    values, national, period = parse(r.text)
    frames = {}
    for sex, v in values.items():
        f = averaged(v, weights)
        f.attrs["national"] = national[sex]
        frames[f"life_expectancy_{sex.lower()}"] = f
    return frames, period
