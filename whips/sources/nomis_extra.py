"""Non-census Nomis datasets published for July 2024 Westminster constituencies.

    ASHE  (NM_30_1, NM_99_1)  median earnings of residents / of jobs located in the seat   GB
    APS   (NM_17_5)           employment, inactivity and occupation rates                   GB
    BRES  (NM_189_1)          jobs located in the seat, by industry                         GB
    UK Business Counts (NM_141_1)  business sites (local units) by size                     UK
    Small-area population estimates (NM_2014_1)  population change since the census         E&W

Each dataset is optional and loaded independently: one failing doesn't stop the
others. Every frame follows the pipeline's convention (value = num / den).
Medians can't be summed, so earnings frames carry the official UK median in
``frame.attrs["national"]``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

import pandas as pd
import requests

from ..http import get_json
from ..metrics import MetricMeta
from .nomis import BASE, _auth_params, fetch_csv, find_pcon_type

log = logging.getLogger(__name__)

UK = "2092957697"  # Nomis geography id for the United Kingdom

ASHE_RESIDENT, ASHE_WORKPLACE = "NM_30_1", "NM_99_1"
APS, BRES, BUSINESS_COUNTS, POP_ESTIMATES = "NM_17_5", "NM_189_1", "NM_141_1", "NM_2014_1"

ASHE_URL = "https://www.nomisweb.co.uk/sources/ashe"
APS_URL = "https://www.nomisweb.co.uk/sources/aps"
BRES_URL = "https://www.nomisweb.co.uk/sources/bres"
BUSINESS_URL = "https://www.nomisweb.co.uk/sources/ukbc"
POPEST_URL = "https://www.nomisweb.co.uk/sources/pest"


def _m(id, label, unit, description, source, polarity="neutral", decimals=1) -> MetricMeta:
    return MetricMeta(id, label, "jobs", unit, description, source, polarity, decimals, ("nomis",))


# (metric id, ASHE dataset, sex code, pay code, label, description)
ASHE_SERIES = [
    ("pay_weekly_ft", ASHE_RESIDENT, "8", "1", "Median weekly pay, full-time (residents)",
     "Median gross weekly pay of full-time employees who live in the constituency (ASHE resident analysis)."),
    ("pay_annual_all", ASHE_RESIDENT, "7", "7", "Median annual pay, all workers (residents)",
     "Median gross annual pay of all employees (full- and part-time) who live in the constituency (ASHE resident analysis)."),
    ("pay_weekly_ft_jobs", ASHE_WORKPLACE, "8", "1", "Median weekly pay, full-time (jobs based here)",
     "Median gross weekly pay of full-time jobs located in the constituency, wherever the worker lives (ASHE workplace analysis)."),
]
ASHE_METRICS = [_m(mid, label, "£", desc, "ONS ASHE (Nomis)", "higher_better", 0) for mid, _, _, _, label, desc in ASHE_SERIES]

# (metric id, APS variable, label, polarity, description)
APS_SERIES = [
    ("aps_employment_rate", "45", "Employment rate 16-64 (APS)", "higher_better",
     "Share of residents aged 16-64 in employment (Annual Population Survey, 12 months). Survey estimate: small seats have wide margins of error."),
    ("aps_inactive", "111", "Economically inactive 16-64 (APS)", "higher_worse",
     "Share of residents aged 16-64 neither in work nor looking for work (Annual Population Survey, 12 months)."),
    ("aps_soc_1_3", "1793", "Managerial, professional & technical jobs (APS)", "neutral",
     "Share of employed residents in SOC 2020 major groups 1-3: managers, professionals, and associate professional and technical occupations."),
]
APS_METRICS = [_m(mid, label, "%", desc, "ONS Annual Population Survey (Nomis)", pol) for mid, _, label, pol, desc in APS_SERIES]

# BRES industry groups as SIC 2007 two-digit divisions.
BRES_GROUPS = {
    "jobs_agriculture": ("Agriculture, forestry & fishing", range(1, 4)),
    "jobs_manufacturing": ("Manufacturing", range(10, 34)),
    "jobs_construction": ("Construction", range(41, 44)),
    "jobs_retail": ("Wholesale & retail", range(45, 48)),
    "jobs_logistics": ("Transport & storage", range(49, 54)),
    "jobs_hospitality": ("Hospitality", range(55, 57)),
    "jobs_ict": ("Information & communication", range(58, 64)),
    "jobs_finance_professional": ("Finance, professional & scientific", [*range(64, 67), *range(69, 76)]),
    "jobs_public_admin": ("Public administration & defence", [84]),
    "jobs_education": ("Education", [85]),
    "jobs_health": ("Health & social care", range(86, 89)),
    "jobs_arts": ("Arts, entertainment & recreation", range(90, 94)),
}
BRES_METRICS = [
    _m("jobs_density", "Jobs per working-age resident", "ratio",
       "Jobs located in the constituency (employees plus working owners, BRES) per resident aged 16-64 (APS population estimate). Above 1 means a net importer of workers.",
       "ONS BRES and APS (Nomis)", "neutral", 2),
    *[
        _m(mid, f"Jobs in {label.lower()}", "%",
           f"Share of jobs located in the constituency that are in {label.lower()} (BRES, SIC 2007).", "ONS BRES (Nomis)")
        for mid, (label, _) in BRES_GROUPS.items()
    ],
]

BUSINESS_METRICS = [
    _m("business_sites_per_1k", "Business sites per 1,000 working-age residents", "per 1,000",
       "VAT/PAYE-registered business sites (local units) per 1,000 residents aged 16-64 (UK Business Counts; APS population estimate).",
       "ONS UK Business Counts (Nomis)", "neutral", 1),
    _m("business_micro", "Micro business sites (0-9 staff)", "%",
       "Share of business sites (local units) employing fewer than 10 people.", "ONS UK Business Counts (Nomis)"),
]

POPEST_METRICS = [
    MetricMeta("pop_change", "Population change since 2021", "people", "%",
               "Change in usual resident population from mid-2021 to the latest ONS small-area population estimate.",
               "ONS population estimates (Nomis)", "neutral", 1, ("nomis",)),
]


def _csv(s: requests.Session, ds: str, geo_type: str, **params) -> pd.DataFrame:
    df = fetch_csv(s, ds, {"geography": geo_type, **params})
    df["value"] = pd.to_numeric(df["OBS_VALUE"], errors="coerce")
    return df


def _period(df: pd.DataFrame) -> str:
    return str(df["DATE_NAME"].iloc[0]) if "DATE_NAME" in df.columns and len(df) else ""


def load_ashe(s: requests.Session) -> tuple[dict[str, pd.DataFrame], str]:
    out, period = {}, ""
    for mid, ds, sex, pay, *_ in ASHE_SERIES:
        geo = find_pcon_type(s, ds)
        df = _csv(s, ds, f"{geo},{UK}", date="latest", sex=sex, item="2", pay=pay, measures="20100")
        uk = df.loc[df["GEOGRAPHY"].astype(str) == UK, "value"]
        seats = df[df["GEOGRAPHY"].astype(str) != UK].set_index("GEOGRAPHY_CODE")["value"]
        f = pd.DataFrame({"num": seats, "den": 1.0})
        f.attrs["national"] = float(uk.iloc[0]) if len(uk) and pd.notna(uk.iloc[0]) else None
        out[mid] = f
        period = _period(df)
    return out, period


def load_aps(s: requests.Session) -> tuple[dict[str, pd.DataFrame], pd.Series, str]:
    """APS rates as num/den, plus the 16-64 population (denominator of the employment rate)."""
    geo = find_pcon_type(s, APS)
    df = _csv(s, APS, geo, date="latest", variable=",".join(v for _, v, *_ in APS_SERIES), measures="20599,21001,21002")
    out = {}
    pop = pd.Series(dtype=float)
    for mid, var, *_ in APS_SERIES:
        d = df[df["VARIABLE"].astype(str) == var].pivot_table(index="GEOGRAPHY_CODE", columns="MEASURES", values="value", aggfunc="first")
        if d.empty or 21001 not in d or 21002 not in d:
            continue
        num = d[21001].where(d[20599].notna()) if 20599 in d else d[21001]  # drop suppressed estimates
        out[mid] = pd.DataFrame({"num": num * 100, "den": d[21002]})
        if var == "45":
            pop = d[21002]
    return out, pop, _period(df)


def division_codes(s: requests.Session, ds: str) -> dict[int, str]:
    """SIC 2007 two-digit division number -> Nomis industry code ("10 : Manufacture of food products")."""
    data = get_json(s, f"{BASE}/dataset/{ds}/industry.def.sdmx.json", params=_auth_params())
    out: dict[int, str] = {}
    for cl in data["structure"]["codelists"]["codelist"]:
        for c in cl["code"]:
            m = re.match(r"^(\d{2}) : ", c["description"]["value"])
            if m:
                out.setdefault(int(m.group(1)), str(c["value"]))
    return out


def bres_frames(df: pd.DataFrame, divisions: dict[int, str], pop_16_64: pd.Series) -> dict[str, pd.DataFrame]:
    """Industry shares of local jobs, and jobs per working-age resident, from a BRES extract."""
    total = df[df["INDUSTRY"].astype(str) == "37748736"].groupby("GEOGRAPHY_CODE")["value"].sum(min_count=1)
    out = {}
    for mid, (_, divs) in BRES_GROUPS.items():
        codes = {divisions[d] for d in divs if d in divisions}
        if not codes:
            continue
        num = df[df["INDUSTRY"].astype(str).isin(codes)].groupby("GEOGRAPHY_CODE")["value"].sum(min_count=1)
        out[mid] = pd.DataFrame({"num": num.reindex(total.index) * 100, "den": total})
    if len(pop_16_64):
        out["jobs_density"] = pd.DataFrame({"num": total, "den": pop_16_64.reindex(total.index)})
    return out


def load_bres(s: requests.Session, pop_16_64: pd.Series) -> tuple[dict[str, pd.DataFrame], str]:
    divisions = division_codes(s, BRES)
    wanted = sorted({divisions[d] for _, divs in BRES_GROUPS.values() for d in divs if d in divisions})
    geo = find_pcon_type(s, BRES)
    df = _csv(s, BRES, geo, date="latest", industry=",".join(["37748736", *wanted]),
              employment_status="4", measure="1", measures="20100")
    return bres_frames(df, divisions, pop_16_64), _period(df)


def load_business(s: requests.Session, pop_16_64: pd.Series) -> tuple[dict[str, pd.DataFrame], str]:
    geo = find_pcon_type(s, BUSINESS_COUNTS)
    df = _csv(s, BUSINESS_COUNTS, geo, date="latest", industry="37748736", employment_sizeband="0,10",
              legal_status="0", measures="20100")
    by = df.pivot_table(index="GEOGRAPHY_CODE", columns="EMPLOYMENT_SIZEBAND", values="value", aggfunc="first")
    out = {"business_micro": pd.DataFrame({"num": by[10] * 100, "den": by[0]})}
    if len(pop_16_64):
        out["business_sites_per_1k"] = pd.DataFrame({"num": by[0] * 1000, "den": pop_16_64.reindex(by.index)})
    return out, _period(df)


def load_popest(s: requests.Session) -> tuple[dict[str, pd.DataFrame], str]:
    geo = find_pcon_type(s, POP_ESTIMATES)
    df = _csv(s, POP_ESTIMATES, geo, date="2021,latest", gender="0", c_age="200", measures="20100")
    by = df.pivot_table(index="GEOGRAPHY_CODE", columns="DATE_NAME", values="value", aggfunc="first")
    by.columns = [str(c) for c in by.columns]
    latest = max(by.columns)
    if latest == "2021":
        raise ValueError("no estimates after 2021")
    return {"pop_change": pd.DataFrame({"num": (by[latest] - by["2021"]) * 100, "den": by["2021"]})}, f"mid-2021 to mid-{latest}"


def load_all(s: requests.Session, skip: set[str], record: Callable[..., None]) -> tuple[dict[str, pd.DataFrame], list[MetricMeta]]:
    """Load every dataset not in ``skip``; record each one's status via ``record(id, name, url, status, detail, as_of)``."""
    frames: dict[str, pd.DataFrame] = {}
    metas: list[MetricMeta] = []
    pop_16_64 = pd.Series(dtype=float)

    def attempt(sid: str, name: str, url: str, detail: str, fn, meta_list: list[MetricMeta]):
        if sid in skip:
            return
        try:
            got, period = fn()
            got = {k: v for k, v in got.items() if not v.empty}
            if not got:
                raise ValueError("no data returned")
            frames.update(got)
            metas.extend(m for m in meta_list if m.id in got)
            record(sid, name, url, "ok", detail, period)
        except Exception as exc:  # noqa: BLE001 - optional source
            log.exception("%s failed", name)
            record(sid, name, url, "failed", str(exc)[:300])

    def aps():
        nonlocal pop_16_64
        got, pop_16_64, period = load_aps(s)
        return got, period

    attempt("aps", "Annual Population Survey (ONS via Nomis)", APS_URL, "Great Britain; 12-month survey estimates", aps, APS_METRICS)
    attempt("ashe", "Annual Survey of Hours and Earnings (ONS via Nomis)", ASHE_URL, "Great Britain; medians", lambda: load_ashe(s), ASHE_METRICS)
    attempt("bres", "Business Register and Employment Survey (ONS via Nomis)", BRES_URL, "Great Britain; jobs by workplace",
            lambda: load_bres(s, pop_16_64), BRES_METRICS)
    attempt("business", "UK Business Counts (ONS via Nomis)", BUSINESS_URL, "Local units; per-resident rate GB only",
            lambda: load_business(s, pop_16_64), BUSINESS_METRICS)
    attempt("popest", "Small-area population estimates (ONS via Nomis)", POPEST_URL, "England & Wales", lambda: load_popest(s), POPEST_METRICS)
    return frames, metas


__all__ = ["load_all", "ASHE_METRICS", "APS_METRICS", "BRES_METRICS", "BUSINESS_METRICS", "POPEST_METRICS", "bres_frames"]
