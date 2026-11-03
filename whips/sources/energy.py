"""Household gas and electricity use by neighbourhood (DESNZ sub-national consumption statistics). England & Wales.

DESNZ publishes domestic gas and electricity meters and consumption for every
neighbourhood (LSOA, 2021 codes) each year. From these:

* homes off the gas grid: one minus gas meters as a share of electricity meters
  (almost every home has an electricity meter);
* average gas and electricity use per meter (kWh a year).
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

CONTENT = "https://www.gov.uk/api/content/government/statistics"
PAGES = {"gas": "lower-and-middle-super-output-areas-gas-consumption",
         "elec": "lower-and-middle-super-output-areas-electricity-consumption"}
SOURCE_URL = "https://www.gov.uk/government/collections/sub-national-gas-consumption-data"

ENERGY_METRICS = [
    MetricMeta("off_gas_grid", "Homes off the gas grid", "housing", "%",
               "Estimated share of homes with no mains gas meter: domestic gas meters compared with electricity meters "
               "(DESNZ, latest year). Off-grid homes heat with oil, LPG, electricity or solid fuel.",
               "DESNZ sub-national energy consumption", "neutral", 0, ("energy",)),
    MetricMeta("gas_kwh_per_home", "Gas use per home", "housing", "kWh",
               "Average domestic gas use per meter a year (DESNZ, weather-corrected).",
               "DESNZ sub-national energy consumption", "neutral", 0, ("energy",)),
    MetricMeta("elec_kwh_per_home", "Electricity use per home", "housing", "kWh",
               "Average domestic electricity use per meter a year (DESNZ).",
               "DESNZ sub-national energy consumption", "neutral", 0, ("energy",)),
]


def find_file(s: requests.Session, kind: str) -> str:
    for a in get_json(s, f"{CONTENT}/{PAGES[kind]}").get("details", {}).get("attachments", []):
        if str(a.get("title", "")).lower().startswith("lsoa domestic") and str(a.get("url", "")).endswith(".xlsx"):
            return a["url"]
    raise LookupError(f"No LSOA domestic {kind} file found")


def latest_sheet(book: pd.ExcelFile) -> tuple[pd.DataFrame, str]:
    year = max(n for n in book.sheet_names if re.fullmatch(r"\d{4}", n))
    raw = pd.read_excel(book, sheet_name=year, header=None)
    header = next(i for i in range(15) if str(raw.iloc[i, 0]).strip().lower().startswith("local authority code"))
    t = raw.iloc[header + 1:].copy()
    t.columns = [re.sub(r"\s+", " ", str(c)).strip().lower() for c in raw.iloc[header]]
    lsoa = next(c for c in t.columns if c.startswith("lsoa code"))
    meters = next(c for c in t.columns if c.startswith("number of meters"))
    total = next(c for c in t.columns if c.startswith("total consumption"))
    out = pd.DataFrame({"meters": pd.to_numeric(t[meters], errors="coerce").values,
                        "kwh": pd.to_numeric(t[total], errors="coerce").values}, index=t[lsoa].astype(str).str.strip())
    return out[out.index.str.match(r"^[EW]01\d{6}$")], year


def seat_frames(gas: pd.DataFrame, elec: pd.DataFrame, lsoa_to_pcon: dict[str, str]) -> dict[str, pd.DataFrame]:
    seat = lambda d: d.groupby(d.index.map(lsoa_to_pcon)).sum(min_count=1)  # noqa: E731
    g, e = seat(gas), seat(elec)
    g = g.reindex(e.index)
    gas_meters = g["meters"].fillna(0)  # no gas meters recorded: fully off grid
    off = (e["meters"] - gas_meters).clip(lower=0)
    return {
        "off_gas_grid": pd.DataFrame({"num": off * 100, "den": e["meters"]}),
        "gas_kwh_per_home": pd.DataFrame({"num": g["kwh"], "den": g["meters"].where(g["meters"] > 0)}),
        "elec_kwh_per_home": pd.DataFrame({"num": e["kwh"], "den": e["meters"].where(e["meters"] > 0)}),
    }


def load_energy(s: requests.Session, lsoa_to_pcon: dict[str, str]) -> tuple[dict[str, pd.DataFrame], str]:
    got = {}
    for kind in ("gas", "elec"):
        r = s.get(find_file(s, kind), timeout=600)
        r.raise_for_status()
        got[kind] = latest_sheet(pd.ExcelFile(io.BytesIO(r.content)))
    (gas, year), (elec, _) = got["gas"], got["elec"]
    return seat_frames(gas, elec, lsoa_to_pcon), year
