"""Census 2021 and claimant count data from the Nomis API.

Nomis (https://www.nomisweb.co.uk/api/v01/) publishes every Census 2021 topic
summary ("TS") table at 2024 Westminster constituency level, so no best-fit
aggregation from small areas is needed for the constituency view.

Dataset ids and the geography type code are discovered at run time from the
Nomis metadata API (with known fallbacks), so the pipeline keeps working if
Nomis renumbers things.
"""

from __future__ import annotations

import io
import logging
import os
import re
from collections.abc import Iterable

import numpy as np
import pandas as pd
import requests

from ..http import get_json
from ..metrics import CensusMetric

log = logging.getLogger(__name__)

BASE = "https://www.nomisweb.co.uk/api/v01"
PAGE = 25_000  # Nomis caps a single CSV response at 25,000 rows

# Last-resort fallbacks if metadata search fails. Discovery is preferred.
FALLBACK_DATASETS = {
    "TS001": "NM_2021_1",
    "TS004": "NM_2024_1",
    "TS007A": "NM_2020_1",
    "TS011": "NM_2031_1",
    "TS021": "NM_2041_1",
    "TS029": "NM_2048_1",
    "TS030": "NM_2049_1",
    "TS037": "NM_2055_1",
    "TS038": "NM_2056_1",
    "TS039": "NM_2057_1",
    "TS044": "NM_2062_1",
    "TS045": "NM_2063_1",
    "TS046": "NM_2064_1",
    "TS052": "NM_2070_1",
    "TS054": "NM_2072_1",
    "TS058": "NM_2075_1",
    "TS061": "NM_2078_1",
    "TS062": "NM_2079_1",
    "TS066": "NM_2083_1",
    "TS067": "NM_2084_1",
}
CLAIMANT_DATASET = "NM_162_1"

_META_PREFIXES = ("DATE", "GEOGRAPHY", "MEASURES", "MEASURE", "OBS_", "RECORD", "URN", "FREQ")


def _auth_params() -> dict[str, str]:
    uid = os.environ.get("NOMIS_UID")
    return {"uid": uid} if uid else {}


def _as_list(x) -> list:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _text(v) -> str:
    if isinstance(v, dict):
        return str(v.get("value", ""))
    return str(v or "")


def find_dataset(s: requests.Session, table: str) -> str:
    """Return the Nomis dataset id (e.g. NM_2072_1) for a census table code (e.g. TS054)."""
    try:
        data = get_json(s, f"{BASE}/dataset/def.sdmx.json", params={"search": f"{table}*", **_auth_params()})
        families = _as_list(data.get("structure", {}).get("keyfamilies", {}).get("keyfamily"))
        pat = re.compile(rf"^{re.escape(table)}\b", re.I)
        for fam in families:
            name = _text(fam.get("name"))
            if pat.search(name.strip()):
                return fam["id"]
    except (requests.RequestException, ValueError, KeyError) as exc:  # pragma: no cover - network
        log.warning("Nomis dataset search for %s failed: %s", table, exc)
    if table in FALLBACK_DATASETS:
        log.info("Using fallback dataset id for %s", table)
        return FALLBACK_DATASETS[table]
    raise LookupError(f"Could not find a Nomis dataset for census table {table}")


def pick_pcon_type(codes: Iterable[dict]) -> str:
    """Choose the 2024 Westminster constituency geography type from a Nomis codelist."""
    best = None
    for c in codes:
        desc = _text(c.get("description")).lower()
        if "parliamentary constituenc" in desc and "2024" in desc:
            best = str(c["value"])
            break
    if best is None:
        raise LookupError("No 2024 parliamentary constituency geography type listed")
    return best if best.upper().startswith("TYPE") else f"TYPE{best}"


def find_pcon_type(s: requests.Session, dataset_id: str) -> str:
    override = os.environ.get("NOMIS_PCON_TYPE")
    if override:
        return override
    data = get_json(s, f"{BASE}/dataset/{dataset_id}/geography/TYPE.def.sdmx.json", params=_auth_params())
    codelists = _as_list(data.get("structure", {}).get("codelists", {}).get("codelist"))
    codes = [c for cl in codelists for c in _as_list(cl.get("code"))]
    return pick_pcon_type(codes)


def fetch_csv(s: requests.Session, dataset_id: str, params: dict[str, str]) -> pd.DataFrame:
    """Download a Nomis dataset as CSV, following record-offset pagination."""
    frames, offset = [], 0
    while True:
        r = s.get(
            f"{BASE}/dataset/{dataset_id}.data.csv",
            params={**params, "recordoffset": offset, **_auth_params()},
            timeout=180,
        )
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        frames.append(df)
        if len(df) < PAGE:
            break
        offset += PAGE
    return pd.concat(frames, ignore_index=True)


def category_columns(df: pd.DataFrame) -> tuple[str, str]:
    """Identify the (code, label) columns of the single category dimension in a Nomis CSV."""
    name_cols = [
        c for c in df.columns
        if c.upper().endswith("_NAME") and not c.upper().startswith(_META_PREFIXES)
    ]
    if len(name_cols) != 1:
        raise ValueError(f"Expected exactly one category dimension, found {name_cols}")
    label_col = name_cols[0]
    code_col = label_col[: -len("_NAME")]
    if code_col not in df.columns:
        raise ValueError(f"Category code column {code_col} missing")
    return code_col, label_col


