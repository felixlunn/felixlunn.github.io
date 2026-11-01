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

NHS_METRICS = [
    *[MetricMeta(mid, label, "health", "%", QOF_NOTE.format(age=age, what=label.split(" (")[0].lower()),
                 "NHS QOF via OHID Fingertips", pol, 1, ("nhs",)) for mid, label, age, pol in QOF.values()],
    *[MetricMeta(mid, label, "health", "%", desc, "GP Patient Survey via OHID Fingertips", "higher_better", 1, ("nhs",))
      for mid, label, desc in GPPS.values()],
]
METRIC_BY_INDICATOR = {i: v[0] for i, v in {**QOF, **GPPS}.items()}


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


def load_nhs(s: requests.Session, workers: int = 4) -> tuple[dict[str, pd.DataFrame], str]:
    parents = [a["Code"] for a in get_json(s, f"{FINGERTIPS}/areas/by_area_type", params={"area_type_id": SUB_ICB})]
    with ThreadPoolExecutor(workers) as pool:
        parts = list(pool.map(lambda p: fetch_parent(s, p), parents))
    rows, periods = latest_by_practice(pd.concat(parts, ignore_index=True))
    r = s.get(f"{FINGERTIPS}/area_addresses/csv/by_parent_area_code", timeout=120,
              params={"parent_area_code": "E92000001", "area_type_id": PRACTICE})
    r.raise_for_status()
    addr = pd.read_csv(io.StringIO(r.text))
    where = practice_constituencies(s, dict(zip(addr["Code"], addr["Postcode"])))
    log.info("NHS: %d practices, %d placed in constituencies", rows["Area Code"].nunique(), len(where))
    frames = seat_frames(rows, where)
    qof = periods.get(241) or next(iter(periods.values()), "")
    gpps = periods.get(94126, "")
    return frames, f"QOF {qof}; GP Patient Survey {gpps}".strip("; ")
