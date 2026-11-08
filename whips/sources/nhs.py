"""NHS: diagnosed conditions (QOF disease registers) and GP access (GP Patient Survey), England.

Both are published per GP practice on OHID Fingertips. Each practice is placed
in the constituency where it is located (practice postcode -> July 2024
constituency via postcodes.io), and a seat's figure is the sum over its
practices: registered patients with the condition / patients in the eligible
age group. Patients don't all live in the seat their practice is in, so these
are "practices in this constituency" figures.
"""

from __future__ import annotations

import io
import logging
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

from ..http import get_json
from ..history import with_history
from ..metrics import MetricMeta

log = logging.getLogger(__name__)

FINGERTIPS = "https://fingertips.phe.org.uk/api"
POSTCODES = "https://api.postcodes.io/postcodes"
SOURCE_URL = "https://fingertips.phe.org.uk/profile/general-practice"
SUB_ICB = 66  # Fingertips area type: sub-ICB locations (practices are requested one sub-ICB at a time)
PRACTICE = 7

QOF_NOTE = ("Patients on GP practice registers ({age}) as a share of registered patients in that age group, for practices "
            "located in the constituency (QOF {what}).")
# Fingertips indicator id -> (metric id, label, age group, polarity)
QOF = {
    241: ("nhs_diabetes", "Diabetes (GP registers)", "17+", "higher_worse"),
    219: ("nhs_hypertension", "High blood pressure (GP registers)", "all ages", "higher_worse"),
    848: ("nhs_depression", "Depression (GP registers)", "18+", "higher_worse"),
    90933: ("nhs_asthma", "Asthma (GP registers)", "6+", "higher_worse"),
    253: ("nhs_copd", "COPD (GP registers)", "all ages", "higher_worse"),
    247: ("nhs_dementia", "Dementia (GP registers)", "all ages", "higher_worse"),
    273: ("nhs_chd", "Coronary heart disease (GP registers)", "all ages", "higher_worse"),
    212: ("nhs_stroke", "Stroke (GP registers)", "all ages", "higher_worse"),
    276: ("nhs_cancer", "Cancer (GP registers)", "all ages", "higher_worse"),
    90581: ("nhs_smi", "Serious mental illness (GP registers)", "all ages", "higher_worse"),
    94136: ("nhs_obesity", "Obesity (GP registers)", "18+", "higher_worse"),
    258: ("nhs_ckd", "Chronic kidney disease (GP registers)", "18+", "higher_worse"),
    280: ("nhs_af", "Atrial fibrillation (GP registers)", "all ages", "higher_worse"),
    200: ("nhs_learning_disability", "Learning disability (GP registers)", "all ages", "neutral"),
    91280: ("nhs_smoking", "Smokers (GP records)", "15+", "higher_worse"),
}
GPPS = {
    94126: ("gp_contact_good", "Good experience contacting GP practice",
            "Share of GP Patient Survey respondents at practices in the constituency who had a good experience contacting their practice."),
    94127: ("gp_wait_ok", "Acceptable wait for a GP appointment",
            "Share of GP Patient Survey respondents at practices in the constituency who felt the wait for their appointment was acceptable."),
    94129: ("gp_needs_met", "Needs met at last GP appointment",
            "Share of GP Patient Survey respondents at practices in the constituency whose needs were met at their last appointment."),
}

# Cancer screening coverage (practice level): eligible patients screened within the recommended interval.
SCREENING = {
    92600: ("screen_bowel", "Bowel cancer screening coverage",
            "Patients aged 60-74 at practices in the constituency screened for bowel cancer in the last 2.5 years (NHS cancer screening)."),
    93717: ("screen_cervical", "Cervical screening coverage (25-49)",
            "Women aged 25-49 at practices in the constituency with a cervical screening record in the last 3.5 years."),
    93718: ("screen_cervical_50", "Cervical screening coverage (50-64)",
            "Women aged 50-64 at practices in the constituency with a cervical screening record in the last 5.5 years."),
}

from .nhsbsa import PRESCRIBING_METRICS  # noqa: E402 - defined alongside the prescribing loader

NHS_METRICS = [
    *[MetricMeta(mid, label, "health", "%", QOF_NOTE.format(age=age, what=label.split(" (")[0].lower()),
                 "NHS QOF via OHID Fingertips", pol, 1, ("nhs",)) for mid, label, age, pol in QOF.values()],
    *[MetricMeta(mid, label, "health", "%", desc, "GP Patient Survey via OHID Fingertips", "higher_better", 1, ("nhs",))
      for mid, label, desc in GPPS.values()],
    *[MetricMeta(mid, label, "health", "%", desc, "NHS cancer screening via OHID Fingertips", "higher_better", 1, ("screening",))
      for mid, label, desc in SCREENING.values()],
    *PRESCRIBING_METRICS,
]
METRIC_BY_INDICATOR = {i: v[0] for i, v in {**QOF, **GPPS, **SCREENING}.items()}


def fetch_parent(s: requests.Session, parent: str) -> pd.DataFrame:
    """All selected indicators for the GP practices in one sub-ICB (full time series; filtered later)."""
    r = s.get(f"{FINGERTIPS}/all_data/csv/by_indicator_id", timeout=300, params={
        "indicator_ids": ",".join(map(str, METRIC_BY_INDICATOR)), "child_area_type_id": PRACTICE,
        "parent_area_type_id": SUB_ICB, "parent_area_code": parent,
    })
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), low_memory=False)
    return df[df["Area Type"].astype(str).str.contains("GP", na=False)]


