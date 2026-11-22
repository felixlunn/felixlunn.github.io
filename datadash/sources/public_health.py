"""Public health indicators by council (OHID Fingertips), averaged over each seat's councils. England.

Council (district and unitary) figures for childhood vaccination, child obesity,
adult smoking, alcohol-related hospital admissions and suicide. Each takes the
latest period, persons where split by sex, and England's value as the national
figure.
"""

from __future__ import annotations

import io
import logging
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

from ..history import council_periods
from ..metrics import MetricMeta
from .councils import averaged, lad_to_county, upper_tier_weights

log = logging.getLogger(__name__)

FINGERTIPS = "https://fingertips.phe.org.uk/api/all_data/csv/by_indicator_id"
SOURCE_URL = "https://fingertips.phe.org.uk/"
COUNCILS, UPPER_TIER, ENGLAND = 501, 502, 15  # districts & unitaries; counties & unitaries; England
NOTE = " Council-level figures, averaged over the councils the constituency covers (OHID Fingertips)."
# Fingertips indicator -> (metric id, label, unit, description, polarity, decimals)
INDICATORS = {
    30311: ("vacc_mmr2_age5", "Children fully vaccinated against MMR by age 5", "%",
            "Children who had both doses of the MMR (measles, mumps, rubella) vaccine by their fifth birthday.", "higher_better", 1),
    90323: ("obesity_year6", "Obesity in Year 6 children", "%",
            "Children in Year 6 (aged 10-11) measured as obese, including severely obese (National Child Measurement Programme).",
            "higher_worse", 1),
    92443: ("smoking_adults", "Adults who smoke", "%", "Adults (18+) who currently smoke (Annual Population Survey).", "higher_worse", 1),
    93764: ("alcohol_admissions", "Alcohol-related hospital admissions per 100,000", "per 100,000",
            "Hospital admissions where the main reason, or a secondary cause, was alcohol-related (narrow measure), age-standardised.",
            "higher_worse", 0),
    41001: ("suicide_rate", "Suicide rate per 100,000", "per 100,000",
            "Deaths from suicide and injury of undetermined intent, age-standardised, three-year period.", "higher_worse", 1),
}
PUBLIC_HEALTH_METRICS = [MetricMeta(mid, label, "health", unit, desc + NOTE, "OHID Fingertips", pol, dec, ("public_health",))
                         for mid, label, unit, desc, pol, dec in INDICATORS.values()]


def parse_periods(text: str) -> list[tuple[str, pd.Series, float | None]]:
    """[(period, council values, England value)] for every period (persons), oldest first."""
    d = pd.read_csv(io.StringIO(text), low_memory=False)
    d = d[d["Category Type"].isna()]
    if "Persons" in set(d["Sex"]):
        d = d[d["Sex"].eq("Persons")]
    if "Age" in d:  # England is often also split by age band: keep the age group councils are published for
        councils_age = d.loc[~d["Area Type"].eq("England"), "Age"].mode()
        if len(councils_age):
            d = d[d["Age"].eq(councils_age.iloc[0])]
    out = []
    for sortable, g in sorted(d.groupby("Time period Sortable"), key=lambda x: x[0]):
        g = g.drop_duplicates(["Area Code"])
        eng = g.loc[g["Area Type"].eq("England"), "Value"]
        councils = g[~g["Area Type"].eq("England")]
        values = pd.Series(pd.to_numeric(councils["Value"], errors="coerce").values,
                           index=councils["Area Code"].astype(str)).dropna()
        if len(values):
            out.append((str(g["Time period"].iloc[0]), values,
                        float(eng.iloc[0]) if len(eng) and pd.notna(eng.iloc[0]) else None))
    return out


def parse(text: str) -> tuple[pd.Series, float | None, str]:
    """Council values, England value and period label for the latest period (persons)."""
    periods = parse_periods(text)
    if not periods:
        return pd.Series(dtype=float), None, ""
    period, values, national = periods[-1]
    return values, national, period


def fetch(s: requests.Session, indicator: int, area_type: int = COUNCILS) -> str:
    r = s.get(FINGERTIPS, timeout=300, params={"indicator_ids": indicator, "child_area_type_id": area_type,
                                              "parent_area_type_id": ENGLAND})
    r.raise_for_status()
    return r.text


def load_public_health(s: requests.Session, weights: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], str]:
    with ThreadPoolExecutor(3) as pool:
        texts = dict(zip(INDICATORS, pool.map(lambda i: fetch(s, i), INDICATORS)))
    frames, periods = {}, []
    upper = None
    for ind, (mid, label, *_rest) in INDICATORS.items():
        try:
            values, national, period = parse(texts[ind])
        except Exception as exc:  # noqa: BLE001 - one bad indicator shouldn't drop the rest
            log.warning("%s failed: %s", mid, exc)
            continue
        if values.empty:
            continue
        w, text = weights, texts[ind]
        if len(values) < 250:  # published for counties and unitaries only (e.g. vaccination): use those
            text = fetch(s, ind, UPPER_TIER)
            values, national, period = parse(text)
            upper = upper if upper is not None else upper_tier_weights(weights, lad_to_county(s))
            w = upper
        # Earlier periods too, for change over time (only periods with most councils reporting).
        past = [p for p in parse_periods(text) if len(p[1]) >= 0.8 * len(values)]
        frames[mid] = council_periods(past, averaged, w)
        periods.append(f"{label.split(' per ')[0].lower()} {period}")
    return frames, "; ".join(periods)
