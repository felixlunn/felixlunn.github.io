"""Council (local authority) lookups, and turning council-level figures into seat figures.

Seats and councils don't nest, so a seat is linked to every council its LSOAs
fall in, weighted by LSOA count (LSOAs hold ~1,500 people each, so this is
close to a population weighting):

* counts (e.g. households in temporary accommodation) are *apportioned*: a seat
  gets each council's count times the share of that council's LSOAs it holds;
* rates and prices (e.g. an affordability ratio) are *averaged*, weighting each
  council by the number of the seat's LSOAs in it.
"""

from __future__ import annotations

import re

import pandas as pd
import requests

from .. import arcgis
from .lsoa import WARD_PATTERN, find_ward_service


def lsoa_to_lad(s: requests.Session) -> dict[str, str]:
    """LSOA (2021) -> council code, from the latest ONS LSOA-to-ward-to-council lookup."""
    layer = find_ward_service(arcgis.services(s, WARD_PATTERN))
    return {r["LSOA21CD"]: arcgis.field(r, r"LAD\d{2}CD") for r in arcgis.rows(s, layer) if r.get("LSOA21CD")}


def seat_council_weights(lsoa_pcon: dict[str, str], lsoa_lad: dict[str, str]) -> pd.DataFrame:
    """One row per (seat, council) overlap: LSOA count, and that count's share of the seat and of the council."""
    df = pd.DataFrame({"pcon": pd.Series(lsoa_pcon)})
    df["lad"] = df.index.map(lsoa_lad)
    df = df.dropna()
    w = df.groupby(["pcon", "lad"]).size().rename("n").reset_index()
    w["of_seat"] = w["n"] / w.groupby("pcon")["n"].transform("sum")
    w["of_council"] = w["n"] / w.groupby("lad")["n"].transform("sum")
    return w


def apportion(counts: pd.Series, weights: pd.DataFrame) -> pd.Series:
    """Council counts -> seat counts, each council's count shared by its LSOAs."""
    w = weights.assign(v=weights["lad"].map(counts) * weights["of_council"]).dropna(subset=["v"])
    return w.groupby("pcon")["v"].sum()


def averaged(values: pd.Series, weights: pd.DataFrame) -> pd.DataFrame:
    """Council values -> seat num/den: the average of the seat's councils, weighted by its LSOAs in each."""
    w = weights.assign(v=weights["lad"].map(values)).dropna(subset=["v"])
    return pd.DataFrame({"num": (w["v"] * w["n"]).groupby(w["pcon"]).sum(), "den": w.groupby("pcon")["n"].sum()})



COUNTY_PATTERN = re.compile(r"^LAD(\d{2})_CTY\d{2}_EN_LU", re.I)


def lad_to_county(s: requests.Session) -> dict[str, str]:
    """District code -> county code (non-metropolitan E10 and metropolitan E11), from the latest ONS lookup.

    Unitary councils and London boroughs are not in it."""
    names = arcgis.matching(s, COUNTY_PATTERN)
    if not names:
        raise LookupError("No district to county lookup found on the ONS portal")
    latest = max(names, key=lambda n: (int(COUNTY_PATTERN.match(n).group(1)), n))
    rows = arcgis.rows(s, arcgis.layer(latest))
    return {arcgis.field(r, r"LAD\d{2}CD"): arcgis.field(r, r"CTY\d{2}CD") for r in rows}


CAUTH_PATTERN = re.compile(r"^LAD(\d{2})_CAUTH\d{2}_EN_LU", re.I)


def lad_to_cauth(s: requests.Session) -> dict[str, str]:
    """Council code -> combined authority code (E47: mayoral and other combined authorities), latest ONS lookup."""
    names = arcgis.matching(s, CAUTH_PATTERN)
    if not names:
        raise LookupError("No council to combined authority lookup found on the ONS portal")
    latest = max(names, key=lambda n: (int(CAUTH_PATTERN.match(n).group(1)), n))
    return {arcgis.field(r, r"LAD\d{2}CD"): arcgis.field(r, r"CAUTH\d{2}CD") for r in arcgis.rows(s, arcgis.layer(latest))}


def regrouped_weights(weights: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    """Seat x council weights regrouped to larger areas (e.g. counties); councils not in ``mapping`` stay as they are."""
    w = weights.assign(lad=weights["lad"].map(lambda c: mapping.get(c, c)))
    w = w.groupby(["pcon", "lad"], as_index=False)["n"].sum()
    w["of_seat"] = w["n"] / w.groupby("pcon")["n"].transform("sum")
    w["of_council"] = w["n"] / w.groupby("lad")["n"].transform("sum")
    return w


def upper_tier_weights(weights: pd.DataFrame, county: dict[str, str]) -> pd.DataFrame:
    """Seat x council weights for upper-tier councils (education, highways, social care): districts join their
    county (E10); unitary councils, metropolitan districts and London boroughs stand alone."""
    return regrouped_weights(weights, {lad: c for lad, c in county.items() if str(c).startswith("E10")})
