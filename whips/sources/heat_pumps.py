"""Heat pump grants by constituency (Boiler Upgrade Scheme statistics, DESNZ/Ofgem). England & Wales.

The monthly Boiler Upgrade Scheme release counts paid grants (redemptions) by
constituency since the scheme began in May 2022, by technology. Heat pump
grants are expressed per 10,000 households (Census 2021).
"""

from __future__ import annotations

import io
import logging
import re

import pandas as pd
import requests

from ..http import get_json
from ..metrics import MetricMeta

log = logging.getLogger(__name__)

COLLECTION = "https://www.gov.uk/api/content/government/collections/boiler-upgrade-scheme-statistics"
CONTENT = "https://www.gov.uk/api/content"
SOURCE_URL = "https://www.gov.uk/government/collections/boiler-upgrade-scheme-statistics"

HEAT_PUMP_METRICS = [
    MetricMeta("heat_pump_grants_per_10k", "Heat pump grants per 10,000 households", "environment", "per 10,000",
               "Boiler Upgrade Scheme grants paid for air and ground source heat pumps in the constituency since May 2022, per "
               "10,000 households (Census 2021).", "Boiler Upgrade Scheme statistics", "higher_better", 1, ("heat_pumps",)),
]


def find_file(s: requests.Session) -> tuple[str, str]:
    docs = [d for d in get_json(s, COLLECTION).get("links", {}).get("documents", [])
            if re.search(r"boiler-upgrade-scheme-statistics-\w+-\d{4}$", d.get("base_path", ""))]
    for d in sorted(docs, key=lambda d: d.get("public_updated_at", ""), reverse=True)[:3]:
        for a in get_json(s, CONTENT + d["base_path"]).get("details", {}).get("attachments", []):
            if str(a.get("url", "")).endswith(".xlsx"):
                return a["url"], d.get("title", "").split(": ")[-1]
    raise LookupError("No Boiler Upgrade Scheme statistics workbook found")


def by_constituency(book: pd.ExcelFile) -> pd.Series:
    """Heat pump grants paid by constituency (table Q1.3)."""
    raw = pd.read_excel(book, sheet_name="Q1.3", header=None)
    header = next(i for i in range(25) if str(raw.iloc[i, 0]).strip().lower().startswith("area code"))
    t = raw.iloc[header + 1:]
    hp = next(j for j in raw.columns if "heat pump" in str(raw.iloc[header, j]).lower())
    code = t[0].astype(str).str.strip()
    keep = code.str.match(r"^(E14|W07)\d{6}$")
    return pd.Series(pd.to_numeric(t[hp], errors="coerce")[keep].values, index=code[keep].values)


def load_heat_pumps(s: requests.Session, households: pd.Series | None) -> tuple[dict[str, pd.DataFrame], str]:
    if households is None:
        raise RuntimeError("Household counts (Census) unavailable")
    url, month = find_file(s)
    r = s.get(url, timeout=120)
    r.raise_for_status()
    n = by_constituency(pd.ExcelFile(io.BytesIO(r.content)))  # "[c]" suppressed small counts -> missing
    return {"heat_pump_grants_per_10k": pd.DataFrame({"num": n * 10_000, "den": households.reindex(n.index)})}, \
        f"Grants paid May 2022 to {month}"
