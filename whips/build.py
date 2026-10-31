"""Data pipeline: fetch every source, compute metrics, write the dashboard's static data files.

    python -m whips.build --out frontend/public/data

Outputs
    data.json           metrics catalogue, seats, columnar values, peer groups, source status
    boundaries.geojson  simplified July 2024 Westminster constituency boundaries
    constituencies.csv  wide table of every metric, for download / spreadsheets

Boundaries and Census 2021 are required (the build fails without them). The
other sources are optional: if one fails, the build continues and records the
failure in ``data.json`` so the dashboard can say what is missing.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import engine
from .http import session
from .metrics import (
    CENSUS_METRICS, CLAIMANT_METRICS, ELECTION_METRICS, POLICE_METRICS, THEMES, MetricMeta, census_meta,
)
from .sources import boundaries as bsrc
from .sources import nomis, parliament, police

log = logging.getLogger("whips.build")

COUNTRY_BY_PREFIX = {"E": "England", "W": "Wales", "S": "Scotland", "N": "Northern Ireland"}


def _clean(v: float, decimals: int = 3):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    return round(float(v), decimals)


def assemble(codes: list[str], frames: dict[str, pd.DataFrame], metas: list[MetricMeta]) -> tuple[list[dict], dict[str, list]]:
    """Align num/den frames to ``codes`` and compute values + national figures."""
    metrics, values = [], {}
    for meta in metas:
        f = frames.get(meta.id)
        if f is None:
            continue
        f = f.reindex(codes)
        num, den = f["num"].astype(float), f["den"].astype(float)
        val = (num / den).replace([np.inf, -np.inf], np.nan)
        ok = val.notna()
        if not ok.any():
            continue
        national = float(num[ok].sum() / den[ok].sum()) if den[ok].sum() else None
        metrics.append({
            "id": meta.id, "label": meta.label, "theme": meta.theme, "unit": meta.unit,
            "description": meta.description, "source": meta.source, "polarity": meta.polarity,
            "decimals": meta.decimals, "tags": list(meta.tags),
            "national": _clean(national), "coverage": int(ok.sum()),
        })
        values[meta.id] = [_clean(v) for v in val.tolist()]
    return metrics, values


def build(out_dir: Path, skip: set[str] | None = None) -> dict:
    skip = skip or set()
    out_dir.mkdir(parents=True, exist_ok=True)
    s = session()
    sources: list[dict] = []
    frames: dict[str, pd.DataFrame] = {}
    metas: list[MetricMeta] = []

    def record(sid, name, url, status, detail="", as_of=None):
        sources.append({"id": sid, "name": name, "url": url, "status": status, "detail": detail, "as_of": as_of})

    # 1. Boundaries (required)
    t0 = time.time()
    geo = bsrc.load_boundaries(s)
    codes = [f["properties"]["code"] for f in geo["features"]]
    names = {f["properties"]["code"]: f["properties"]["name"] for f in geo["features"]}
    record("boundaries", "ONS Open Geography: Westminster constituencies (July 2024)",
           "https://geoportal.statistics.gov.uk/", "ok", f"{len(codes)} constituencies", "July 2024")
    log.info("Boundaries: %d features (%.0fs)", len(codes), time.time() - t0)

    # 2. Census 2021 (required)
    t0 = time.time()
    census, _census_names, prov = nomis.load_census(s, CENSUS_METRICS)
    frames.update(census)
    metas += [census_meta(m) for m in CENSUS_METRICS]
    record("census", "Census 2021 (ONS via Nomis)", "https://www.nomisweb.co.uk/sources/census_2021",
           "ok", f"{len(prov['tables'])} tables; England & Wales only"
           + (f"; unavailable: {', '.join(sorted(prov['failed']))}" if prov["failed"] else ""), "March 2021")
    log.info("Census: %d metrics (%.0fs)", len(census), time.time() - t0)
    population = census["population"]["num"]

    # 3. Optional sources
    if "claimants" not in skip:
        try:
            cf, period = nomis.load_claimants(s)
            frames["claimant_rate"] = cf
            metas += CLAIMANT_METRICS
            record("claimants", "ONS Claimant Count (Nomis)", "https://www.nomisweb.co.uk/sources/cc", "ok", "", period)
        except Exception as exc:  # noqa: BLE001 - optional source
            log.exception("Claimant count failed")
            record("claimants", "ONS Claimant Count (Nomis)", "https://www.nomisweb.co.uk/sources/cc", "failed", str(exc))

    if "police" not in skip:
        try:
            t0 = time.time()
            pf, months = police.load_police(s, geo, population)
            frames.update(pf)
            metas += POLICE_METRICS
            record("police", "police.uk street-level crime", "https://data.police.uk/", "ok",
                   f"{len(months)} months; England, Wales & Northern Ireland; annualised",
                   f"{min(months)} to {max(months)}")
            log.info("Police: done (%.0fs)", time.time() - t0)
        except Exception as exc:  # noqa: BLE001
            log.exception("police.uk failed")
            record("police", "police.uk street-level crime", "https://data.police.uk/", "failed", str(exc))

    attrs = pd.DataFrame(index=codes)
    if "elections" not in skip:
        try:
            ef, eattrs = parliament.load_results(s)
            frames.update(ef)
            metas += ELECTION_METRICS
            attrs = attrs.join(eattrs, how="left")
            record("elections", "2024 general election results (House of Commons Library)",
                   "https://commonslibrary.parliament.uk/research-briefings/cbp-10009/", "ok", "", "4 July 2024")
        except Exception as exc:  # noqa: BLE001
            log.exception("Election results failed")
            record("elections", "2024 general election results (House of Commons Library)",
                   "https://commonslibrary.parliament.uk/research-briefings/cbp-10009/", "failed", str(exc))

    members: dict[str, dict] = {}
    if "members" not in skip:
        try:
            members = parliament.match_members(parliament.load_members(s), names)
            record("members", "Current MPs (UK Parliament Members API)", "https://members-api.parliament.uk/", "ok",
                   f"{len(members)} seats matched", datetime.now(timezone.utc).date().isoformat())
        except Exception as exc:  # noqa: BLE001
            log.exception("Members API failed")
            record("members", "Current MPs (UK Parliament Members API)", "https://members-api.parliament.uk/", "failed", str(exc))

    # 4. Assemble seats + values
    metrics, values = assemble(codes, frames, metas)
    seats = []
    for code in codes:
        a = attrs.loc[code].to_dict() if code in attrs.index else {}
        a = {k: v for k, v in a.items() if isinstance(v, str) and v}
        country = a.get("country") or COUNTRY_BY_PREFIX.get(code[0], "")
        m = members.get(code, {})
        seats.append({
            "code": code,
            "name": names[code],
            "country": country,
            "region": a.get("region") or (country if country != "England" else ""),
            "mp": m.get("mp") or a.get("mp_2024"),
            "party": m.get("party") or a.get("first_party"),
            "party_colour": m.get("party_colour"),
            "first_party_2024": a.get("first_party"),
            "second_party_2024": a.get("second_party"),
            "result_2024": a.get("result"),
        })
    return finish(out_dir, geo, seats, metrics, values, sources, demo=False)


def finish(out_dir: Path, geo: dict, seats: list[dict], metrics: list[dict], values: dict[str, list],
           sources: list[dict], demo: bool) -> dict:
    """Add peer groups and write all output files."""
    ds = engine.Dataset.from_json({"seats": seats, "metrics": metrics, "values": values})
    groups, group_meta = engine.peer_groups(ds)
    for seat, g in zip(seats, groups):
        seat["peer_group"] = g
    data = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "demo": demo,
        "themes": THEMES,
        "metrics": metrics,
        "seats": seats,
        "values": values,
        "peer_groups": group_meta,
        "sources": sources,
    }
    (out_dir / "data.json").write_text(json.dumps(data, separators=(",", ":"), allow_nan=False))
    (out_dir / "boundaries.geojson").write_text(json.dumps(geo, separators=(",", ":")))
    wide = pd.DataFrame({"code": [s["code"] for s in seats], "name": [s["name"] for s in seats],
                         "country": [s["country"] for s in seats], "region": [s["region"] for s in seats],
                         "mp": [s["mp"] for s in seats], "party": [s["party"] for s in seats]})
    for m in metrics:
        wide[m["id"]] = values[m["id"]]
    wide.to_csv(out_dir / "constituencies.csv", index=False)
    log.info("Wrote %s: %d seats, %d metrics", out_dir, len(seats), len(metrics))
    return data


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default="frontend/public/data", type=Path)
    p.add_argument("--skip", action="append", default=[], choices=["claimants", "police", "elections", "members"],
                   help="Skip an optional source (repeatable)")
    p.add_argument("--demo", action="store_true", help="Write a SYNTHETIC demo dataset (no network); for UI development only")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.demo:
        from .demo import build_demo
        build_demo(args.out)
    else:
        build(args.out, set(args.skip))


if __name__ == "__main__":
    main()
