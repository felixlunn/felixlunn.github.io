"""Local bus use and bus service mileage by local transport authority (DfT bus statistics). England.

DfT publishes, by local transport authority (counties and unitary councils):
passenger journeys per head (BUS01f) and vehicle miles run on local bus
services (BUS02d). Seats take the average of the authorities they overlap,
weighted by their neighbourhoods in each (``councils.averaged``).
"""

from __future__ import annotations

import logging
import re

import pandas as pd
import requests

from .. import govuk
from ..history import council_periods, year_columns as history_years
from ..metrics import MetricMeta
from ..ods import find_table, read_ods
from .councils import averaged, lad_to_cauth, lad_to_county, regrouped_weights

log = logging.getLogger(__name__)

DATASET = "https://www.gov.uk/api/content/government/statistical-data-sets/bus-statistics-data-tables"
SOURCE_URL = "https://www.gov.uk/government/statistical-data-sets/bus-statistics-data-tables"
BASE_YEAR = "2010"
LONDON = "E12000007"  # TfL: London is one transport authority
# Unitary councils created since the tables' authorities were set: use their former county's figure.
FORMER_COUNTY = {"E06000063": "E10000006", "E06000064": "E10000006",  # Cumberland, Westmorland and Furness: Cumbria
                 "E06000065": "E10000023", "E06000066": "E10000027"}   # North Yorkshire, Somerset

NOTE = " Figures are for the local transport authority (county or unitary council), averaged over those the constituency covers."
BUS_METRICS = [
    MetricMeta("bus_journeys_per_head", "Bus journeys per person a year", "transport", "journeys",
               "Passenger journeys on local bus services a year per resident (DfT, latest year ending March)." + NOTE,
               "DfT bus statistics", "higher_better", 0, ("buses",)),
    MetricMeta("bus_miles_change", "Change in bus service miles since 2010", "transport", "%",
               "Change in vehicle miles run on local bus services between the year ending March 2010 and the latest year: "
               "a measure of how much bus service has been cut or added." + NOTE,
               "DfT bus statistics", "higher_better", 0, ("buses",)),
]


def find_files(s: requests.Session) -> dict[str, str]:
    """{"bus01": url, "bus02": url} for the journeys and vehicle miles workbooks."""
    found = {}
    for a in govuk.attachments(s, DATASET):
        url = str(a.get("url", ""))
        for key, name in [("bus01", "/bus01.ods"), ("bus02", "/bus02_mi.ods")]:
            if url.endswith(name):
                found[key] = url
    if len(found) < 2:
        raise LookupError(f"Bus statistics tables missing: {sorted({'bus01', 'bus02'} - set(found))}")
    return found


# DfT renamed the header columns in November 2026 ("LA Code" -> "Area code", "Service type [note 3]", ...):
# tables are found by any of their first headers, and columns by how their name starts.
FIRST_HEADERS = ("Area code", "LA Code", "Local Authority")


def table(sheet: pd.DataFrame) -> pd.DataFrame:
    for h in FIRST_HEADERS:
        try:
            return find_table(sheet, h)
        except IndexError:
            continue
    raise LookupError(f"No table starting {' / '.join(FIRST_HEADERS)} in the bus statistics sheet")


def column(t: pd.DataFrame, *starts: str) -> str:
    """The first column whose name starts with one of ``starts`` (ignoring case and [note] markers)."""
    found = next((c for c in t.columns if str(c).lower().startswith(tuple(s.lower() for s in starts))), None)
    if found is None:
        raise LookupError(f"No column starting {' / '.join(starts)} in the bus statistics table")
    return found


def year_columns(t: pd.DataFrame) -> list[str]:
    return [c for c in t.columns if re.fullmatch(r"\d{4}", c)]


def journeys_per_head(sheet: pd.DataFrame) -> tuple[pd.Series, float | None, str]:
    t = table(sheet)
    year = year_columns(t)[-1]
    v = pd.to_numeric(t[year], errors="coerce")
    code, name = t.iloc[:, 0].astype(str).str.strip(), t.iloc[:, 1].astype(str).str.strip()
    england = v[name.eq("England")]
    keep = code.str.match(r"^E(06|10|11|12|47)\d{6}$") & v.notna()
    return pd.Series(v[keep].values, index=code[keep].values), (float(england.iloc[0]) if len(england) else None), year


def journeys_by_year(sheet: pd.DataFrame) -> list[tuple[str, pd.Series, float | None]]:
    t = table(sheet)
    code, name = t.iloc[:, 0].astype(str).str.strip(), t.iloc[:, 1].astype(str).str.strip()
    return history_years(t, code, year_columns(t), code.str.match(r"^E(06|10|11|12|47)\d{6}$"), name.eq("England"))


def miles_change(sheet: pd.DataFrame) -> tuple[pd.Series, float | None, str]:
    t = table(sheet)
    t = t[t[column(t, "service type")].astype(str).str.strip().eq("Total")]
    latest = year_columns(t)[-1]
    then, now = (pd.to_numeric(t[c], errors="coerce") for c in (BASE_YEAR, latest))
    code = t[column(t, "area code", "la code")].astype(str).str.strip()
    change = (now - then) * 100 / then
    england = code.eq("E92000001") | t[column(t, "area name", "local authority")].astype(str).str.strip().eq("England")
    nat = float(change[england].iloc[0]) if england.any() else None
    keep = code.str.match(r"^E(06|10|11|12|47)\d{6}$") & change.notna()
    return pd.Series(change[keep].values, index=code[keep].values), nat, latest


def authority_weights(weights: pd.DataFrame, county: dict[str, str], cauth: dict[str, str], listed: set[str]) -> pd.DataFrame:
    """Seat x council weights regrouped to the transport authorities the table lists.

    DfT reports some areas by council, others by county, and (since November 2026) the mayoral areas by combined
    authority (E47): each council takes the first of itself, its county, its combined authority or its former county
    that the table has. London is one authority (TfL)."""
    mapping = {}
    for lad in weights["lad"].unique():
        if lad.startswith("E09"):
            mapping[lad] = LONDON
            continue
        options = [lad, county.get(lad), cauth.get(lad), FORMER_COUNTY.get(lad)]
        mapping[lad] = next((o for o in options if o and o in listed), lad)
    return regrouped_weights(weights, mapping)


def load_buses(s: requests.Session, weights: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], str]:
    urls = find_files(s)
    county, cauth = lad_to_county(s), lad_to_cauth(s)
    out, years = {}, []
    for key, mid, sheet, fn in [("bus01", "bus_journeys_per_head", "BUS01f", journeys_per_head),
                                ("bus02", "bus_miles_change", "BUS02d", miles_change)]:
        r = s.get(urls[key], timeout=120)
        r.raise_for_status()
        sheets = read_ods(r.content)
        table = next(v for k, v in sheets.items() if k.startswith(sheet))
        values, nat, year = fn(table)
        upper_weights = authority_weights(weights, county, cauth, set(values.index))
        if mid == "bus_journeys_per_head":  # every year since 2010 is published
            out[mid] = council_periods(journeys_by_year(table), averaged, upper_weights)
        else:  # already a change since 2010
            f = averaged(values, upper_weights)
            f.attrs["national"] = nat
            out[mid] = f
        years.append(year)
    return out, f"Year ending March {max(years)}"
