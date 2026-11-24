"""Ready-made police.uk data for the FOI section's Policing tab, by police force area.

It sits beside uploaded FOI responses (same map, Lib Dem seats, Area view and key tools) but comes from the public
police.uk data the pipeline already fetches, so nobody has to upload it. Written to ``foi/police.json`` in the FOI
dataset format (see frontend/src/foi/types.ts):

* Crime by force: the street-level crime figures fetched for each seat (police.py), shared out to force areas by how
  much of each seat the area covers: crimes a year by type, and the outcome shares.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ..metrics import POLICE_CATEGORIES

SOURCE_URL = "https://data.police.uk/docs/"
CRIME_COLUMNS = [{"key": mid, "label": f"{label} (a year)", "unit": "count", "direction": "higher_worse"}
                 for _, (mid, label) in POLICE_CATEGORIES.items()] + [
    {"key": "outcome_no_suspect", "label": "Closed: no suspect identified (%)", "unit": "percent", "direction": "higher_worse"},
    {"key": "outcome_charged", "label": "Charged / court outcome (%)", "unit": "percent", "direction": "higher_better"}]


def _dataset(ds_id: str, title: str, period: str, notes: str, columns: list[dict], rows: list[dict], as_of: str) -> dict:
    return {
        "id": f"police-uk-{ds_id}", "builtin": "police.uk", "department": "policing", "geography": "police_force",
        "title": title, "foi_reference": None, "authority": "police.uk (public data)", "period": period,
        "requested_on": None, "received_on": None, "notes": notes, "columns": columns, "rows": rows, "unmatched": [],
        "summary": None, "file_path": None, "created_by": None, "created_by_email": "police.uk",
        "created_at": f"{as_of}T00:00:00Z", "updated_at": f"{as_of}T00:00:00Z",
    }


def _num(v) -> float:
    """A seat's count, with a missing figure (None or NaN) counting as none."""
    return float(v) if v is not None and pd.notna(v) else 0.0


def crime_dataset(frames: dict[str, pd.DataFrame], areas: list[dict], period: str | None, as_of: str) -> dict | None:
    """Crime by force area, built from the seat figures: each seat's counts shared by the area's share of the seat."""
    if "crime_rate" not in frames:
        return None
    # Seat crimes a year: the frames hold (annual count x 1,000) / residents.
    counts = {mid: frames[mid]["num"] / 1000 for _, (mid, _) in POLICE_CATEGORIES.items() if mid in frames}
    outcomes = {k: frames[k] for k in ("outcome_no_suspect", "outcome_charged") if k in frames}
    cols = [c for c in CRIME_COLUMNS if c["key"] in counts or c["key"] in outcomes]
    rows = []
    for a in areas:
        links = [(seat, share) for seat, share in a.get("seats", []) if pd.notna(counts["crime_rate"].get(seat))]
        if not links:
            continue
        values = {}
        for mid, s in counts.items():
            values[mid] = round(sum(_num(s.get(seat)) * share for seat, share in links))
        for k, f in outcomes.items():
            # Seats with no figure (e.g. no crimes with a final outcome yet) are left out of both sides.
            known = [(seat, share) for seat, share in links if seat in f.index and pd.notna(f.at[seat, "num"]) and pd.notna(f.at[seat, "den"])]
            num = sum(float(f.at[seat, "num"]) * share for seat, share in known)
            den = sum(float(f.at[seat, "den"]) * share for seat, share in known)
            values[k] = round(num / den, 1) if den else None
        rows.append({"code": a["code"], "source_name": a["name"], "values": values})
    if len(rows) < 30:
        return None
    notes = ("Street-level crime recorded on police.uk, counted within each constituency and shared out to force areas by "
             "how much of each seat the area covers; annualised. Forces not publishing to police.uk (e.g. Greater Manchester) "
             "are missing. Outcome shares are of crimes with a final recorded outcome; recent months are provisional.")
    return _dataset("crime", "Crime by force (police.uk)", period or "Latest months", notes, cols, rows, as_of)


def load_police_datasets(ref: dict, frames: dict[str, pd.DataFrame], crime_period: str | None,
                         as_of: str) -> tuple[list[dict], list[str]]:
    """The datasets, and any problems."""
    crime = crime_dataset(frames, ref["layers"]["police"]["areas"], crime_period, as_of)
    if crime:
        return [crime], []
    return [], ["crime: no seat figures from police.uk in this build"]


def write_police_datasets(out_dir: Path, datasets: list[dict], as_of: str) -> None:
    d = out_dir / "foi"
    d.mkdir(parents=True, exist_ok=True)
    (d / "police.json").write_text(json.dumps({"as_of": as_of, "datasets": datasets}, separators=(",", ":"), allow_nan=False))


def demo_police_datasets(ref: dict, rng) -> list[dict]:
    """SYNTHETIC crime by force for the demo build (one row per demo force area)."""
    rows = [{"code": a["code"], "source_name": a["name"], "values": {
        mid: int(rng.integers(200, 9_000)) for _, (mid, _) in POLICE_CATEGORIES.items()}
        | {"outcome_no_suspect": round(float(rng.uniform(35, 65)), 1), "outcome_charged": round(float(rng.uniform(4, 12)), 1)}}
        for a in ref["layers"]["police"]["areas"]]
    return [_dataset("crime", "Crime by force (police.uk)", "2026-07 to 2026-09", "SYNTHETIC demo data.", CRIME_COLUMNS, rows, "2026-11-01")]
