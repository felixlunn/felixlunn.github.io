"""Keep slow, slowly-changing sources between runs so each refresh only re-downloads what may have changed.

Set ``WHIPS_SOURCE_CACHE`` to a folder to turn this on (the deploy workflow does). A source listed in
``MAX_AGE_DAYS`` is reused until it is that many days old; any change to the pipeline code discards every
saved copy, so a new figure or a fix is never hidden by old data. If a source fails to update and an
older copy exists, the older copy is used and the failure is noted in ``STALE`` (shown as a failed update).
"""

from __future__ import annotations

import hashlib
import logging
import os
import pickle
import time
from pathlib import Path

log = logging.getLogger(__name__)

# How long each source's last successful download is reused. Sources not listed are fetched on every run.
MAX_AGE_DAYS = {
    "police": 6,        # ~10 minutes to fetch; police.uk adds a month of data monthly
    "epc": 13,          # ~5 minutes; millions of certificates, updated monthly
    "nhs": 13,          # ~2 minutes; QOF is annual, prescribing monthly
    "travel": 60,       # ~2 minutes; DfT's latest edition is 2019
    "energy": 27,       # annual
    "vehicles": 13,     # quarterly, two large files
    "roads": 13,        # annual, large file
    "green_space": 60,  # 2020 edition
    "university": 60,   # 2021 release
    "cqc": 6,           # monthly
    "sewage": 27,       # annual
    "rail": 27,         # annual
}
STALE: dict[str, str] = {}  # source id -> why an older copy is being shown


def _code_version() -> str:
    """A fingerprint of the pipeline code: saved copies made by different code are ignored."""
    h = hashlib.sha256()
    for p in sorted(Path(__file__).parent.rglob("*.py")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def cached(sid: str, load, folder: str | None = None, now: float | None = None):
    """``load()``, or its saved result when that is recent enough (see the module docstring)."""
    folder = folder if folder is not None else os.environ.get("WHIPS_SOURCE_CACHE")
    if not folder or sid not in MAX_AGE_DAYS:
        return load()
    now = time.time() if now is None else now
    path, version = Path(folder) / f"{sid}.pkl", _code_version()
    saved = None
    try:
        if path.exists():
            saved = pickle.loads(path.read_bytes())
            if saved.get("code") != version:
                saved = None
    except Exception as exc:  # noqa: BLE001 - an unreadable copy is just a cache miss
        log.warning("Ignoring unreadable saved copy of %s: %s", sid, exc)
        saved = None
    if saved and now - saved["saved"] < MAX_AGE_DAYS[sid] * 86400:
        log.info("%s: using copy saved %.1f days ago", sid, (now - saved["saved"]) / 86400)
        return saved["value"]
    try:
        value = load()
    except Exception as exc:  # noqa: BLE001
        if not saved:
            raise
        when = time.strftime("%-d %B %Y", time.gmtime(saved["saved"]))
        STALE[sid] = f"Update failed, showing data fetched on {when}: {str(exc)[:200]}"
        log.exception("%s failed; using the copy saved on %s", sid, when)
        return saved["value"]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pickle.dumps({"saved": now, "code": version, "value": value}))
    except Exception as exc:  # noqa: BLE001 - failing to save must not fail the build
        log.warning("Could not save %s: %s", sid, exc)
    return value
