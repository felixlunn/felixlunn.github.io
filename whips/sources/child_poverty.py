"""Children in low income families by constituency (DWP local area statistics), UK.

DWP publishes the number and share of children (aged under 16) in relative low
income families by Westminster constituency, both after housing costs (AHC,
modelled from the survey) and before housing costs (BHC, from benefit and tax
credit records). The latest edition is found via the GOV.UK content API.
"""

from __future__ import annotations

import logging
import re

import pandas as pd
import requests

from ..http import get_json
from ..history import with_history
from ..metrics import MetricMeta
from ..ods import find_table, read_ods

log = logging.getLogger(__name__)

COLLECTION = "https://www.gov.uk/api/content/government/collections/children-in-low-income-families-local-area-statistics"
CONTENT = "https://www.gov.uk/api/content"
SOURCE_URL = "https://www.gov.uk/government/collections/children-in-low-income-families-local-area-statistics"

CHILD_POVERTY_METRICS = [
    MetricMeta("child_poverty_ahc", "Children in poverty (after housing costs)", "economy", "%",
               "Children under 16 living in relative low income families after housing costs (household income below 60% "
               "of the UK median once rent or mortgage is paid). DWP modelled estimate, latest financial year.",
               "DWP Children in low income families", "higher_worse", 1, ("child_poverty",)),
    MetricMeta("child_poverty_bhc", "Children in low income families (before housing costs)", "economy", "%",
               "Children under 16 in relative low income families before housing costs, from benefit and tax credit "
               "records (DWP), latest financial year.",
               "DWP Children in low income families", "higher_worse", 1, ("child_poverty",)),
]


def find_file(s: requests.Session) -> str:
    docs = sorted(get_json(s, COLLECTION).get("links", {}).get("documents", []),
                  key=lambda d: d.get("public_updated_at", ""), reverse=True)
    for d in docs[:3]:
        for a in get_json(s, CONTENT + d["base_path"]).get("details", {}).get("attachments", []):
            if str(a.get("url", "")).endswith((".ods", ".xlsx")):
                return a["url"]
    raise LookupError("No children in low income families local area tables found")


def seat_years(sheet: pd.DataFrame) -> list[tuple[str, pd.DataFrame, float | None]]:
    """[(FYE label, num/den frame by seat, UK share)] for every year in the table, oldest first."""
    t = find_table(sheet, "Westminster Parliamentary Constituency")
    year = lambda c: re.search(r"FYE (\d{4})", c)  # noqa: E731
    code = t["Area Code"].astype(str).str.strip()
    out = []
    for pct in sorted((c for c in t.columns if c.lower().startswith("percentage") and year(c)), key=lambda c: year(c).group(1)):
        fye = year(pct).group(1)
        num = next(c for c in t.columns if c.lower().startswith("number") and f"FYE {fye}" in c)
        n, p = pd.to_numeric(t[num], errors="coerce"), pd.to_numeric(t[pct], errors="coerce")
        uk = float(p[code.eq("K02000001")].iloc[0]) * 100 if code.eq("K02000001").any() else None
        keep = code.str.match(r"^(E14|S14|W07|N05)\d{6}$") & n.notna() & p.gt(0)
        out.append((f"FYE {fye}", pd.DataFrame({"num": (n * 100)[keep].values, "den": (n / p)[keep].values},
                                              index=code[keep].values), uk))
    return out


def seat_table(sheet: pd.DataFrame) -> tuple[pd.DataFrame, float, str]:
    """(num/den frame of children in low income families by seat, UK share, year label) for the latest year,
    carrying the earlier years as history."""
    years = seat_years(sheet)
    label, frame, uk = years[-1]
    frame = frame.copy()
    frame.attrs["national"] = uk
    return with_history(frame, years), uk, label


def load_child_poverty(s: requests.Session) -> tuple[dict[str, pd.DataFrame], str]:
    r = s.get(find_file(s), timeout=180)
    r.raise_for_status()
    sheets = read_ods(r.content)
    frames, year = {}, ""
    for mid, pat in [("child_poverty_ahc", r"AHC_Relative_ParlC"), ("child_poverty_bhc", r"BHC_Relative_ParlC")]:
        name = next(k for k in sheets if re.search(pat, k, re.I))
        frames[mid], uk, year = seat_table(sheets[name])
        log.info("%s: %d seats, UK %.1f%%", mid, len(frames[mid]), uk or float("nan"))
    return frames, f"Financial year ending {year[4:]}"
