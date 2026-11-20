"""Spotting sources that have stopped picking up new releases.

Each run records, per source, the date its reported period (``as_of``) last changed, carried forward from the
previously published data.json. A source whose period hasn't changed for longer than its publisher's normal
cycle (plus some slack) is marked ``overdue``: the publisher may be late, or may have moved or renamed the
release so the pipeline no longer finds the newest one. The deploy workflow raises an alert for these.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

MONTHLY, QUARTERLY, HALF_YEARLY, ANNUAL, DAILY = 50, 120, 220, 430, 4

# Days a source's period may stay unchanged before it is flagged. Sources not listed never change
# (Census 2021, the 2024 election, DfT's 2019 journey times...) or report no comparable period.
EXPECTED_DAYS = {
    # daily
    "members": DAILY, "debates": DAILY, "gias": DAILY,
    # monthly
    "police": MONTHLY, "claimants": MONTHLY, "rents": MONTHLY, "dental": MONTHLY, "heat_pumps": MONTHLY, "ofsted": MONTHLY,
    # quarterly
    "vehicles": QUARTERLY, "homelessness": QUARTERLY, "courts": QUARTERLY, "aps": QUARTERLY, "pharmacies": QUARTERLY,
    "asylum": QUARTERLY, "ev": QUARTERLY,
    # twice a year
    "police_workforce": HALF_YEARLY,
    # annual
    "fuel_poverty": ANNUAL, "bres": ANNUAL, "ashe": ANNUAL, "popest": ANNUAL, "air_pollution": ANNUAL, "energy": ANNUAL,
    "renewables": ANNUAL, "insolvency": ANNUAL, "business_demography": ANNUAL, "affordability": ANNUAL, "ks4": ANNUAL,
    "business": ANNUAL, "council_tax": ANNUAL, "roads": ANNUAL, "life_expectancy": ANNUAL, "fire": ANNUAL,
    "child_poverty": ANNUAL, "buses": ANNUAL, "income": ANNUAL, "road_condition": ANNUAL, "sewage": ANNUAL, "nhs": ANNUAL,
    "pupils": ANNUAL, "children": ANNUAL, "public_health": ANNUAL, "housing_stock": ANNUAL, "council_control": ANNUAL,
}


def stamp(sources: list[dict], previous: dict | None, today: date | None = None) -> None:
    """Add ``since`` (date the period was first seen) and ``overdue`` to each source, in place."""
    today = today or date.today()
    before = {s["id"]: s for s in (previous or {}).get("sources", [])}
    for s in sources:
        old = before.get(s["id"])
        if s.get("status") == "ok" and s.get("as_of") is not None:
            same = old is not None and old.get("as_of") == s["as_of"] and old.get("since")
            s["since"] = old["since"] if same else today.isoformat()
        elif old and old.get("since"):  # a failed run keeps the last known date
            s["since"] = old["since"]
        limit = EXPECTED_DAYS.get(s["id"])
        s["overdue"] = bool(limit and s.get("since") and (today - date.fromisoformat(s["since"])).days > limit)


def load_previous() -> dict | None:
    """The previously published data.json, if the workflow fetched it (``WHIPS_PREVIOUS_DATA``)."""
    path = os.environ.get("WHIPS_PREVIOUS_DATA")
    if not path or not Path(path).exists():
        return None
    try:
        return json.loads(Path(path).read_text())
    except ValueError:
        log.warning("Ignoring unreadable previous data at %s", path)
        return None
