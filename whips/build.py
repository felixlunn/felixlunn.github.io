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
import re
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
from .sources import debates as debates_src
from .sources import lsoa as lsoa_src
from .sources import nomis, nomis_extra, parliament, police

log = logging.getLogger("whips.build")

# Neighbourhood (LSOA) profiles are published for seats held by this party.
NEIGHBOURHOOD_PARTY = re.compile(r"^(liberal democrats?|lib ?dems?|ld)$", re.I)

SKIPPABLE = ["neighbourhoods", "debates", "claimants", "aps", "ashe", "bres", "business", "popest", "police", "elections", "members", "lsoa"]

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
        official = f.attrs.get("national")  # e.g. a UK median, which can't be built from seat medians
        f = f.reindex(codes)
        num, den = f["num"].astype(float), f["den"].astype(float)
        val = (num / den).replace([np.inf, -np.inf], np.nan)
        ok = val.notna()
        if not ok.any():
            continue
        national = official if official is not None else float(num[ok].sum() / den[ok].sum()) if den[ok].sum() else None
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
    lookup_cache: dict = {}

    def lsoa_lookup():
        if "v" not in lookup_cache:
            lookup_cache["v"] = bsrc.load_lsoa_pcon_lookup(s)
            log.info("LSOA -> constituency lookup: %d LSOAs", len(lookup_cache["v"]))
        return lookup_cache["v"]

    want_lsoa = "lsoa" not in skip and "neighbourhoods" not in skip
    lsoa_frames: dict[str, pd.DataFrame] | None = {} if want_lsoa else None
    census, _census_names, prov = nomis.load_census(s, CENSUS_METRICS, None if "lsoa" in skip else lsoa_lookup, lsoa_frames)
    frames.update(census)
    metas += [census_meta(m) for m in CENSUS_METRICS]
    record("census", "Census 2021 (ONS via Nomis)", "https://www.nomisweb.co.uk/sources/census_2021",
           "ok", f"{len(prov['tables'])} tables; England & Wales only"
           + (f"; {len(prov['aggregated_from_lsoa'])} summed from LSOAs (ONS best-fit)" if prov.get("aggregated_from_lsoa") else "")
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

    extra_frames, extra_metas = nomis_extra.load_all(s, skip, record)
    frames.update(extra_frames)
    metas += extra_metas

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
            try:
                ef, eattrs = parliament.load_results(s)
                source = ("2024 general election results (House of Commons Library)",
                          "https://commonslibrary.parliament.uk/research-briefings/cbp-10009/")
            except Exception as exc:  # noqa: BLE001 - the Library file can refuse automated downloads
                log.warning("Commons Library results unavailable (%s); using the Members API", exc)
                ef, eattrs = parliament.load_results_api(s, names)
                source = ("2024 general election results (UK Parliament Members API)", "https://members-api.parliament.uk/")
            frames.update(ef)
            metas += ELECTION_METRICS
            attrs = attrs.join(eattrs, how="left")
            record("elections", *source, "ok", f"{len(eattrs)} constituencies", "4 July 2024")
        except Exception as exc:  # noqa: BLE001
            log.exception("Election results failed")
            record("elections", "2024 general election results", "https://members-api.parliament.uk/", "failed", str(exc))

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
    neighbourhoods = None
    if lsoa_frames:
        try:
            chosen = {st["code"]: st["name"] for st in seats if st.get("party") and NEIGHBOURHOOD_PARTY.match(st["party"].strip())}
            neighbourhoods = lsoa_src.write_seat_files(s, out_dir, chosen, lsoa_lookup(), lsoa_frames)
            record("neighbourhoods", "Neighbourhood (LSOA) census profiles", "https://geoportal.statistics.gov.uk/", "ok",
                   f"{len(neighbourhoods['seats'])} Lib Dem seats in England & Wales; {neighbourhoods['lsoas']} LSOAs", "March 2021")
        except Exception as exc:  # noqa: BLE001
            log.exception("Neighbourhood profiles failed")
            record("neighbourhoods", "Neighbourhood (LSOA) census profiles", "https://geoportal.statistics.gov.uk/", "failed", str(exc))

    debates: list[dict] = []
    if "debates" not in skip:
        try:
            debates = debates_src.load_debates(s)
            record("debates", "Upcoming Commons debates (UK Parliament What's On)", debates_src.SOURCE_URL, "ok",
                   f"{len(debates)} debates in the next 3 weeks", datetime.now(timezone.utc).date().isoformat())
        except Exception as exc:  # noqa: BLE001
            log.exception("What's On calendar failed")
            record("debates", "Upcoming Commons debates (UK Parliament What's On)", debates_src.SOURCE_URL, "failed", str(exc))
    return finish(out_dir, geo, seats, metrics, values, sources, demo=False, debates=debates, neighbourhoods=neighbourhoods)


def finish(out_dir: Path, geo: dict, seats: list[dict], metrics: list[dict], values: dict[str, list],
           sources: list[dict], demo: bool, debates: list[dict] | None = None, neighbourhoods: dict | None = None) -> dict:
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
        "debates": debates or [],
        "debate_topics": debates_src.topic_catalogue(),
        "neighbourhoods": neighbourhoods,
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
    p.add_argument("--skip", action="append", default=[], choices=SKIPPABLE,
                   help="Skip an optional source (repeatable); 'lsoa' skips the slow LSOA fallback for census tables")
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
