"""ERIC (Estates Returns Information Collection) for the FOI Health tab: ten years of NHS trust estates data.

NHS England publishes ERIC each year on digital.nhs.uk, which refuses automated downloads, so the trust-level
returns for 2016/17 to 2025/26 are kept in the repository (``eric/eric_trusts.csv.gz``: one row per trust per
year, with measures renamed over the years merged under their latest name). To add a year, append its trust-level
rows to that file with the same columns.

The returns become ready-made FOI datasets (like the police.uk crime data on Policing), one per theme (car parking,
capital investment, fire safety...) and per map layer: hospital and community trusts on the Trusts layer, mental
health trusts and ambulance trusts on theirs, so each is compared with its own kind. Each measure has a column per
year, so the FOI pages show its trend and % change.

* Trusts that merged: a former trust's figures are added to the trust that took it over (from NHS ODS successions),
  so today's trusts have figures for every year. All but two measures are totals (money, counts, staff, tonnes);
  the two percentages are averaged.
* From 2019/20, ERIC publishes income and contributions as negative numbers; they are turned back to positive.
* "Not Applicable" and "No Data Provided" are left blank.
Written to ``foi/eric.json`` in the FOI dataset format (see frontend/src/foi/types.ts).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pandas as pd
import requests

from ..http import get_json

log = logging.getLogger(__name__)

SOURCE_URL = "https://digital.nhs.uk/data-and-information/publications/statistical/estates-returns-information-collection"
DATA = Path(__file__).with_name("eric") / "eric_trusts.csv.gz"
ODS_URL = "https://directory.spineservices.nhs.uk/ORD/2-0-0/organisations"
ID_COLUMNS = {"Year", "Trust Code", "Trust Name", "Commissioning Region", "Old Commissioning Region", "Trust Type", "Status"}
SKIP_UNITS = {"Yes/No", "Select"}  # answers, not figures
MIN_ROWS = 5

# Themes: (id, title, the measures in it as name patterns, in order (the first is the dataset's headline), default
# direction, {pattern: direction} exceptions). A measure goes in the first theme with a pattern it matches.
THEMES: list[tuple[str, str, list[str], str, dict[str, str]]] = [
    ("parking", "Car parking income", [r"car parking - patients", r"car parking - staff"], "higher_worse", {}),
    ("capital", "Capital investment", [r"^Capital investment for new build", r"^Capital investment", r"funding investment", r"Charity and/or grant",
                                       r"Investment to reduce backlog"], "higher_better", {}),
    ("fire", "Fire safety", [r"^Fires recorded", r"False alarms", r"from fires", r"during evacuation"], "higher_worse", {}),
    ("incidents", "Estates incidents and overheating", [r"^Clinical service incidents", r"RIDDOR", r"^Estates and facilities related incidents",
                                                       r"Overheating", r"clinical space monitored"], "higher_worse",
     {r"clinical space monitored": "higher_better"}),
    ("sites", "Sites", [r"^Total number of sites", r"^Number of sites", r"^Sites "], "neutral", {r"unreported": "higher_worse"}),
    ("sustainability", "Energy, waste and carbon", [r"Energy efficient schemes costs", r"energy efficient schemes", r"Waste re-use", r"WEEE",
                                                   r"Energy managers", r"Waste managers"], "higher_better", {r"WEEE": "neutral"}),
    ("income", "Income and contributions to costs", [r"^Total contributions", r"^Contribution to costs", r"^Income from"], "neutral", {}),
    ("workforce", "Estates staff and medical records", [r"^Medical Records cost", r"wholly owned subsidiary", r"apprenticeship"], "neutral",
     {r"apprenticeship": "higher_better"}),
    ("other", "Other measures (some years only)", [r"Cost Improvement", r"Premises and Facilities", r"."], "neutral",
     {r"savings from Cost Improvement|planned savings": "higher_better", r"Premises and Facilities Assurance action plan": "higher_worse"}),
]

LAYERS = [("nhs_trust", "hospital", "trusts"), ("mh_trust", "mental_health", "mental health trusts"),
          ("ambulance_trust", "ambulance", "ambulance trusts")]


def split_unit(name: str) -> tuple[str, str]:
    """("Fires recorded", "No.") from "Fires recorded (No.)"."""
    m = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", name)
    return (m.group(1), m.group(2)) if m else (name, "")


def unit_of(u: str) -> str:
    u = u.lower().rstrip(".")
    return {"£": "money", "no": "count", "%": "percent"}.get(u, "other")


def year_start(year: str) -> int:
    return int(year[:4])


def theme_of(measure: str) -> tuple[str, str]:
    """(theme id, direction) for a measure."""
    for tid, _, patterns, direction, exceptions in THEMES:
        if any(re.search(p, measure, re.I) for p in patterns):
            for p, d in exceptions.items():
                if re.search(p, measure, re.I):
                    return tid, d
            return tid, direction
    raise AssertionError("the last theme matches everything")


def order_in_theme(measure: str, tid: str) -> int:
    patterns = next(t[2] for t in THEMES if t[0] == tid)
    return next(i for i, p in enumerate(patterns) if re.search(p, measure, re.I))


def load_returns(path: Path = DATA) -> pd.DataFrame:
    """The returns, long: Year, Trust Code, Trust Name, measure, value (numbers only, income made positive)."""
    raw = pd.read_csv(path, dtype=str)
    measures = [c for c in raw.columns if c not in ID_COLUMNS and split_unit(c)[1] not in SKIP_UNITS]
    long = raw.melt(id_vars=["Year", "Trust Code", "Trust Name"], value_vars=measures, var_name="measure", value_name="raw")
    long["value"] = pd.to_numeric(long["raw"].str.replace(",", "", regex=False), errors="coerce")
    long = long.dropna(subset=["value"]).drop(columns="raw")
    income = long["measure"].str.match(r"^(Income from|Contribution to costs|Total contributions)")
    flip = income & (long["Year"].map(year_start) >= 2019)
    long.loc[flip, "value"] = -long.loc[flip, "value"]
    long["Trust Code"] = long["Trust Code"].str.strip().str.upper()
    return long


def successors(s: requests.Session, codes: set[str], current: set[str]) -> dict[str, str]:
    """{former trust code: the current trust it's now part of}, following ODS successions (newest first)."""
    out: dict[str, str] = {}
    for code in sorted(codes - current):
        c, seen = code, set()
        while c not in current and c not in seen and len(seen) < 6:
            seen.add(c)
            try:
                org = get_json(s, f"{ODS_URL}/{c}").get("Organisation", {})
            except requests.RequestException as exc:
                log.warning("ODS lookup of %s failed: %s", c, exc)
                break
            succ = [x for x in (org.get("Succs") or {}).get("Succ", []) if x.get("Type") == "Successor"]
            if not succ:
                break
            succ.sort(key=lambda x: max((d.get("Start", "") for d in x.get("Date", [])), default=""), reverse=True)
            c = succ[0]["Target"]["OrgId"]["extension"]
        if c in current:
            out[code] = c
    return out


def layer_members(ref: dict) -> dict[str, set[str]]:
    """The trust codes on each FOI map layer."""
    trusts = ref["points"].get("trusts", [])
    return {
        "nhs_trust": {t["code"] for t in trusts if not t.get("groups") or "hospital" in t["groups"]},
        "mh_trust": {a["code"] for a in ref["layers"].get("mental_health", {}).get("areas", [])},
        "ambulance_trust": {a["code"] for a in ref["layers"].get("ambulance", {}).get("areas", [])},
    }


def build_datasets(long: pd.DataFrame, members: dict[str, set[str]], moved: dict[str, str], names: dict[str, str], as_of: str) -> tuple[list[dict], list[str]]:
    """The datasets, and the ERIC trusts that match no current trust."""
    known = set().union(*members.values())
    long = long.assign(code=long["Trust Code"].map(lambda c: c if c in known else moved.get(c)))
    unmatched = sorted(set(long.loc[long["code"].isna(), "Trust Name"]))
    long = long.dropna(subset=["code"])
    pct = long["measure"].map(lambda m: unit_of(split_unit(m)[1]) == "percent")
    totals = pd.concat([long[~pct].groupby(["code", "measure", "Year"])["value"].sum(),
                        long[pct].groupby(["code", "measure", "Year"])["value"].mean()])
    years = sorted(long["Year"].unique(), key=year_start)
    span = f"{years[0]} to {years[-1]}"
    measures = sorted(long["measure"].unique(), key=lambda m: (theme_of(m)[0], order_in_theme(m, theme_of(m)[0]), m))
    out = []
    for g, _, plural in LAYERS:
        codes = members[g]
        for tid, title, *_ in THEMES:
            cols, keys = [], {}
            for i, m in enumerate(x for x in measures if theme_of(x)[0] == tid):
                label, u = split_unit(m)
                if u.lower().rstrip(".") not in {"£", "no", "%"}:
                    label = f"{label} ({u})"
                present = sorted({y for (c, mm, y) in totals.index if mm == m and c in codes}, key=year_start)
                for y in present:
                    key = f"m{i}_{year_start(y)}"
                    keys[(m, y)] = key
                    cols.append({"key": key, "label": f"{label} {y}", "unit": unit_of(u), "direction": theme_of(m)[1], "period": y, "series": label})
            rows = []
            for code in sorted(codes):
                values = {k: round(float(totals[(code, m, y)]), 2) for (m, y), k in keys.items() if (code, m, y) in totals.index}
                if values:
                    rows.append({"code": code, "source_name": names.get(code, code), "values": values})
            if len(rows) < MIN_ROWS:  # e.g. car parking: one ambulance trust has any
                continue
            notes = (f"NHS Estates Returns Information Collection (ERIC), trust-level returns {span}, as published by NHS England. "
                     "Measures change over the years, so some have figures for only some years. Where trusts merged, the former "
                     "trusts' figures are added to the trust that took them over. Income from 2019/20 is published as negative "
                     "numbers and shown here as positive. Blank: not collected that year, not applicable or not provided.")
            out.append({
                "id": f"eric-{tid}-{g}", "builtin": "ERIC", "department": "health", "geography": g,
                "title": f"ERIC: {title} ({plural})",
                "foi_reference": None, "authority": "NHS England (ERIC)", "period": span, "requested_on": None, "received_on": None,
                "notes": notes, "columns": cols, "rows": rows, "unmatched": [],
                "summary": None, "file_path": None, "created_by": None, "created_by_email": "ERIC",
                "created_at": f"{as_of}T00:00:00Z", "updated_at": f"{as_of}T00:00:00Z",
            })
    return out, unmatched


def load_eric_datasets(s: requests.Session, ref: dict, as_of: str) -> tuple[list[dict], list[str]]:
    """The datasets, and any problems."""
    long = load_returns()
    members = layer_members(ref)
    known = set().union(*members.values())
    moved = successors(s, set(long["Trust Code"]), known)
    names = {t["code"]: t["name"] for t in ref["points"].get("trusts", [])}
    names |= {a["code"]: a["name"] for layer in ("mental_health", "ambulance") for a in ref["layers"].get(layer, {}).get("areas", [])}
    sets, unmatched = build_datasets(long, members, moved, names, as_of)
    if unmatched:
        log.warning("ERIC: %d trusts match no current trust: %s", len(unmatched), unmatched[:10])
    problems = [] if sets else ["no ERIC datasets built"]
    return sets, problems


def write_eric_datasets(out_dir: Path, datasets: list[dict], as_of: str) -> None:
    d = out_dir / "foi"
    d.mkdir(parents=True, exist_ok=True)
    (d / "eric.json").write_text(json.dumps({"as_of": as_of, "datasets": datasets}, separators=(",", ":"), allow_nan=False))


def demo_eric_datasets(ref: dict, as_of: str = "2026-11-01") -> list[dict]:
    """ERIC for the demo build: the real returns (they're in the repository) can't match demo trusts, so each demo trust
    takes a real trust's figures in turn. SYNTHETIC pairing."""
    long = load_returns()
    members = layer_members(ref)
    real = sorted(set(long.loc[long["Year"] == long["Year"].max(), "Trust Code"]))
    demo_codes = sorted(set().union(*members.values()))
    pair = {r: demo_codes[i] for i, r in enumerate(real[:len(demo_codes)])}
    long = long[long["Trust Code"].isin(pair)].assign(**{"Trust Code": lambda d: d["Trust Code"].map(pair)})
    names = {t["code"]: t["name"] for t in ref["points"].get("trusts", [])}
    names |= {a["code"]: a["name"] for layer in ("mental_health", "ambulance") for a in ref["layers"].get(layer, {}).get("areas", [])}
    sets = build_datasets(long, members, {}, names, as_of)[0]
    for d in sets:
        d["notes"] = "SYNTHETIC demo pairing: real ERIC figures attached to made-up trusts. " + d["notes"]
    return sets
