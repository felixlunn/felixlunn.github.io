"""Gardens and parks (ONS / Ordnance Survey access to green space, April 2020). Great Britain.

* Addresses without a private garden, patio or balcony: published by MSOA
  (2011); each MSOA's counts are shared equally among its neighbourhoods and
  summed to seats.
* Postcodes within 300 metres of a public park or garden (built-up areas
  only): published by neighbourhood (LSOA, 2011 codes), summed to seats.
"""

from __future__ import annotations

import io
import logging
import re

import pandas as pd
import requests

from ..metrics import MetricMeta

log = logging.getLogger(__name__)

SOURCE_URL = "https://www.ons.gov.uk/economy/environmentalaccounts/datasets/accesstogardensandpublicgreenspaceingreatbritain"

GREEN_METRICS = [
    MetricMeta("no_garden", "Homes without a garden", "housing", "%",
               "Addresses with no private outdoor space (garden, patio or balcony), ONS and Ordnance Survey, 2020.",
               "ONS access to gardens and green space", "higher_worse", 0, ("green_space",)),
    MetricMeta("park_within_300m", "Homes within 300m of a park", "environment", "%",
               "Postcodes in built-up areas within 300 metres of a public park or garden (ONS and Ordnance Survey, 2020).",
               "ONS access to gardens and green space", "higher_better", 0, ("green_space",)),
]


def find_files(s: requests.Session) -> dict[str, str]:
    html = s.get(SOURCE_URL, timeout=60).text
    links = ["https://www.ons.gov.uk" + u for u in re.findall(r'href="(/file\?uri=[^"]+\.xlsx)"', html)]
    out = {}
    for u in links:
        if "privateoutdoorspace" in u.lower() and "gardens" not in out:
            out["gardens"] = u
        elif "publicgreenspace" in u.lower() and "parks" not in out:
            out["parks"] = u
    if len(out) < 2:
        raise LookupError("Green space workbooks not found on the ONS page")
    return out


def parks(book: pd.ExcelFile) -> pd.DataFrame:
    """LSOA -> MSOA, built-up postcodes and those within 300m of a park."""
    d = pd.read_excel(book, sheet_name="LSOA Parks only")
    col = lambda *w: next(c for c in d.columns if all(x in str(c).lower() for x in w))  # noqa: E731
    return pd.DataFrame({"msoa": d[col("msoa code")].astype(str).values,
                         "postcodes": pd.to_numeric(d[col("number of postcodes within built up area")], errors="coerce").values,
                         "near": pd.to_numeric(d[col("within 300m")], errors="coerce").values},
                        index=d[col("lsoa code")].astype(str).values)


def gardens(book: pd.ExcelFile) -> pd.DataFrame:
    """MSOA -> addresses and addresses with private outdoor space (all property types)."""
    raw = pd.read_excel(book, sheet_name="MSOA gardens", header=None)
    groups, labels = raw.iloc[0].ffill(), raw.iloc[1].astype(str)
    total = groups.astype(str).str.contains("Total")
    addr = next(j for j in raw.columns if total[j] and labels[j].lower() == "address count")
    with_space = next(j for j in raw.columns if total[j] and labels[j].lower().startswith("adress with private outdoor space count"))
    msoa = next(j for j in raw.columns if str(raw.iloc[0, j]).lower() == "msoa code")
    t = raw.iloc[2:]
    return pd.DataFrame({"addresses": pd.to_numeric(t[addr], errors="coerce").values,
                         "with_space": pd.to_numeric(t[with_space], errors="coerce").values},
                        index=t[msoa].astype(str).values).dropna()


def seat_frames(p: pd.DataFrame, g: pd.DataFrame, lsoa_to_pcon: dict[str, str]) -> dict[str, pd.DataFrame]:
    p = p.assign(pcon=p.index.map(lsoa_to_pcon))
    near = p.dropna(subset=["pcon", "postcodes"]).groupby("pcon")[["near", "postcodes"]].sum()
    # Share each MSOA's addresses equally among its LSOAs.
    share = 1 / p.groupby("msoa")["msoa"].transform("size")
    gl = p[["msoa", "pcon"]].assign(share=share).join(g, on="msoa").dropna(subset=["pcon", "addresses"])
    gs = gl.assign(a=gl["addresses"] * gl["share"], w=gl["with_space"] * gl["share"]).groupby("pcon")[["a", "w"]].sum()
    return {
        "no_garden": pd.DataFrame({"num": (gs["a"] - gs["w"]) * 100, "den": gs["a"].where(gs["a"] > 0)}),
        "park_within_300m": pd.DataFrame({"num": near["near"] * 100, "den": near["postcodes"].where(near["postcodes"] > 0)}),
    }


def load_green_space(s: requests.Session, lsoa_to_pcon: dict[str, str]) -> tuple[dict[str, pd.DataFrame], str]:
    urls = find_files(s)
    books = {}
    for k, u in urls.items():
        r = s.get(u, timeout=180)
        r.raise_for_status()
        books[k] = pd.ExcelFile(io.BytesIO(r.content))
    return seat_frames(parks(books["parks"]), gardens(books["gardens"]), lsoa_to_pcon), "April 2020"
