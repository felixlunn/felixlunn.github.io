"""Special educational needs and early years (DfE, via the explore education statistics API). England.

* Pupils with an education, health and care (EHC) plan or on SEN support, by
  the constituency their school is in (January school census).
* EHC plans issued within the statutory 20 weeks, by council (calendar year),
  shared out across seats.
* Take-up of funded early education by eligible (disadvantaged) 2-year-olds,
  by council, shared out across seats.

Data sets are found by publication and title, and filter options by label, so
new releases are picked up without code changes.
"""

from __future__ import annotations

import logging
import re

import pandas as pd
import requests

from ..http import get_json
from ..metrics import MetricMeta
from .councils import apportion, lad_to_county, regrouped_weights

log = logging.getLogger(__name__)

API = "https://api.education.gov.uk/statistics/v1"
SOURCE_URL = "https://explore-education-statistics.service.gov.uk/find-statistics/special-educational-needs-in-england"
SEN_PUB, SEN_SET = "Special educational needs in England", r"^Pupils in all schools, by type of SEN provision"
EHC_PUB, EHC_SET = "Education, health and care plans", r"^Timeliness of new education, health and care plans"
EY_PUB, EY_SET = "Funded early education and childcare", r"Children registered and take-up rates"

MIN_PLANS = 20
NOTE = " Council figures shared out across the constituencies each council covers."
CHILDREN_METRICS = [
    MetricMeta("pupils_ehc_plan", "Pupils with an EHC plan", "education", "%",
               "Pupils at schools in the constituency with an education, health and care plan (DfE school census, January).",
               "DfE special educational needs", "neutral", 1, ("send",)),
    MetricMeta("pupils_sen_support", "Pupils on SEN support", "education", "%",
               "Pupils at schools in the constituency with special educational needs but no EHC plan (SEN support).",
               "DfE special educational needs", "neutral", 1, ("send",)),
    MetricMeta("ehc_within_20_weeks", "EHC plans issued within 20 weeks", "education", "%",
               "New education, health and care plans issued within the statutory 20 weeks, excluding exceptions (DfE, "
               "latest calendar year)." + NOTE, "DfE education, health and care plans", "higher_better", 0, ("send",)),
    MetricMeta("early_years_2yo_takeup", "Funded childcare take-up by eligible 2-year-olds", "education", "%",
               "Estimated share of eligible (lower-income) 2-year-olds registered for funded early education (DfE, January)."
               + NOTE, "DfE funded early education", "higher_better", 0, ("early_years",)),
]


def find_dataset(s: requests.Session, publication: str, title: str) -> str:
    pubs = get_json(s, f"{API}/publications", params={"search": publication, "pageSize": 20}).get("results", [])
    pub = next(p for p in pubs if p["title"].strip().lower() == publication.lower())
    sets = get_json(s, f"{API}/publications/{pub['id']}/data-sets", params={"pageSize": 20}).get("results", [])
    match = [d for d in sets if re.search(title, d["title"], re.I)]
    if not match:
        raise LookupError(f"No {title!r} data set in {publication!r}")
    return match[0]["id"]


class DataSet:
    """One EES data set: its metadata, option lookups by label, and paged queries."""

    def __init__(self, s: requests.Session, dataset_id: str):
        self.s, self.id = s, dataset_id
        self.meta = get_json(s, f"{API}/data-sets/{dataset_id}/meta")
        self.codes = {o["id"]: o.get("code") for loc in self.meta["locations"] for o in loc["options"]}

    def indicator(self, label: str) -> str:
        return next(i["id"] for i in self.meta["indicators"] if i["label"].strip().lower() == label.lower())

    def option(self, filter_label: str, label: str) -> str:
        f = next(f for f in self.meta["filters"] if f["label"].strip().lower() == filter_label.lower())
        return next(o["id"] for o in f["options"] if o["label"].strip().lower() == label.lower())

    def filter_id(self, filter_label: str) -> str:
        return next(f["id"] for f in self.meta["filters"] if f["label"].strip().lower() == filter_label.lower())

    def latest_period(self) -> dict:
        p = self.meta["timePeriods"][-1]
        return {"period": p["period"], "code": p["code"]}

    def query(self, levels: list[str], filters: list[str], indicators: list[str], period: dict) -> list[dict]:
        and_ = [{"filters": {"eq": f}} for f in filters] + [{"geographicLevels": {"in": levels}}, {"timePeriods": {"eq": period}}]
        out, page = [], 1
        while True:
            r = self.s.post(f"{API}/data-sets/{self.id}/query", timeout=120,
                            json={"criteria": {"and": and_}, "indicators": indicators, "page": page, "pageSize": 1000})
            r.raise_for_status()
            d = r.json()
            out += d.get("results", [])
            if page >= d.get("paging", {}).get("totalPages", 1):
                return out
            page += 1

    def code(self, row: dict) -> str | None:
        level = row["geographicLevel"]
        return self.codes.get(row["locations"].get(level))