def tidy_census(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise a raw Nomis census CSV to columns: code, name, cat, label, value."""
    if "MEASURES" in df.columns:
        df = df[df["MEASURES"] == 20100]
    code_col, label_col = category_columns(df)
    out = pd.DataFrame({
        "code": df["GEOGRAPHY_CODE"].astype(str),
        "name": df["GEOGRAPHY_NAME"].astype(str),
        "cat": pd.to_numeric(df[code_col], errors="coerce"),
        "label": df[label_col].astype(str).str.strip(),
        "value": pd.to_numeric(df["OBS_VALUE"], errors="coerce"),
    })
    return out


def _norm(label: str) -> str:
    return re.sub(r"\s+", " ", label.strip().lower())


def is_total(cat: float, label: str) -> bool:
    return cat == 0 or _norm(label).startswith("total")


def select_categories(labels: Iterable[str], patterns: Iterable[str]) -> list[str]:
    """Labels matching any pattern, keeping only the top-most of nested categories.

    Nomis census tables mix aggregate categories ("Private rented") with their
    children ("Private rented: Private landlord or letting agency"). If both match,
    only the aggregate is kept so values are not double counted.
    """
    regs = [re.compile(p, re.I) for p in patterns]
    labels = list(dict.fromkeys(labels))
    hit = [lab for lab in labels if not _norm(lab).startswith("total") and any(r.search(_norm(lab)) for r in regs)]
    normed = {lab: _norm(lab) for lab in hit}
    keep = []
    for lab in hit:
        n = normed[lab]
        if any(n != o and n.startswith(o + ":") for o in normed.values()):
            continue
        keep.append(lab)
    return keep


def compute_census_metric(tidy: pd.DataFrame, metric: CensusMetric) -> pd.DataFrame:
    """Return numerator / denominator per constituency for one metric."""
    totals = tidy[[is_total(c, lab) for c, lab in zip(tidy["cat"], tidy["label"])]]
    if totals.empty:
        raise ValueError(f"{metric.table}: no total category found")
    # If a table has several "total" rows, the one with the lowest category code is the overall total.
    totals = totals.sort_values("cat").groupby("code", as_index=True).first()
    den = totals["value"]
    if metric.is_count:
        return pd.DataFrame({"num": den, "den": np.ones(len(den))}, index=den.index)
    labels = select_categories(tidy["label"].unique(), metric.include)
    if not labels:
        raise ValueError(f"{metric.id}: no categories in {metric.table} matched {metric.include}")
    log.debug("%s <- %s", metric.id, labels)
    num = tidy[tidy["label"].isin(labels)].groupby("code")["value"].sum().reindex(den.index)
    if metric.complement:
        num = den - num
    # Convention for every source: value = num / den (any scaling lives in num).
    return pd.DataFrame({"num": num * 100, "den": den})


def load_census(s: requests.Session, metrics: list[CensusMetric]) -> tuple[dict[str, pd.DataFrame], dict[str, str], dict]:
    """Fetch all census tables needed by ``metrics``.

    Returns (per-metric num/den frames, constituency names by code, provenance).
    """
    tables = sorted({m.table for m in metrics})
    geo_type = None
    out: dict[str, pd.DataFrame] = {}
    names: dict[str, str] = {}
    provenance = {"tables": {}}
    for table in tables:
        ds = find_dataset(s, table)
        if geo_type is None:
            geo_type = find_pcon_type(s, ds)
            provenance["geography_type"] = geo_type
            log.info("Nomis 2024 constituency geography type: %s", geo_type)
        log.info("Fetching %s (%s)", table, ds)
        tidy = tidy_census(fetch_csv(s, ds, {"geography": geo_type, "measures": "20100"}))
        provenance["tables"][table] = ds
        names.update(dict(zip(tidy["code"], tidy["name"])))
        for m in metrics:
            if m.table == table:
                out[m.id] = compute_census_metric(tidy, m)
    return out, names, provenance


def parse_claimants(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Turn a claimant count CSV (count + proportion measures) into num/den and a period label."""
    measure_col = "MEASURE_NAME" if "MEASURE_NAME" in df.columns else None
    if measure_col is None:
        raise ValueError("Claimant CSV lacks MEASURE_NAME column")
    df = df.copy()
    df["value"] = pd.to_numeric(df["OBS_VALUE"], errors="coerce")
    is_prop = df[measure_col].str.contains("proportion", case=False)
    count = df[~is_prop].groupby("GEOGRAPHY_CODE")["value"].sum()
    prop = df[is_prop].groupby("GEOGRAPHY_CODE")["value"].mean()
    den = (count / prop * 100).replace([np.inf, -np.inf], np.nan)
    period = str(df["DATE_NAME"].iloc[0]) if "DATE_NAME" in df.columns and len(df) else ""
    return pd.DataFrame({"num": count * 100, "den": den}), period


def load_claimants(s: requests.Session) -> tuple[pd.DataFrame, str]:
    geo_type = find_pcon_type(s, CLAIMANT_DATASET)
    df = fetch_csv(s, CLAIMANT_DATASET, {
        "geography": geo_type, "date": "latest", "gender": "0", "age": "0",
        "measure": "1,2", "measures": "20100",
    })
    return parse_claimants(df)
