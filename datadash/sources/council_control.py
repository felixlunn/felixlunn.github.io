"""Who runs the councils covering each seat (Open Council Data UK), for the seat briefing.

Open Council Data publishes every councillor in Great Britain and Northern Ireland with their party and the
date of the next election, after each May's elections. For each council this works out the controlling party
(more than half the seats) or "No overall control", the largest party, and the next election. Councils are
linked to seats through the neighbourhoods each seat contains (England & Wales: LSOAs and the ONS lookups;
Scotland: output areas, from NRS) - county councils as well as districts in two-tier areas. Northern Ireland
is not covered (no neighbourhood-to-seat lookup).
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from datetime import date

import pandas as pd
import requests

from .. import arcgis
from .councils import COUNTY_PATTERN, lad_to_county

log = logging.getLogger(__name__)

SOURCE_URL = "https://opencouncildata.co.uk/"
CSV_URL = "https://opencouncildata.co.uk/csv2.php?y={year}"
UK_NAMES = re.compile(r"^LAD_[A-Z]{3}_(20\d\d)_UK_NC", re.I)
MIN_SHARE = 0.10  # councils covering less of the seat than this are left out

# Open Council Data party names -> the names the dashboard uses for party colours.
PARTIES = {
    "Liberal Democrats": "Liberal Democrat", "Labour Party": "Labour", "Conservative and Unionist": "Conservative",
    "Green Party (E&W)": "Green Party", "Scottish Green Party": "Green Party", "Reform UK": "Reform UK",
    "Scottish National Party (SNP)": "Scottish National Party", "Plaid Cymru - The Party of Wales": "Plaid Cymru",
    "Independent / Other": "Independent",
}
ALIASES = {"herefordshire county of": "herefordshire", "county durham": "durham"}


def norm(name: str) -> str:
    n = name.lower().replace("&", "and")
    n = re.sub(r"[^a-z ]", " ", n)
    n = re.sub(r"\b(city of|council|borough|district|the|metropolitan|royal)\b", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    n = ALIASES.get(n, n)
    return re.sub(r"\bcounty\b", "", n).strip() if n.endswith(" county") else n


def party(name: str) -> str:
    return PARTIES.get(name, name)


def control(members: pd.DataFrame) -> dict:
    """Seats by party, the controlling party (over half the filled seats) and the next election."""
    filled = members[members["Party Name"].ne("Vacant")]
    counts = filled["Party Name"].map(party).value_counts()
    seats = int(len(members))
    top, top_n = (counts.index[0], int(counts.iloc[0])) if len(counts) else (None, 0)
    if top and top_n * 2 > len(filled):
        ctrl = "Independents" if top == "Independent" else top
    else:
        ctrl = "No overall control"
    nxt = pd.to_datetime(members["Next Election"], errors="coerce").dropna()
    return {"control": ctrl, "largest": top, "largest_seats": top_n, "seats": seats,
            "parties": {k: int(v) for k, v in counts.head(6).items()},
            "next_election": nxt.min().date().isoformat() if len(nxt) else None}


def load_councillors(s: requests.Session) -> tuple[pd.DataFrame, int]:
    """The latest year's councillor list (this year's, falling back to last year's before it is published)."""
    for year in (date.today().year, date.today().year - 1):
        r = s.get(CSV_URL.format(year=year), timeout=120)
        if r.ok and r.text.lstrip().startswith("Council,"):
            d = pd.read_csv(io.StringIO(r.text))
            if len(d) > 1000:
                return d, year
    raise LookupError("No Open Council Data councillor list")


def council_names(s: requests.Session) -> dict[str, str]:
    """Council code -> name, for UK local authorities and English counties."""
    names = arcgis.services(s, UK_NAMES, COUNTY_PATTERN)
    uk = max((n for n in names if UK_NAMES.match(n)), key=lambda n: (int(UK_NAMES.match(n).group(1)), n))
    out = {arcgis.field(r, r"LAD\d{2}CD"): arcgis.field(r, r"LAD\d{2}NM") for r in arcgis.rows(s, arcgis.layer(uk))}
    cty = max(n for n in names if COUNTY_PATTERN.match(n))
    out.update({arcgis.field(r, r"CTY\d{2}CD"): arcgis.field(r, r"CTY\d{2}NM") for r in arcgis.rows(s, arcgis.layer(cty))})
    return out