def number(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")  # suppressed or not applicable ("c", "x", "z")


def sen(ds: DataSet) -> tuple[dict[str, pd.DataFrame], str]:
    period = ds.latest_period()
    head = ds.indicator("Headcount of pupils")
    fixed = [ds.option("Hospital school flag", "Total"), ds.option("Phase type of school", "Total"),
             ds.option("School type (detailed)", "Total")]
    rows = ds.query(["PCON", "NAT"], fixed, [head], period)
    prov = ds.filter_id("Pupil SEN provision")
    labels = {ds.option("Pupil SEN provision", x): x for x in
              ("Education, health and care plan", "SEN support / SEN without an EHC plan", "Total")}
    d = pd.DataFrame([{"code": ds.code(r), "level": r["geographicLevel"], "kind": labels.get(r["filters"].get(prov)),
                       "n": number(r["values"].get(head))} for r in rows]).dropna(subset=["kind"])
    t = d.pivot_table(index=["level", "code"], columns="kind", values="n", aggfunc="sum")
    seats = t.loc["PCON"]
    seats = seats[seats.index.astype(str).str.match(r"^E14\d{6}$")]  # not "z" (school's seat unknown)
    frames = {}
    for mid, kind in [("pupils_ehc_plan", "Education, health and care plan"), ("pupils_sen_support", "SEN support / SEN without an EHC plan")]:
        f = pd.DataFrame({"num": seats[kind] * 100, "den": seats["Total"]})
        if "NAT" in t.index.get_level_values(0):
            nat = t.loc["NAT"].iloc[0]
            f.attrs["national"] = float(nat[kind] * 100 / nat["Total"])
        frames[mid] = f
    return frames, period["period"].replace("/", "-")


def by_council(ds: DataSet, filters: list[str], num: str, den: str, picks: dict[str, str] | None = None,
               period: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Council and national counts for indicator(s) in a period (default the latest); ``picks`` maps a filter id to
    {option id: column name}."""
    period = period or ds.latest_period()
    rows = ds.query(["LA", "NAT"], filters, sorted({num, den} - {None}), period)
    recs = []
    for r in rows:
        rec = {"code": ds.code(r), "level": r["geographicLevel"]}
        if picks:
            fid, options = picks
            col = options.get(r["filters"].get(fid))
            if col is None:
                continue
            rec[col] = number(r["values"].get(num))
        else:
            rec["num"], rec["den"] = number(r["values"].get(num)), number(r["values"].get(den))
        recs.append(rec)
    d = pd.DataFrame(recs).groupby(["level", "code"]).sum(min_count=1)
    return d, period


def councils_frame(d: pd.DataFrame, weights: pd.DataFrame, min_den: float = 0, past: bool = False) -> pd.DataFrame:
    la = d.loc["LA"].dropna(subset=["num", "den"])
    la = la[la["den"] >= max(min_den, 1e-9)]
    if past:  # earlier years: councils created since 2019 take their predecessors' rate
        from ..history import fill_successors
        la = la[~la.index.duplicated()]
        rate = fill_successors(la["num"] / la["den"])
        den = la["den"].reindex(rate.index).fillna(1.0)
        la = pd.DataFrame({"num": rate * den, "den": den})
    f = pd.DataFrame({"num": apportion(la["num"], weights) * 100, "den": apportion(la["den"], weights)})
    if "NAT" in d.index.get_level_values(0):
        nat = d.loc["NAT"].iloc[0]
        f.attrs["national"] = float(nat["num"] * 100 / nat["den"])
    return f


def ehc_timeliness(ds: DataSet, weights: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    filters = [ds.option("Characteristic breakdown topic of child or young person with EHC plan", "All EHC plans"),
               ds.option("Characteristics of child or young person with EHC plan", "All EHC plans"),
               ds.option("Exemption inclusion flag", "Excluding exemptions")]
    timely = ds.filter_id("Timeliness of EHC plan outcome")
    picks = (timely, {ds.option("Timeliness of EHC plan outcome", "Plans issued within 20 weeks"): "num",
                      ds.option("Timeliness of EHC plan outcome", "Total plans issued"): "den"})
    d, period = by_council(ds, filters, ds.indicator("Number of EHC plans"), None, picks)
    # A few councils report almost no plans (incomplete returns): leave out fewer than MIN_PLANS.
    return councils_frame(d, weights, MIN_PLANS), period["period"]


def early_years(ds: DataSet, weights: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    filters = [ds.option("Age", "2 years"), ds.option("Entitlement type", "Early learning for 2-year-olds")]
    d, period = by_council(ds, filters, ds.indicator("Number of registered children"),
                           ds.indicator("Estimated number of eligible children"))
    # Eligibility is an estimate, so a few councils register more children than "eligible": count those as 100%.
    d["num"] = d["num"].clip(upper=d["den"])
    return councils_frame(d, weights), period["period"]


def education_weights(weights: pd.DataFrame, county: dict[str, str]) -> pd.DataFrame:
    """Seat x council weights regrouped to education authorities: districts join their county (E10); unitary
    councils, metropolitan districts and London boroughs are education authorities themselves."""
    return regrouped_weights(weights, {lad: c for lad, c in county.items() if str(c).startswith("E10")})


def load_children(s: requests.Session, weights: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], str]:
    frames, notes = {}, []
    weights = education_weights(weights, lad_to_county(s))
    sen_frames, year = sen(DataSet(s, find_dataset(s, SEN_PUB, SEN_SET)))
    frames.update(sen_frames)
    notes.append(f"school census {year}")
    for mid, pub, title, fn, label in [
        ("ehc_within_20_weeks", EHC_PUB, EHC_SET, ehc_timeliness, "EHC plans"),
        ("early_years_2yo_takeup", EY_PUB, EY_SET, early_years, "early years"),
    ]:
        try:
            frames[mid], when = fn(DataSet(s, find_dataset(s, pub, title)), weights)
            notes.append(f"{label} {when}")
        except Exception as exc:  # noqa: BLE001 - keep the rest if one data set fails
            log.warning("%s failed: %s", mid, exc)
    return frames, "; ".join(notes)
