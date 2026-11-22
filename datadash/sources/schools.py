"""Schools: the DfE register (Get Information about Schools) and GCSE results by constituency.

GIAS lists every school in England and Wales with its July 2024 parliamentary
constituency, pupil numbers and free school meals (FSM) eligibility, so seat
figures are straight sums over the schools located in each seat (England only:
Welsh schools don't report the same fields).

GCSE (Key Stage 4) results come from DfE's Explore Education Statistics API,
which publishes them by parliamentary constituency of pupils' residence.
"""

from __future__ import annotations

import io
import logging
from datetime import date, timedelta

import pandas as pd
import requests

from ..metrics import MetricMeta

log = logging.getLogger(__name__)

GIAS_URL = "https://ea-edubase-api-prod.azurewebsites.net/edubase/downloads/public/edubasealldata{date}.csv"
GIAS_PAGE = "https://get-information-schools.service.gov.uk/"
KS4_DATASET = "https://api.education.gov.uk/statistics/v1/data-sets/19e39901-9533-5f75-aafe-c98bb510cb28"
KS4_PAGE = "https://explore-education-statistics.service.gov.uk/find-statistics/key-stage-4-performance"

STATE = {"Academies", "Free Schools", "Local authority maintained schools", "Special schools"}
ACADEMY = {"Academies", "Free Schools"}

SCHOOL_METRICS = [
    MetricMeta("school_fsm", "Pupils eligible for free school meals", "education", "%",
               "Share of pupils at schools in the constituency who are eligible for free school meals (DfE Get Information about Schools).",
               "DfE Get Information about Schools", "higher_worse", 1, ("schools",)),
    MetricMeta("school_academy", "Pupils at academies", "education", "%",
               "Share of pupils at state-funded schools in the constituency who attend an academy or free school.",
               "DfE Get Information about Schools", "neutral", 1, ("schools",)),
    MetricMeta("school_independent", "Pupils at independent schools", "education", "%",
               "Share of pupils at schools in the constituency who attend an independent (fee-paying) school.",
               "DfE Get Information about Schools", "neutral", 1, ("schools",)),
]

# indicator id in the KS4 constituency data set -> role
KS4_IND = {"eDSuS": "pupils", "Y26HK": "em4", "XLwfK": "em5", "PrTeb": "a8"}
KS4_METRICS = [
    MetricMeta("gcse_em4", "GCSE English & maths grade 4+", "education", "%",
               "Share of pupils living in the constituency who achieved grade 4 or above in both English and maths GCSE (end of Key Stage 4).",
               "DfE Key stage 4 performance", "higher_better", 1, ("schools",)),
    MetricMeta("gcse_em5", "GCSE English & maths grade 5+", "education", "%",
               "Share of pupils living in the constituency who achieved grade 5 or above (a 'strong pass') in both English and maths GCSE.",
               "DfE Key stage 4 performance", "higher_better", 1, ("schools",)),
    MetricMeta("gcse_a8", "Attainment 8 score", "education", "score",
               "Average Attainment 8 score of pupils living in the constituency: their results across eight GCSE-level qualifications.",
               "DfE Key stage 4 performance", "higher_better", 1, ("schools",)),
]


def fetch_gias(s: requests.Session, today: date | None = None) -> pd.DataFrame:
    """The latest daily GIAS extract (published most days; try back a week)."""
    day = today or date.today()
    for back in range(8):
        r = s.get(GIAS_URL.format(date=(day - timedelta(days=back)).strftime("%Y%m%d")), timeout=180)
        if r.ok and len(r.content) > 1_000_000:
            return pd.read_csv(io.BytesIO(r.content), encoding="latin-1", low_memory=False)
    raise LookupError("No GIAS extract found for the last 8 days")


def gias_frames(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Seat num/den frames from the GIAS table (open schools in England)."""
    d = df[df["EstablishmentStatus (name)"].eq("Open")].copy()
    d["code"] = d["ParliamentaryConstituency (code)"].astype(str)
    d = d[d["code"].str.match(r"^E14\d{6}$")]
    d["pupils"] = pd.to_numeric(d["NumberOfPupils"], errors="coerce")
    d["fsm"] = pd.to_numeric(d["FSM"], errors="coerce")
    group = d["EstablishmentTypeGroup (name)"]
    by = lambda mask, col="pupils": d[mask].groupby("code")[col].sum(min_count=1)  # noqa: E731
    has_fsm = d["fsm"].notna() & d["pupils"].notna()
    state = group.isin(STATE) & d["pupils"].notna()
    indep = group.eq("Independent schools") & d["pupils"].notna()
    state_pupils = by(state)
    all_pupils = state_pupils.add(by(indep), fill_value=0)
    return {
        "school_fsm": pd.DataFrame({"num": by(has_fsm, "fsm") * 100, "den": by(has_fsm)}),
        "school_academy": pd.DataFrame({"num": by(state & group.isin(ACADEMY)).reindex(state_pupils.index).fillna(0) * 100, "den": state_pupils}),
        "school_independent": pd.DataFrame({"num": by(indep).reindex(all_pupils.index).fillna(0) * 100, "den": all_pupils}),
    }


def load_gias(s: requests.Session) -> tuple[dict[str, pd.DataFrame], str]:
    df = fetch_gias(s)
    return gias_frames(df), date.today().isoformat()


def ks4_frames(rows: list[dict], codes: dict[str, str]) -> dict[str, pd.DataFrame]:
    """KS4 API result rows -> num/den frames. ``codes`` maps location ids to GSS codes."""
    recs = {}
    for r in rows:
        code = codes.get(r["locations"].get("PCON", ""))
        if not code:
            continue
        vals = {KS4_IND[k]: pd.to_numeric(v, errors="coerce") for k, v in r["values"].items() if k in KS4_IND}
        recs[code] = vals
    df = pd.DataFrame.from_dict(recs, orient="index")
    p = df["pupils"]
    return {
        "gcse_em4": pd.DataFrame({"num": df["em4"] * 100, "den": p}),
        "gcse_em5": pd.DataFrame({"num": df["em5"] * 100, "den": p}),
        "gcse_a8": pd.DataFrame({"num": df["a8"] * p, "den": p.where(df["a8"].notna())}),  # pupil-weighted national
    }


def load_ks4(s: requests.Session) -> tuple[dict[str, pd.DataFrame], str]:
    meta = s.get(f"{KS4_DATASET}/meta", timeout=60).json()
    basis = next(o["id"] for f in meta["filters"] for o in f["options"] if o["label"].lower() == "pupil residency")
    codes = {o["id"]: o["code"] for g in meta["locations"] if g["level"]["code"] == "PCON" for o in g["options"]}
    for tp in reversed(meta["timePeriods"]):  # latest year with data
        q = {"criteria": {"and": [
            {"timePeriods": {"in": [{"period": tp["period"], "code": tp["code"]}]}},
            {"geographicLevels": {"eq": "PCON"}},
            {"filters": {"eq": basis}},
        ]}, "indicators": list(KS4_IND), "page": 1, "pageSize": 1000}
        r = s.post(f"{KS4_DATASET}/query", json=q, timeout=120)
        if r.ok and r.json().get("results"):
            frames = ks4_frames(r.json()["results"], codes)
            if frames["gcse_em4"]["num"].notna().sum() > 400:
                return frames, tp.get("label") or tp["period"]
    raise LookupError("No KS4 constituency results found")
