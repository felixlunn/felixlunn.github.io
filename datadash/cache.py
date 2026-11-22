"""Keep slow, slowly-changing sources between runs so each refresh only re-downloads what may have changed.

Set ``DATADASH_SOURCE_CACHE`` to a folder to turn this on (the refresh workflow does, except on its weekly full
refresh, which re-downloads everything). A source with a ``keep`` period in the registry (``max_age_days`` here) is
reused until its saved copy is that old. A change to the source's own code (its module and the pipeline modules it
imports) discards its saved copy, so a new figure or a fix is never hidden by old data. If a source fails to update
and an older copy exists, the older copy is used and the failure is noted in ``STALE`` (shown as a failed update).
"""

from __future__ import annotations

import hashlib
import logging
import os
import pickle
import time
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)

STALE: dict[str, str] = {}  # source id -> why an older copy is being shown


def _code_version(files: Iterable[Path] | None = None) -> str:
    """A fingerprint of the code a saved copy came from: copies made by different code are ignored.
    ``files``: the source's own code (see registry.code_files); by default, the whole pipeline."""
    h = hashlib.sha256()
    for p in sorted(files if files is not None else Path(__file__).parent.rglob("*.py")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def cached(sid: str, load, folder: str | None = None, now: float | None = None,
           max_age_days: float | None = None, code_files: Iterable[Path] | None = None):
    """``load()``, or its saved result when it is less than ``max_age_days`` old (see the module docstring).
    Without ``max_age_days`` (or a cache folder) it always loads."""
    folder = folder if folder is not None else os.environ.get("DATADASH_SOURCE_CACHE")
    if not folder or not max_age_days:
        return load()
    now = time.time() if now is None else now
    path, version = Path(folder) / f"{sid}.pkl", _code_version(code_files)
    saved = None
    try:
        if path.exists():
            saved = pickle.loads(path.read_bytes())
            if saved.get("code") != version:
                saved = None
    except Exception as exc:  # noqa: BLE001 - an unreadable copy is just a cache miss
        log.warning("Ignoring unreadable saved copy of %s: %s", sid, exc)
        saved = None
    if saved and now - saved["saved"] < max_age_days * 86400:
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
