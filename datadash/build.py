"""Data pipeline: fetch every source, compute metrics, write the dashboard's static data files.

    python -m datadash.build --out frontend/public/data

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

from . import freshness, peers
from .cache import cached
from .context import BuildContext
from .history import assemble_history
from .http import session
from .parties import is_lib_dem
from .metrics import CENSUS_METRICS, THEMES, MetricMeta, census_meta, source_url
from .registry import BY_ID, SOURCES, code_files, expected_days, skip_names
from .sources import boundaries as bsrc
from .sources import debates as debates_src
from .sources import foi_geo as foi_src
from .sources import lsoa as lsoa_src
from .sources import nomis
from .sources import police_priorities as priorities_src
from .sources import scotland as scotland_src

log = logging.getLogger("datadash.build")


SKIPPABLE = skip_names()  # every --skip name, from the registry

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
            "description": meta.description, "source": meta.source, "source_url": source_url(meta.source),
            "polarity": meta.polarity,
            "decimals": meta.decimals, "tags": list(meta.tags),
            "national": _clean(national), "coverage": int(ok.sum()),
        })
        values[meta.id] = [_clean(v) for v in val.tolist()]
    return metrics, values


def build(out_dir: Path, skip: set[str] | None = None) -> dict:
    """Run every source (see registry.py) and write the output files."""
    out_dir.mkdir(parents=True, exist_ok=True)
    c = BuildContext(s=session(), out_dir=out_dir, skip=skip or set())
    skipped = lambda sid: BY_ID[sid].skip_name in c.skip  # noqa: E731

    # 1. Boundaries (required)
    t0 = time.time()
    c.geo = bsrc.load_boundaries(c.s)
    c.codes = [f["properties"]["code"] for f in c.geo["features"]]
    c.names = {f["properties"]["code"]: f["properties"]["name"] for f in c.geo["features"]}
    src = BY_ID["boundaries"]
    c.record(src.id, src.name, src.url, "ok", f"{len(c.codes)} constituencies", "July 2024")
    log.info("Boundaries: %d features (%.0fs)", len(c.codes), time.time() - t0)

    # 2. Census 2021 (required), with Scotland's Census 2022 filling the Scottish seats where defined the same way
    t0 = time.time()
    if "lsoa" not in c.skip and not skipped("neighbourhoods"):
        c.lsoa_frames = {}
    c.census, _census_names, prov = nomis.load_census(c.s, CENSUS_METRICS, None if "lsoa" in c.skip else c.lsoa_lookup, c.lsoa_frames)
    c.frames.update(c.census)
    c.metas += [census_meta(m) for m in CENSUS_METRICS]
    src = BY_ID["census"]
    c.record(src.id, src.name, src.url, "ok", f"{len(prov['tables'])} tables; England & Wales only"
             + (f"; {len(prov['aggregated_from_lsoa'])} summed from LSOAs (ONS best-fit)" if prov.get("aggregated_from_lsoa") else "")
             + (f"; unavailable: {', '.join(sorted(prov['failed']))}" if prov["failed"] else ""), "March 2021")
    log.info("Census: %d metrics (%.0fs)", len(c.census), time.time() - t0)
    if not skipped("scotland"):
        src = BY_ID["scotland"]
        try:
            scot, period = cached(src.id, lambda: scotland_src.load_scotland(c.s, c.geo), max_age_days=src.keep)
            for mid, f in scot.items():
                if mid in c.frames:
                    base = c.frames[mid]
                    c.frames[mid] = pd.concat([base[~base.index.isin(f.index)], f])
            c.record(src.id, src.name, src.url, "ok", f"{len(scot)} census figures for Scottish seats, summed from output areas", period)
        except Exception as exc:  # noqa: BLE001 - optional source
            log.exception("Scotland's Census failed")
            c.record(src.id, src.name, src.url, "failed", str(exc)[:300])
    c.attrs = pd.DataFrame(index=c.codes)

    # 3. Every other source, in registry order
    for src in SOURCES:
        if src.stage == "main" and src.skip_name not in c.skip:
            t0 = time.time()
            c.run(src)
            log.info("%s (%.0fs)", src.id, time.time() - t0)

    # 4. Assemble seats + values
    metrics, values = assemble(c.codes, c.frames, c.metas)
    history = assemble_history(c.codes, c.frames, metrics)
    log.info("History: %d metrics with past periods", len(history["metrics"]))
    seats = seat_list(c)

    # 5. Steps that need the seats
    neighbourhoods = None
    if c.lsoa_frames:
        src = BY_ID["neighbourhoods"]
        try:
            # Neighbourhood (LSOA) profiles are published for Lib Dem-held seats.
            chosen = {st["code"]: st["name"] for st in seats if is_lib_dem(st.get("party"))}
            neighbourhoods = lsoa_src.write_seat_files(c.s, out_dir, chosen, c.lsoa_lookup(), c.lsoa_frames, c.imd_deciles)
            c.record(src.id, src.name, src.url, "ok",
                     f"{len(neighbourhoods['seats'])} Lib Dem seats in England & Wales; {neighbourhoods['lsoas']} LSOAs", "March 2021")
        except Exception as exc:  # noqa: BLE001
            log.exception("Neighbourhood profiles failed")
            c.record(src.id, src.name, src.url, "failed", str(exc))

    debates: list[dict] = []
    if not skipped("debates"):
        src = BY_ID["debates"]
        try:
            debates = debates_src.load_debates(c.s)
            c.record(src.id, src.name, src.url, "ok", f"{len(debates)} debates in the next 3 weeks", datetime.now(timezone.utc).date().isoformat())
        except Exception as exc:  # noqa: BLE001
            log.exception("What's On calendar failed")
            c.record(src.id, src.name, src.url, "failed", str(exc))

    # Neighbourhood policing priorities for each seat's briefing (policing.json). Teams update them every few
    # months, so a fetched copy is reused for a week; if police.uk fails, the copy already live is kept.
    if not skipped("policing"):
        src = BY_ID["policing"]
        try:
            fetch = c.fetch or (lambda sid, load, keep, files: cached(sid, load, max_age_days=keep, code_files=files))
            pri = fetch(src.id, lambda: priorities_src.load_priorities(c.s, c.geo), src.keep, code_files(src.module))
            priorities_src.write_priorities(out_dir, pri, datetime.now(timezone.utc).date().isoformat())
            n_teams = sum(len(v) for v in pri["seats"].values())
            c.record(src.id, src.name, src.url, "ok", f"{n_teams} teams' priorities across {len(pri['seats'])} seats; England, Wales & NI",
                     datetime.now(timezone.utc).date().isoformat())
        except Exception as exc:  # noqa: BLE001
            log.exception("Policing priorities failed")
            c.record(src.id, src.name, src.url, "failed", str(exc)[:300])

    # Reference geographies for the password-protected FOI research section (police forces, courts, NHS bodies).
    if not skipped("foi"):
        src = BY_ID["foi"]
        try:
            ref, areas, problems = foi_src.load_foi_reference(c.s, c.geo, seats, c.population.to_dict(),
                                                              datetime.now(timezone.utc).date().isoformat())
            foi_src.write_foi(out_dir, ref, areas)
            c.record(src.id, src.name, src.url, "failed" if problems else "ok",
                     "; ".join(problems) or f"{len(ref['layers']['police']['areas'])} forces, {len(ref['layers']['health']['areas'])} NHS areas, "
                     f"{len(ref['points'].get('courts', []))} courts, {len(ref['points'].get('trusts', []))} trusts")
        except Exception as exc:  # noqa: BLE001
            log.exception("FOI reference failed")
            c.record(src.id, src.name, src.url, "failed", str(exc)[:300])

    freshness.stamp(c.sources, freshness.load_previous(), expected=expected_days())
    return finish(out_dir, c.geo, seats, metrics, values, c.sources, demo=False, debates=debates, neighbourhoods=neighbourhoods,
                  petitions=c.petitions, history=history, councils=c.councils)


def seat_list(c: BuildContext) -> list[dict]:
    """One record per seat: name, nation, region, current MP and party, 2024 result."""
    seats = []
    for code in c.codes:
        a = c.attrs.loc[code].to_dict() if code in c.attrs.index else {}
        a = {k: v for k, v in a.items() if isinstance(v, str) and v}
        country = a.get("country") or COUNTRY_BY_PREFIX.get(code[0], "")
        m = c.members.get(code, {})
        seats.append({
            "code": code,
            "name": c.names[code],
            "country": country,
            "region": a.get("region") or (country if country != "England" else ""),
            "mp": m.get("mp") or a.get("mp_2024"),
            "party": m.get("party") or a.get("first_party"),
            "party_colour": m.get("party_colour"),
            "first_party_2024": a.get("first_party"),
            "second_party_2024": a.get("second_party"),
            "result_2024": a.get("result"),
        })
    return seats


def finish(out_dir: Path, geo: dict, seats: list[dict], metrics: list[dict], values: dict[str, list],
           sources: list[dict], demo: bool, debates: list[dict] | None = None, neighbourhoods: dict | None = None,
           petitions: dict | None = None, history: dict | None = None, councils: dict | None = None) -> dict:
    """Add peer groups and write all output files."""
    groups, group_meta = peers.peer_groups(seats, metrics, values)
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
        "petitions": petitions,
        "councils": councils,
    }
    hist = (history or {}).get("metrics", {})
    for m in metrics:
        if m["id"] in hist:
            m["history"] = len(hist[m["id"]]["periods"])  # periods available in history.json
    (out_dir / "data.json").write_text(json.dumps(data, separators=(",", ":"), allow_nan=False))
    (out_dir / "history.json").write_text(json.dumps({"metrics": hist}, separators=(",", ":"), allow_nan=False))
    (out_dir / "boundaries.geojson").write_text(json.dumps(geo, separators=(",", ":")))
    wide = pd.DataFrame({"code": [s["code"] for s in seats], "name": [s["name"] for s in seats],
                         "country": [s["country"] for s in seats], "region": [s["region"] for s in seats],
                         "mp": [s["mp"] for s in seats], "party": [s["party"] for s in seats]})
    wide = pd.concat([wide, pd.DataFrame({m["id"]: values[m["id"]] for m in metrics})], axis=1)
    wide.to_csv(out_dir / "constituencies.csv", index=False)
    log.info("Wrote %s: %d seats, %d metrics", out_dir, len(seats), len(metrics))
    return data


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default="frontend/public/data", type=Path)
    p.add_argument("--skip", action="append", default=[], choices=SKIPPABLE,
                   help="Skip an optional source (repeatable); 'lsoa' skips the slow LSOA fallback for census tables")
    p.add_argument("--demo", action="store_true", help="Write a SYNTHETIC demo dataset (no network); for UI development only")
    p.add_argument("--list-sources", action="store_true", help="Print the names --skip accepts, one per line, and exit")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    if args.list_sources:
        print("\n".join(SKIPPABLE))
        return
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.demo:
        from .demo import build_demo
        build_demo(args.out)
    else:
        build(args.out, set(args.skip))


if __name__ == "__main__":
    main()
