"""Storm overflow sewage spills by constituency (Environment Agency EDM annual returns), England & Wales.

The annual return lists every storm overflow with its outlet grid reference,
its spill count (12-24h counting method) and total spill duration. Outlets are
placed in seats by location (sea outfalls can lie offshore, so the nearest seat
within ~5 km is used for points outside the coast-clipped boundaries).
"""

from __future__ import annotations

import io
import logging
import re
import zipfile

import pandas as pd
import requests

from ..geo import SeatLocator, en_to_lonlat, ngr_to_en
from ..http import get_json
from ..metrics import MetricMeta

log = logging.getLogger(__name__)

PACKAGE = "https://ckan.publishing.service.gov.uk/api/action/package_show"
PACKAGE_ID = "event-duration-monitoring-storm-overflows-annual-returns"
SOURCE_URL = "https://www.data.gov.uk/dataset/19f6064d-7356-466f-844e-d20ea10ae9fd/event-duration-monitoring-storm-overflows-annual-returns"

SEWAGE_METRICS = [
    MetricMeta("sewage_spills", "Sewage spills from storm overflows", "environment", "spills",
               "Spills from storm overflows discharging in the constituency in the year (water companies' Event Duration "
               "Monitoring returns; 12-24 hour counting). National figure: average per seat.",
               "Environment Agency EDM annual returns", "higher_worse", 0, ("sewage",)),
    MetricMeta("sewage_hours", "Hours of sewage spills", "environment", "hours",
               "Total hours that storm overflows discharging in the constituency spilled in the year. National figure: "
               "average per seat.", "Environment Agency EDM annual returns", "higher_worse", 0, ("sewage",)),
]


def find_return(s: requests.Session) -> tuple[str, str]:
    """(zip URL, year) of the latest annual return."""
    res = get_json(s, PACKAGE, params={"id": PACKAGE_ID})["result"]["resources"]
    years = []
    for r in res:
        m = re.search(r"EDM_(\d{4})_Storm_Overflow_Annual_Return\.zip", r.get("url", "") + " " + (r.get("name") or ""))
        if m:
            years.append((int(m.group(1)), r["url"]))
    if not years:
        raise LookupError("No EDM annual return found")
    year, url = max(years)
    return url.replace(" ", "%20"), str(year)


def hours(v) -> float | None:
    """Spill duration as hours, whether given as "hhh:mm:ss", a timedelta or a number of hours."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, pd.Timedelta) or hasattr(v, "total_seconds"):
        return v.total_seconds() / 3600
    if hasattr(v, "hour") and hasattr(v, "minute"):  # a time of day (under 24h)
        return v.hour + v.minute / 60 + getattr(v, "second", 0) / 3600
    m = re.fullmatch(r"\s*(\d+):(\d{1,2})(?::(\d{1,2}))?\s*", str(v))
    if m:
        return int(m.group(1)) + int(m.group(2)) / 60 + int(m.group(3) or 0) / 3600
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_return(xlsx: bytes) -> pd.DataFrame:
    """The all-companies sheet -> one row per overflow: ngr, spills, hours."""
    book = pd.ExcelFile(io.BytesIO(xlsx))
    sheet = next((n for n in book.sheet_names if "all" in n.lower()), book.sheet_names[0])
    raw = pd.read_excel(book, sheet_name=sheet, header=None, nrows=30)
    header = next(i for i in range(30) if raw.iloc[i].astype(str).str.strip().str.lower().eq("unique id").any())
    df = pd.read_excel(book, sheet_name=sheet, header=header)
    col = lambda *words: next(c for c in df.columns if all(w in str(c).lower() for w in words))  # noqa: E731
    ngr = df[col("ngr")]
    out = pd.DataFrame({
        "ngr": ngr.where(ngr.notna(), "").astype(str).str.strip(),
        "spills": pd.to_numeric(df[col("counted spills")], errors="coerce"),
        "hours": df[col("total duration")].map(hours),
    })
    return out[out["ngr"].ne("")].reset_index(drop=True)


def seat_frames(overflows: pd.DataFrame, locator: SeatLocator, all_codes: list[str]) -> dict[str, pd.DataFrame]:
    en = overflows["ngr"].map(ngr_to_en)
    ok = en.notna()
    d = overflows[ok].copy()
    lon, lat = en_to_lonlat([e for e, _ in en[ok]], [n for _, n in en[ok]])
    d["pcon"] = locator.seats(lon, lat, tolerance=0.05)
    d = d.dropna(subset=["pcon"])
    ew = [c for c in all_codes if c[:1] in "EW"]  # returns cover England and Wales
    spills = d.groupby("pcon")["spills"].sum().reindex(ew).fillna(0)
    hrs = d.groupby("pcon")["hours"].sum().reindex(ew).fillna(0)
    return {
        "sewage_spills": pd.DataFrame({"num": spills, "den": 1.0}),
        "sewage_hours": pd.DataFrame({"num": hrs, "den": 1.0}),
    }


def load_sewage(s: requests.Session, geo: dict) -> tuple[dict[str, pd.DataFrame], str]:
    url, year = find_return(s)
    r = s.get(url, timeout=300)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    name = next(n for n in z.namelist() if n.lower().endswith(".xlsx") and "all water and sewerage" in n.lower())
    overflows = parse_return(z.read(name))
    locator = SeatLocator(geo)
    frames = seat_frames(overflows, locator, locator.codes)
    log.info("Sewage: %d overflows, %d spills", len(overflows), int(overflows["spills"].sum()))
    return frames, f"Calendar year {year}"
