"""NHS Business Services Authority open data: GP prescribing and NHS dentistry, England.

Both come from the NHSBSA open data portal (CKAN), using its SQL endpoint so
the aggregation happens server-side:

* English Prescribing Dataset (latest month): items per GP practice for a few
  BNF sections, turned into items per 1,000 registered patients for the
  practices located in each seat (list sizes and practice locations come from
  the NHS step, so the denominators match).
* English contractor monthly general dental activity: patients seen per dental
  contract (adults in the last 24 months, children in the last 12), placed in
  seats by the contract's LSOA, per 1,000 residents.
"""

from __future__ import annotations

import logging
import re

import pandas as pd
import requests

from ..http import get_json
from ..metrics import MetricMeta

log = logging.getLogger(__name__)

API = "https://opendata.nhsbsa.net/api/3/action"
EPD_PACKAGE = "english-prescribing-dataset-epd-with-snomed-code"
DENTAL_PACKAGE = "english-contractor-monthly-general-dental-activity"
SOURCE_URL = "https://opendata.nhsbsa.net/"

# metric id -> (label, BNF code prefix, description)
PRESCRIBING = {
    "rx_antidepressants": ("Antidepressant prescriptions", "0403", "antidepressants (BNF 4.3)"),
    "rx_opioids": ("Opioid painkiller prescriptions", "040702", "opioid analgesics (BNF 4.7.2)"),
    "rx_anxiolytics": ("Sleeping pill and anti-anxiety prescriptions", "0401", "hypnotics and anxiolytics (BNF 4.1)"),
    "rx_antibiotics": ("Antibiotic prescriptions", "0501", "antibiotics (BNF 5.1)"),
}
PRESCRIBING_METRICS = [
    MetricMeta(mid, f"{label} per 1,000 patients", "health", "per 1,000",
               f"Prescription items for {desc} in a month, per 1,000 patients registered at GP practices located in the "
               "constituency (NHSBSA English Prescribing Dataset).", "NHSBSA English Prescribing Dataset", "neutral", 1, ("nhs",))
    for mid, (label, _, desc) in PRESCRIBING.items()
]
DENTAL_METRICS = [
    MetricMeta("dental_adults_per_1k", "Adults seen by an NHS dentist per 1,000 residents", "health", "per 1,000",
               "Adults seen by an NHS dentist in the last 24 months at dental practices in the constituency, per 1,000 "
               "residents (NHSBSA dental activity). Low values mean little NHS dentistry nearby.",
               "NHSBSA dental activity", "higher_better", 0, ("dental",)),
    MetricMeta("dental_children_per_1k", "Children seen by an NHS dentist per 1,000 residents", "health", "per 1,000",
               "Children seen by an NHS dentist in the last 12 months at dental practices in the constituency, per 1,000 "
               "residents (NHSBSA dental activity).", "NHSBSA dental activity", "higher_better", 0, ("dental",)),
]


def latest_resource(s: requests.Session, package: str, prefix: str) -> str:
    """Name of the newest monthly resource in a package, e.g. EPD_SNOMED_202608."""
    names = [r["name"] for r in get_json(s, f"{API}/package_show", params={"id": package})["result"]["resources"]
             if r.get("datastore_active") and re.fullmatch(prefix + r"\d{6}", r.get("name", ""))]
    if not names:
        raise LookupError(f"No {prefix}YYYYMM resources in {package}")
    return max(names)


def sql(s: requests.Session, resource: str, query: str) -> list[dict]:
    data = get_json(s, f"{API}/datastore_search_sql", params={"resource_id": resource, "sql": query}, timeout=300)
    inner = data.get("result", {})
    inner = inner.get("result", inner)  # the portal nests a second result object
    return inner.get("records", [])


def load_prescribing(s: requests.Session, where: dict[str, str], list_size: pd.Series) -> tuple[dict[str, pd.DataFrame], str]:
    """Items per 1,000 patients by seat. ``where``: practice -> seat; ``list_size``: practice -> registered patients."""
    res = latest_resource(s, EPD_PACKAGE, "EPD_SNOMED_")
    seats = pd.Series(where)
    patients = list_size[list_size.index.isin(seats.index)].groupby(seats).sum()
    frames = {}
    for mid, (_, prefix, _) in PRESCRIBING.items():
        rows = sql(s, res, f"SELECT PRACTICE_CODE, SUM(ITEMS) AS items FROM `{res}` "
                           f"WHERE BNF_PRESENTATION_CODE LIKE '{prefix}%' GROUP BY PRACTICE_CODE")
        items = pd.Series({r["PRACTICE_CODE"]: float(r["items"] or 0) for r in rows})
        # Only practices with a list size, so numerator and denominator cover the same patients.
        items = items[items.index.isin(list_size.index) & items.index.isin(seats.index)]
        by_seat = items.groupby(seats).sum()
        frames[mid] = pd.DataFrame({"num": by_seat.reindex(patients.index).fillna(0) * 1000, "den": patients})
    return frames, f"{res[-6:-2]}-{res[-2:]}"


def load_dental(s: requests.Session, lsoa_to_pcon: dict[str, str], population: pd.Series) -> tuple[dict[str, pd.DataFrame], str]:
    res = latest_resource(s, DENTAL_PACKAGE, "UDA_CONTRACTOR_")
    rows = sql(s, res, f"SELECT LSOA21_CODE, ADULT_24M_COUNT, CHILD_12M_COUNT FROM `{res}`")
    df = pd.DataFrame(rows)
    df["pcon"] = df["LSOA21_CODE"].map(lsoa_to_pcon)
    df = df.dropna(subset=["pcon"])
    adults = pd.to_numeric(df["ADULT_24M_COUNT"], errors="coerce").groupby(df["pcon"]).sum()
    children = pd.to_numeric(df["CHILD_12M_COUNT"], errors="coerce").groupby(df["pcon"]).sum()
    england = population[population.index.str.startswith("E")]
    return {
        "dental_adults_per_1k": pd.DataFrame({"num": adults.reindex(england.index).fillna(0) * 1000, "den": england}),
        "dental_children_per_1k": pd.DataFrame({"num": children.reindex(england.index).fillna(0) * 1000, "den": england}),
    }, f"{res[-6:-2]}-{res[-2:]}"
