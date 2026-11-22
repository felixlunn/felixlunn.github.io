"""Change over time: past values of a metric, kept alongside its latest figures.

A source that publishes earlier periods attaches them to its latest num/den frame with ``with_history``:
a list of (period label, num/den frame, national figure or None), oldest first, ending with the latest
period. ``assemble_history`` turns those into seat values per period for ``history.json``, which the
dashboard loads separately (the main data file stays the same size).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

MAX_PERIODS = 12  # keep the most recent periods only: enough for "since 2015" without bloating the file

Period = tuple[str, pd.DataFrame, "float | None"]


def with_history(frame: pd.DataFrame, periods: list[Period]) -> pd.DataFrame:
    """Attach past periods (oldest first, including the latest) to a metric's latest frame."""
    periods = [(label, _detached(pf), nat) for label, pf, nat in periods if pf is not None and len(pf)]
    if len(periods) >= 2:
        frame.attrs["history"] = periods[-MAX_PERIODS:]
    return frame


def _detached(pf: pd.DataFrame) -> pd.DataFrame:
    """num/den only, without attrs (a frame holding itself in its own history recurses in pandas)."""
    out = pd.DataFrame({"num": pf["num"].values, "den": pf["den"].values if "den" in pf else 1.0}, index=pf.index)
    out.attrs = {}
    return out


def _clean(v, decimals: int = 4):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    return round(float(v), decimals)


def assemble_history(codes: list[str], frames: dict[str, pd.DataFrame], metrics: list[dict]) -> dict:
    """{"metrics": {id: {"periods": [...], "national": [...], "values": [[seat values] per period]}}}.

    ``metrics`` are the assembled metric dicts (id and display decimals); values keep one more decimal than shown."""
    out = {}
    for m in metrics:
        mid, dec = m["id"], int(m.get("decimals", 1)) + 1
        f = frames.get(mid)
        periods = f.attrs.get("history") if f is not None else None
        if not periods:
            continue
        labels, national, values = [], [], []
        for label, pf, nat in periods:
            pf = pf.reindex(codes)
            num, den = pf["num"].astype(float), pf["den"].astype(float)
            val = (num / den).replace([np.inf, -np.inf], np.nan)
            ok = val.notna()
            if not ok.any():
                continue
            if nat is None and den[ok].sum():
                nat = float(num[ok].sum() / den[ok].sum())
            labels.append(str(label))
            national.append(_clean(nat, dec))
            values.append([_clean(v, dec) for v in val.tolist()])
        if len(labels) >= 2:
            out[mid] = {"periods": labels, "national": national, "values": values}
    return {"metrics": out}


def year_columns(t: pd.DataFrame, codes: pd.Series, columns: list[str], keep: pd.Series,
                 national: pd.Series | None = None) -> list[tuple[str, pd.Series, float | None]]:
    """For a table with one column per period: [(column, values by code where ``keep``, national value)]."""
    out = []
    for c in columns:
        v = pd.to_numeric(t[c], errors="coerce")
        ok = keep & v.notna()
        nat = None
        if national is not None and national.any():
            n = v[national]
            nat = float(n.iloc[0]) if len(n) and pd.notna(n.iloc[0]) else None
        if ok.any():
            out.append((c, pd.Series(v[ok].values, index=codes[ok].values), nat))
    return out


# Councils created since 2019 and the councils (districts, and for upper-tier tables counties) they replaced, so a
# new council's earlier years can be filled from its predecessors' figures.
SUCCESSORS: dict[str, list[str]] = {
    "E06000058": ["E06000028", "E06000029", "E07000048"],                                    # BCP (2019)
    "E06000059": ["E07000049", "E07000050", "E07000051", "E07000052", "E07000053", "E10000009"],  # Dorset (2019)
    "E07000244": ["E07000205", "E07000206"],                                                 # East Suffolk (2019)
    "E07000245": ["E07000201", "E07000204"],                                                 # West Suffolk (2019)
    "E07000246": ["E07000190", "E07000191"],                                                 # Somerset West and Taunton (2019)
    "E06000060": ["E07000004", "E07000005", "E07000006", "E07000007", "E10000002"],          # Buckinghamshire (2020)
    "E06000061": ["E07000150", "E07000152", "E07000153", "E07000156", "E10000021"],          # North Northamptonshire (2021)
    "E06000062": ["E07000151", "E07000154", "E07000155", "E10000021"],                       # West Northamptonshire (2021)
    "E06000063": ["E07000026", "E07000028", "E07000029", "E10000006"],                       # Cumberland (2023)
    "E06000064": ["E07000027", "E07000030", "E07000031", "E10000006"],                       # Westmorland and Furness (2023)
    "E06000065": ["E07000163", "E07000164", "E07000165", "E07000166", "E07000167", "E07000168", "E07000169",
                  "E10000023"],                                                              # North Yorkshire (2023)
    "E06000066": ["E07000187", "E07000188", "E07000189", "E07000246", "E07000190", "E07000191",
                  "E10000027"],                                                              # Somerset (2023)
}


def fill_successors(values: pd.Series, how: str = "mean") -> pd.Series:
    """Add values for councils created since 2019 from their predecessors (mean for rates, sum for counts)."""
    values = values[~values.index.duplicated()]
    extra = {}
    for new, old in SUCCESSORS.items():
        if new in values.index:
            continue
        prev = values.reindex([o for o in old if o in values.index]).dropna()
        if how == "sum":  # counts: districts only (a county total would double count)
            prev = prev[~prev.index.str.startswith("E10")]
        if len(prev):
            extra[new] = prev.sum() if how == "sum" else prev.mean()
    return pd.concat([values, pd.Series(extra, dtype=float)]) if extra else values


def council_periods(years: list[tuple[str, pd.Series, float | None]], combine, weights: pd.DataFrame,
                    label=lambda c: c, how: str = "mean") -> pd.DataFrame:
    """Seat frames for each period of council values (combined with e.g. councils.averaged, or councils.apportion
    with how="sum"); returns the latest period's frame (national attached) carrying the rest as history.
    Earlier periods use predecessor councils' figures for councils created since 2019."""
    periods = [(label(c), combine(v if i == len(years) - 1 else fill_successors(v, how), weights), nat)
               for i, (c, v, nat) in enumerate(years)]
    latest = periods[-1][1].copy()
    latest.attrs["national"] = periods[-1][2]
    return with_history(latest, periods)
