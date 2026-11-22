"""Party names as they appear in the sources ("Liberal Democrat", "Lib Dems", "LD"...).

The frontend has the same rule in frontend/src/foi/analysis.ts (isLibDem): keep them in step.
"""

from __future__ import annotations

import re

LIB_DEM = re.compile(r"^(liberal democrats?|lib ?dems?|ld)$", re.I)


def is_lib_dem(party: str | None) -> bool:
    return bool(LIB_DEM.match((party or "").strip()))
