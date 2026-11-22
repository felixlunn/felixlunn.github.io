"""Pupil absence and what young people do after GCSEs (DfE, via the explore education statistics API). England.

* Persistent and severe absence (missing 10% / 50% or more of sessions), by
  council (education authority), shared out across seats.
* Key stage 4 destinations: pupils at state schools who did not stay in
  education, an apprenticeship or employment for the two terms after year 11,
  by council district (DfE's constituency figures use the pre-2024 boundaries),
  shared out across seats.
"""

from __future__ import annotations

import logging

import pandas as pd
import requests

from ..history import with_history
from ..metrics import MetricMeta
from .children import DataSet, by_council, councils_frame, education_weights, find_dataset, number
from .councils import apportion, lad_to_county

log = logging.getLogger(__name__)

HISTORY_YEARS = 8
SOURCE_URL = "https://explore-education-statistics.service.gov.uk/find-statistics/pupil-absence-in-schools-in-england"
ABS_PUB, ABS_SET = "Pupil absence in schools in England", r"persistent and severe absentees"
KS4_PUB, KS4_SET = "Key stage 4 destination measures", r"Key stage 4 leavers destinations"

NOTE = " Council figures shared out across the constituencies each council covers."
PUPIL_METRICS = [
    MetricMeta("persistent_absence", "Pupils persistently absent", "education", "%",
               "Pupils missing 10% or more of school sessions (state-funded schools, latest academic year)." + NOTE,
               "DfE pupil absence", "higher_worse", 1, ("absence",)),
    MetricMeta("severe_absence", "Pupils severely absent", "education", "%",
               "Pupils missing half or more of school sessions (state-funded schools, latest academic year)." + NOTE,
               "DfE pupil absence", "higher_worse", 1, ("absence",)),
    MetricMeta("ks4_not_sustained", "Year 11 leavers not in sustained education or work", "education", "%",
               "Pupils finishing year 11 at state schools who were not in sustained education, an apprenticeship or "
               "employment for the following two terms (DfE key stage 4 destinations)." + NOTE,
               "DfE key stage 4 destinations", "higher_worse", 1, ("neet",)),
]


def absence(ds: DataSet, weights: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], str]:
    school = ds.option("School type", "Total")
    kind = ds.filter_id("Absence type")
    frames = {}
    latest_period = ds.meta["timePeriods"][-1]["period"]
    for mid, label in [("persistent_absence", "Persistent absence"), ("severe_absence", "Severe absence")]:
        picks = (kind, {ds.option("Absence type", label): "num", ds.option("Absence type", "Total pupils"): "den"})
        past = []
        for p in ds.meta["timePeriods"][-HISTORY_YEARS:]:  # oldest first, ending with the latest
            period = {"period": p["period"], "code": p["code"]}
            try:
                d, _ = by_council(ds, [school], ds.indicator("Count of pupil enrolments"), None, picks, period)
                f = councils_frame(d, weights, past=p["period"] != latest_period)
            except Exception as exc:  # noqa: BLE001 - a missing past year shouldn't drop the latest
                log.info("%s %s: %s", mid, p["period"], exc)
                continue
            past.append((p["period"].replace("/", "-"), f, f.attrs.get("national")))
        label, latest, _ = past[-1]
        frames[mid] = with_history(latest, past)
    return frames, label


def headline_rows(ds: DataSet, rows: list[dict]) -> list[dict]:
    """Rows for all pupils: every breakdown filter at "Total", state-funded mainstream schools."""
    label = {o["id"]: o["label"].strip().lower() for f in ds.meta["filters"] for o in f["options"]}
    ok = {"total", "headline destinations", "state-funded mainstream school", "state-funded mainstream schools",
          "not recorded as a sustained destination"}
    return [r for r in rows if all(label.get(v) in ok for v in r["filters"].values())]


def destinations(ds: DataSet, weights: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    period = ds.latest_period()
    count, cohort = ds.indicator("Number of pupils sustaining a destination"), ds.indicator("Number of pupils completing key stage 4")
    rows = headline_rows(ds, ds.query(["LAD", "NAT"], [ds.option("Destination measure", "Not recorded as a sustained destination")],
                                      [count, cohort], period))
    d = pd.DataFrame([{"level": r["geographicLevel"], "code": ds.code(r), "num": number(r["values"].get(count)),
                       "den": number(r["values"].get(cohort))} for r in rows]).groupby(["level", "code"]).sum(min_count=1)
    lad = d.loc["LAD"].dropna()
    f = pd.DataFrame({"num": apportion(lad["num"], weights) * 100, "den": apportion(lad["den"], weights)})
    if "NAT" in d.index.get_level_values(0):
        nat = d.loc["NAT"].iloc[0]
        f.attrs["national"] = float(nat["num"] * 100 / nat["den"])
    return f, period["period"].replace("/", "-")


def load_pupils(s: requests.Session, weights: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], str]:
    frames, notes = {}, []
    try:
        got, year = absence(DataSet(s, find_dataset(s, ABS_PUB, ABS_SET)), education_weights(weights, lad_to_county(s)))
        frames.update(got)
        notes.append(f"absence {year}")
    except Exception as exc:  # noqa: BLE001 - keep destinations if absence fails
        log.warning("Pupil absence failed: %s", exc)
    try:
        frames["ks4_not_sustained"], year = destinations(DataSet(s, find_dataset(s, KS4_PUB, KS4_SET)), weights)
        notes.append(f"KS4 leavers {year}")
    except Exception as exc:  # noqa: BLE001
        log.warning("KS4 destinations failed: %s", exc)
    if not frames:
        raise RuntimeError("No pupil absence or destinations data")
    return frames, "; ".join(notes)