def latest_by_practice(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[int, str]]:
    """Latest period per indicator: rows of (indicator, practice, count, denominator) and the period labels."""
    df = df.copy()
    df["Count"] = pd.to_numeric(df["Count"], errors="coerce")
    df["Denominator"] = pd.to_numeric(df["Denominator"], errors="coerce")
    latest = df.groupby("Indicator ID")["Time period Sortable"].transform("max")
    df = df[df["Time period Sortable"].eq(latest)].drop_duplicates(["Indicator ID", "Area Code"])
    periods = df.groupby("Indicator ID")["Time period"].first().to_dict()
    return df[["Indicator ID", "Area Code", "Count", "Denominator"]], periods


def practice_constituencies(s: requests.Session, postcodes: dict[str, str]) -> dict[str, str]:
    """{practice code: postcode} -> {practice code: July 2024 constituency code} (postcodes.io, 100 per request)."""
    by_pc: dict[str, list[str]] = {}
    for prac, pc in postcodes.items():
        if isinstance(pc, str) and pc.strip():
            by_pc.setdefault(pc.strip().upper(), []).append(prac)
    pcs, out = list(by_pc), {}
    for i in range(0, len(pcs), 100):
        r = s.post(POSTCODES, json={"postcodes": pcs[i:i + 100]}, timeout=60)
        r.raise_for_status()
        for item in r.json().get("result", []):
            code = ((item.get("result") or {}).get("codes") or {}).get("parliamentary_constituency_2024")
            if code:
                for prac in by_pc.get(item["query"].strip().upper(), []):
                    out[prac] = code
    return out


def seat_frames(rows: pd.DataFrame, where: dict[str, str]) -> dict[str, pd.DataFrame]:
    d = rows.assign(pcon=rows["Area Code"].map(where)).dropna(subset=["pcon", "Count", "Denominator"])
    out = {}
    for ind, g in d.groupby("Indicator ID"):
        mid = METRIC_BY_INDICATOR.get(int(ind))
        if mid:
            sums = g.groupby("pcon")[["Count", "Denominator"]].sum()
            out[mid] = pd.DataFrame({"num": sums["Count"] * 100, "den": sums["Denominator"].where(sums["Denominator"] > 0)})
    return out


def add_history(frames: dict[str, pd.DataFrame], df: pd.DataFrame, where: dict[str, str]) -> None:
    """Attach each indicator's earlier periods (same practices, summed to seats) to its latest frame."""
    df = df.copy()
    df["Count"] = pd.to_numeric(df["Count"], errors="coerce")
    df["Denominator"] = pd.to_numeric(df["Denominator"], errors="coerce")
    df = df.drop_duplicates(["Indicator ID", "Area Code", "Time period Sortable"])
    for ind, g in df.groupby("Indicator ID"):
        mid = METRIC_BY_INDICATOR.get(int(ind))
        if mid not in frames:
            continue
        periods = []
        for _, p in sorted(g.groupby("Time period Sortable"), key=lambda x: x[0]):
            f = seat_frames(p, where).get(mid)
            if f is not None and len(f) >= 0.8 * len(frames[mid]):  # skip thinly reported periods
                periods.append((str(p["Time period"].iloc[0]), f, None))
        with_history(frames[mid], periods)


def load_nhs(s: requests.Session, workers: int = 4, prescribing: bool = True) -> tuple[dict[str, pd.DataFrame], str]:
    parents = [a["Code"] for a in get_json(s, f"{FINGERTIPS}/areas/by_area_type", params={"area_type_id": SUB_ICB})]
    with ThreadPoolExecutor(workers) as pool:
        parts = list(pool.map(lambda p: fetch_parent(s, p), parents))
    everything = pd.concat(parts, ignore_index=True)
    rows, periods = latest_by_practice(everything)
    r = s.get(f"{FINGERTIPS}/area_addresses/csv/by_parent_area_code", timeout=120,
              params={"parent_area_code": "E92000001", "area_type_id": PRACTICE})
    r.raise_for_status()
    addr = pd.read_csv(io.StringIO(r.text))
    where = practice_constituencies(s, dict(zip(addr["Code"], addr["Postcode"])))
    log.info("NHS: %d practices, %d placed in constituencies", rows["Area Code"].nunique(), len(where))
    frames = seat_frames(rows, where)
    add_history(frames, everything, where)
    qof = periods.get(241) or next(iter(periods.values()), "")
    gpps = periods.get(94126, "")
    period = f"QOF {qof}; GP Patient Survey {gpps}".strip("; ")
    if prescribing:
        # Prescribing uses the same practices and list sizes (all-ages hypertension register denominators).
        from .nhsbsa import load_prescribing
        hyp = rows[rows["Indicator ID"].eq(219)]
        list_size = pd.Series(hyp["Denominator"].values, index=hyp["Area Code"].values).dropna()
        try:
            rx, month = load_prescribing(s, where, list_size)
            frames.update(rx)
            period += f"; prescribing {month}"
        except Exception as exc:  # noqa: BLE001 - keep the rest of the NHS data if prescribing fails
            log.warning("Prescribing failed: %s", exc)
    return frames, period
