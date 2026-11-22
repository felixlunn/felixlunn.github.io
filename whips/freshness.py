"""Spotting sources that have stopped picking up new releases.

Each run records, per source, the date its reported period (``as_of``) last changed, carried forward from the
previously published data.json. A source whose period hasn't changed for longer than its publisher's normal
cycle (plus some slack; set per source in registry.py) is marked ``overdue``: the publisher may be late, or may
have moved or renamed the release so the pipeline no longer finds the newest one. The refresh workflow raises an
alert for these.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)


def stamp(sources: list[dict], previous: dict | None, today: date | None = None, expected: dict[str, int] | None = None) -> None:
    """Add ``since`` (date the period was first seen) and ``overdue`` to each source, in place. ``expected``: source id
    -> days its period may stay unchanged (default: each source's update cycle in the registry)."""
    today = today or date.today()
    if expected is None:
        from .registry import expected_days
        expected = expected_days()
    before = {s["id"]: s for s in (previous or {}).get("sources", [])}
    for s in sources:
        old = before.get(s["id"])
        if s.get("status") == "ok" and s.get("as_of") is not None:
            same = old is not None and old.get("as_of") == s["as_of"] and old.get("since")
            s["since"] = old["since"] if same else today.isoformat()
        elif old and old.get("since"):  # a failed run keeps the last known date
            s["since"] = old["since"]
        limit = expected.get(s["id"])
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