def seat_councils(weights: pd.DataFrame, county: dict[str, str]) -> pd.DataFrame:
    """(seat, council code, share of the seat) for districts/unitaries and, in two-tier areas, their county."""
    w = weights[["pcon", "lad", "of_seat"]].copy()
    upper = w.assign(lad=w["lad"].map(lambda c: county.get(c)))
    upper = upper[upper["lad"].astype(str).str.startswith("E10")].groupby(["pcon", "lad"], as_index=False)["of_seat"].sum()
    return pd.concat([w, upper], ignore_index=True)


def by_seat(links: pd.DataFrame, names: dict[str, str], councils: dict[str, dict]) -> dict[str, list[dict]]:
    """Seat code -> councils covering at least MIN_SHARE of it, largest share first (counties after their districts)."""
    out: dict[str, list[dict]] = {}
    for _, r in links[links["of_seat"] >= MIN_SHARE].iterrows():
        name = names.get(r["lad"])
        info = councils.get(norm(name)) if name else None
        if not info:
            continue
        tier = "county" if str(r["lad"]).startswith("E10") else "council"
        out.setdefault(r["pcon"], []).append({"name": info["name"], "code": r["lad"], "tier": tier,
                                              "share": round(float(r["of_seat"]), 2), **info["control"]})
    for seat in out.values():
        seat.sort(key=lambda c: (c["tier"] == "county", -c["share"]))
    return out


def scotland_links(s: requests.Session, geo: dict) -> pd.DataFrame:
    """(seat, council code, share of the seat's population) for Scotland, from NRS output-area centroids."""
    from ..geo import SeatLocator, en_to_lonlat
    from .scotland import GEOGRAPHY_PAGE, find_zip
    g = s.get(find_zip(s, GEOGRAPHY_PAGE, r"pwc"), timeout=300)
    g.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(g.content))
    oa = read_dbf(z.read(next(n for n in z.namelist() if n.lower().endswith(".dbf"))))
    lon, lat = en_to_lonlat(oa["easting"].astype(float), oa["northing"].astype(float))
    oa["pcon"] = SeatLocator(geo).seats(lon, lat)
    oa = oa.dropna(subset=["pcon"])
    oa["pop"] = pd.to_numeric(oa["popcount"], errors="coerce").fillna(0)
    t = oa.groupby(["pcon", "council"], as_index=False)["pop"].sum()
    t["of_seat"] = t["pop"] / t.groupby("pcon")["pop"].transform("sum")
    return t.rename(columns={"council": "lad"})[["pcon", "lad", "of_seat"]]


def read_dbf(dbf: bytes) -> pd.DataFrame:
    """All character/number fields of a dBase table (as strings)."""
    import struct
    n, header_len, record_len = struct.unpack("<IHH", dbf[4:12])
    fields, p = [], 32
    while dbf[p] != 0x0D:
        fields.append((dbf[p:p + 11].split(b"\0")[0].decode().lower(), dbf[p + 16]))
        p += 32
    rows = []
    for k in range(n):
        rec = dbf[header_len + k * record_len: header_len + (k + 1) * record_len]
        pos, row = 1, {}
        for name, length in fields:
            row[name] = rec[pos:pos + length].decode("latin-1").strip()
            pos += length
        rows.append(row)
    return pd.DataFrame(rows)


def load_council_control(s: requests.Session, weights: pd.DataFrame, geo: dict) -> tuple[dict, str]:
    d, year = load_councillors(s)
    councils = {norm(name): {"name": name, "control": control(g)} for name, g in d.groupby("Council")}
    names = council_names(s)
    links = seat_councils(weights, lad_to_county(s))
    try:
        links = pd.concat([links, scotland_links(s, geo)], ignore_index=True)
    except Exception as exc:  # noqa: BLE001 - keep England & Wales if the Scottish lookup fails
        log.warning("Scottish council lookup failed: %s", exc)
    seats = by_seat(links, names, councils)
    log.info("Council control: %d councils, %d seats", len(councils), len(seats))
    return {"year": year, "by_seat": seats}, f"After the May {year} elections"
