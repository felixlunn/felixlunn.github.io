"""What a source's loader can use while the pipeline runs, and how its result is recorded.

One ``BuildContext`` is created per build. Loaders read what they need from it (the session, boundaries,
population, lazily-loaded lookups) and a few write results back (e.g. the MPs, council control, petitions).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import pandas as pd
import requests

from .cache import STALE, cached
from .metrics import MetricMeta
from .sources import boundaries as bsrc
from .sources import councils as councils_src

if TYPE_CHECKING:
    from .registry import Source

log = logging.getLogger("whips.build")


@dataclass
class BuildContext:
    s: requests.Session
    out_dir: Path
    skip: set[str]
    geo: dict = field(default_factory=dict)
    codes: list[str] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)
    frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    metas: list[MetricMeta] = field(default_factory=list)
    census: dict[str, pd.DataFrame] = field(default_factory=dict)
    sources: list[dict] = field(default_factory=list)
    lsoa_frames: dict[str, pd.DataFrame] | None = None
    # Written by sources for later ones, or for the final output
    imd_deciles: pd.Series | None = None
    pop_16_64: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    attrs: pd.DataFrame = field(default_factory=pd.DataFrame)
    members: dict[str, dict] = field(default_factory=dict)
    councils: dict | None = None
    petitions: dict | None = None
    _lsoa_lookup: dict[str, str] | None = None
    _council_weights: pd.DataFrame | None = None
    # How a source's download is (re)used: (source id, loader, max age in days, code files) -> result. Tests replace it.
    fetch: Callable = field(default=None)  # type: ignore[assignment]

    @property
    def population(self) -> pd.Series:
        return self.frames["population"]["num"]

    def electorate(self) -> pd.Series:
        """Electors (2024 register) where known, else population: for per-voter rates."""
        return (self.frames["turnout"]["den"] if "turnout" in self.frames else self.population).dropna()

    def lsoa_lookup(self) -> dict[str, str]:
        """LSOA -> July 2024 constituency (fetched once, when first needed)."""
        if self._lsoa_lookup is None:
            self._lsoa_lookup = bsrc.load_lsoa_pcon_lookup(self.s)
            log.info("LSOA -> constituency lookup: %d LSOAs", len(self._lsoa_lookup))
        return self._lsoa_lookup

    def council_weights(self) -> pd.DataFrame:
        """Seat x council overlaps (fetched once, shared by the council-level sources)."""
        if self._council_weights is None:
            self._council_weights = councils_src.seat_council_weights(self.lsoa_lookup(), councils_src.lsoa_to_lad(self.s))
        return self._council_weights

    def record(self, sid: str, name: str, url: str, status: str, detail: str = "", as_of: str | None = None) -> None:
        if status == "ok" and sid in STALE:  # an older saved copy is shown because the update failed
            status, detail = "failed", STALE[sid]
        self.sources.append({"id": sid, "name": name, "url": url, "status": status, "detail": detail, "as_of": as_of})

    def run(self, src: "Source") -> None:
        """Run one source: its own ``run``, or the generic load. A failure is recorded, never raised."""
        if src.when and not src.when(self):
            return
        if src.run:
            src.run(self, src)
            return
        from .registry import code_files
        fetch = self.fetch or (lambda sid, load, keep, files: cached(sid, load, max_age_days=keep, code_files=files))
        try:
            out = fetch(src.id, lambda: src.load(self), src.keep, code_files(src.module))
            got, period, *rest = out  # loaders return (frames, period) or (frames, period, detail)
            detail = rest[0] if rest else src.detail
            got = {k: v for k, v in got.items() if v is not None and not getattr(v, "empty", False)}
            if src.metrics and not got:
                raise ValueError("no data returned")
            self.frames.update(got)
            self.metas.extend(m for m in src.metrics if m.id in got)
            self.record(src.id, src.name, src.url, "ok", detail, period)
        except Exception as exc:  # noqa: BLE001 - optional source
            log.exception("%s failed", src.name)
            self.record(src.id, src.name, src.url, "failed", str(exc)[:300])
