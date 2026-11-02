"""Public electric vehicle chargers by constituency (DfT EVCI statistics, from Zapmap), UK.

DfT's quarterly table EVCI0103 counts public chargers (and 50 kW+ rapid ones)
by July 2024 parliamentary constituency. The latest edition is found via the
GOV.UK content API.
"""

from __future__ import annotations

import logging
import re

import pandas as pd
import requests

from ..http import get_json
from ..metrics import MetricMeta
from ..ods import find_table, read_ods

log = logging.getLogger(__name__)

DATASET = "https://www.gov.uk/api/content/government/statistical-data-sets/electric-vehicle-charging-infrastructure-statistics-data-tables-evci"
SOURCE_URL = "https://www.gov.uk/government/statistical-data-sets/electric-vehicle-charging-infrastructure-statistics-data-tables-evci"

EV_METRICS = [
    MetricMeta("ev_chargers", "Public EV chargers", "transport", "chargers",
               "Public electric vehicle chargers in the constituency (DfT, from Zapmap). National figure: average per seat.",
               "DfT EV charging infrastructure statistics", "higher_better", 0, ("ev",)),
    MetricMeta("ev_chargers_per_10k", "Public EV chargers per 10,000 voters", "transport", "per 10,000",
               "Public electric vehicle chargers per 10,000 people on the 2024 electoral register.",
               "DfT EV charging infrastructure statistics", "higher_better", 1, ("ev",)),
    MetricMeta("ev_rapid_share", "Rapid EV chargers (50kW+)", "transport", "%",
               "Share of the constituency's public chargers that are rapid or ultra-rapid (50 kW or more).",
               "DfT EV charging infrastructure statistics", "neutral", 1, ("ev",)),
]


def find_file(s: requests.Session) -> str:
    for a in get_json(s, DATASET).get("details", {}).get("attachments", []):
        if "parliamentary constituency" in str(a.get("title", "")).lower() and str(a.get("url", "")).endswith(".ods"):
            return a["url"]
    raise LookupError("No EV chargers by parliamentary constituency table found")


def latest_column(table: pd.DataFrame) -> str:
    """The most recent date column (headers like "1 July 2026\\n[note 3]")."""
    dated = [c for c in table.columns if re.search(r"\b(19|20)\d{2}\b", c)]
    return max(dated, key=lambda c: pd.to_datetime(re.sub(r"\s*\[.*?\]", "", c).strip(), dayfirst=True))


def counts(sheet: pd.DataFrame) -> tuple[pd.Series, str]:
    table = find_table(sheet, "Code")
    col = latest_column(table)
    codes = table["Code"].astype(str).str.strip()
    values = pd.to_numeric(table[col], errors="coerce")
    keep = codes.str.match(r"^(E14|S14|W07|N05)\d{6}$")  # July 2024 constituency codes in each nation
    return pd.Series(values[keep].values, index=codes[keep].values), re.sub(r"\s*\[.*?\]", "", col).strip()


def load_ev(s: requests.Session, electorate: pd.Series) -> tuple[dict[str, pd.DataFrame], str]:
    r = s.get(find_file(s), timeout=120)
    r.raise_for_status()
    sheets = read_ods(r.content)
    allc, when = counts(next(v for k, v in sheets.items() if k.lower().endswith("0103a")))
    rapid, _ = counts(next(v for k, v in sheets.items() if k.lower().endswith("0103b")))
    elec = electorate.reindex(allc.index)
    return {
        "ev_chargers": pd.DataFrame({"num": allc, "den": 1.0}),
        "ev_chargers_per_10k": pd.DataFrame({"num": allc * 10_000, "den": elec}),
        "ev_rapid_share": pd.DataFrame({"num": rapid.reindex(allc.index) * 100, "den": allc.where(allc > 0)}),
    }, f"Chargers at {when}"
