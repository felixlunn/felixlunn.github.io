"""Scotland's Census 2022 (National Records of Scotland), summed from output areas to Westminster seats.

Nomis only holds the 2021 census for England and Wales. NRS publishes every 2022 census table for Scotland's
46,000 output areas, with each area's population-weighted centre. Areas are placed in the July 2024 seats by
that centre, and counts summed, to give Scottish values for the census figures whose definitions match the
England and Wales ones closely (see ``MAPPING``). Figures defined differently in Scotland (qualification
levels, deprivation dimensions, sexual orientation and others) are left as "No data" rather than approximated.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import struct
import zipfile

import pandas as pd
import requests

from ..geo import SeatLocator, en_to_lonlat

log = logging.getLogger(__name__)

TABLES_PAGE = "https://www.scotlandscensus.gov.uk/documents/2022-output-area-data/"
GEOGRAPHY_PAGE = "https://www.nrscotland.gov.uk/publications/2022-census-geography-products/"
SOURCE_URL = "https://www.scotlandscensus.gov.uk/"

# metric id -> (table, regex on the lower-cased column label, complement?). The denominator is the table's total.
MAPPING: dict[str, tuple[str, str, bool]] = {
    "age_0_14": ("UV102b", r"^all people: (0 - 4|5 - 9|10 - 14)$", False),
    "age_20_34": ("UV102b", r"^all people: (20 - 24|25 - 29|30 - 34)$", False),
    "age_35_49": ("UV102b", r"^all people: (35 - 39|40 - 44|45 - 49)$", False),
    "age_50_64": ("UV102b", r"^all people: (50 - 54|55 - 59|60 - 64)$", False),
    "age_65_plus": ("UV102b", r"^all people: (65 - 69|70 - 74|75 - 79|80 - 84|85 and over)$", False),
    "age_80_plus": ("UV102b", r"^all people: (80 - 84|85 and over)$", False),
    "female": ("UV102b", r"^female: all people$", False),
    "ethnic_minority": ("UV201", r"^white: (white scottish|other white british)$", True),
    "eth_asian": ("UV201", r"^asian.*: total$", False),
    "eth_indian": ("UV201", r"^asian.*: indian", False),
    "eth_pakistani": ("UV201", r"^asian.*: pakistani", False),
    "eth_bangladeshi": ("UV201", r"^asian.*: bangladeshi", False),
    "eth_black": ("UV201", r"^(african|caribbean or black): total$", False),
    "eth_mixed": ("UV201", r"^mixed or multiple", False),
    "eth_white_other": ("UV201", r"^(white: (white irish|gypsy|white polish)|other white)", False),
    "religion_christian": ("UV205", r"^(church of scotland|roman catholic|other christian)$", False),
    "religion_muslim": ("UV205", r"^muslim$", False),
    "religion_none": ("UV205", r"^no religion$", False),
    "religion_hindu": ("UV205", r"^hindu$", False),
    "religion_sikh": ("UV205", r"^sikh$", False),
    "religion_jewish": ("UV205", r"^jewish$", False),
    "english_not_main": ("UV212", r"^english$", True),
    "owner_occupied": ("UV404", r"^owned: owned (outright|with a mortgage)", False),
    "owned_outright": ("UV404", r"^owned: owned outright", False),
    "mortgage": ("UV404", r"^owned: owned with a mortgage", False),
    "shared_ownership": ("UV404", r"^owned: shared ownership", False),
    "private_rented": ("UV404", r"^private rented: total$", False),
    "social_rented": ("UV404", r"^social rented", False),
    "overcrowded": ("UV415", r"-1 or less", False),
    "under_occupied": ("UV415", r"\+2 or more", False),
    "flats": ("UV402", r"^flat, maisonette or apartment: total$", False),
    "detached": ("UV402", r"^whole house or bungalow: detached", False),
    "semi_detached": ("UV402", r"^whole house or bungalow: semi-detached", False),
    "terraced": ("UV402", r"^whole house or bungalow: terraced", False),
    "caravan": ("UV402", r"^caravan", False),
    "no_central_heating": ("UV407", r"^no central heating$", False),
    "heat_gas": ("UV407", r"^gas central heating: mains gas", False),
    "heat_oil": ("UV407", r"^oil central heating", False),
    "heat_electric": ("UV407", r"^electric", False),
    "no_car": ("UV405", r"no cars or vans", False),
    "cars_2plus": ("UV405", r"(two|three|four or more) cars or vans", False),
    "bad_health": ("UV302", r"^(bad|very bad)$", False),
    "very_good_health": ("UV302", r"^very good$", False),
    "disabled": ("UV303", r"limited a (lot|little)$", False),
    "disabled_a_lot": ("UV303", r"limited a lot$", False),
    "unpaid_carers": ("UV301", r"^all unpaid carers$", False),
    "carers_50h": ("UV301", r"50 or more hours", False),
    "no_qualifications": ("UV501", r"^no qualifications$", False),
    "apprenticeship": ("UV501", r"^apprenticeship", False),
    "retired": ("UV601", r"^economically inactive - retired$", False),
    "inactive_sick": ("UV601", r"long term sick or disabled", False),
    "looking_after_home": ("UV601", r"looking after home", False),
    "unemployed": ("UV601", r"- unemployed", False),
    "in_employment": ("UV601", r"- (employee|self-employed with employees|self-employed without employees) - total$", False),
    "nssec_professional": ("UV607", r"^l[1-6]:", False),
    "nssec_routine": ("UV607", r"^l1[23]:", False),
    "nssec_self_employed": ("UV607", r"^l[89]:", False),
    "students": ("UV607", r"^l15:", False),
    "work_from_home": ("UV701", r"^work mainly at or from home$", False),
    "commute_car": ("UV701", r"^driving a car", False),
    "commute_public": ("UV701", r"^(bus|train|underground)", False),
    "commute_active": ("UV701", r"^(on foot|bicycle)$", False),
    "commute_train": ("UV701", r"^(train|underground)", False),
    "commute_bus": ("UV701", r"^bus", False),
    "commute_cycle": ("UV701", r"^bicycle$", False),
    "commute_30km_plus": ("UV703", r"^(30km|40km|60km)", False),
    "commute_under_2km": ("UV703", r"^less than 2km$", False),
    "hh_one_person": ("UV113", r"^one person household: total$", False),
    "hh_alone_66": ("UV113", r"^one person household: aged 66 and over$", False),
    "hh_pensioner": ("UV113", r"^(one person household: aged 66 and over|one family household: all aged 66 and over)$", False),
    "hh_large": ("UV406", r"^(five|six|seven|eight or more) people$", False),
}
POPULATION = ("UV102b", "all people: all people")


def find_zip(s: requests.Session, page: str, pattern: str) -> str:
    html = s.get(page, timeout=60).text
    links = [u for u in re.findall(r'href="([^"]+\.zip)"', html) if re.search(pattern, u, re.I)]
    if not links:
        raise LookupError(f"No {pattern} download on {page}")
    return requests.compat.urljoin(page, links[0])


def read_table(text: str) -> pd.DataFrame:
    """One NRS output-area table: rows are output areas, columns the (lower-cased) category labels.

    Tables broken down by sex have two header rows, combined as "top: sub". A dash is a zero."""
    rows = list(csv.reader(io.StringIO(text)))
    first = next(i for i, r in enumerate(rows) if r and re.fullmatch(r"S00\d{6}", r[0].strip()))
    header = [r for r in rows[3:first] if len(r) > 2 and not r[0].strip()]
    clean = lambda x: re.sub(r"\s+", " ", x).strip().lower()  # noqa: E731
    if len(header) >= 2:
        labels = [f"{clean(a)}: {clean(b)}" for a, b in zip(header[-2][1:], header[-1][1:])]
    else:
        labels = [clean(x) for x in header[-1][1:]]
    data = [r for r in rows[first:] if r and re.fullmatch(r"S00\d{6}", r[0].strip())]
    df = pd.DataFrame([r[1:len(labels) + 1] for r in data], index=[r[0].strip() for r in data], columns=labels)
    return df.replace("-", "0").apply(pd.to_numeric, errors="coerce").fillna(0)


def centroids(dbf: bytes) -> pd.DataFrame:
    """Output area code -> easting, northing from the population-weighted centroid shapefile's .dbf table."""
    n, header_len, record_len = struct.unpack("<IHH", dbf[4:12])
    fields, p = [], 32
    while dbf[p] != 0x0D:
        fields.append((dbf[p:p + 11].split(b"\0")[0].decode().lower(), dbf[p + 16]))
        p += 32
    out, offsets, pos = [], {}, 1
    for name, length in fields:
        offsets[name] = (pos, pos + length)
        pos += length
    for k in range(n):
        rec = dbf[header_len + k * record_len: header_len + (k + 1) * record_len]
        get = lambda f: rec[offsets[f][0]:offsets[f][1]].decode("latin-1").strip()  # noqa: E731
        out.append((get("code"), float(get("easting")), float(get("northing"))))
    return pd.DataFrame(out, columns=["oa", "e", "n"]).set_index("oa")


def seat_frames(tables: dict[str, pd.DataFrame], oa_seat: pd.Series) -> dict[str, pd.DataFrame]:
    """Census num/den frames for Scottish seats (same shape as the England & Wales ones)."""
    seats = {t: df.groupby(df.index.map(oa_seat)).sum() for t, df in tables.items()}
    frames = {}
    pop_table, pop_col = POPULATION
    if pop_table in seats:
        frames["population"] = pd.DataFrame({"num": seats[pop_table][pop_col], "den": 1.0})
    for mid, (table, pattern, complement) in MAPPING.items():
        t = seats.get(table)
        if t is None:
            continue
        cols = [c for c in t.columns if re.search(pattern, c)]
        if not cols:
            log.warning("Scotland census: no column matches %s in %s", pattern, table)
            continue
        total = t.iloc[:, 0]
        matched = t[cols].sum(axis=1)
        frames[mid] = pd.DataFrame({"num": (total - matched if complement else matched) * 100, "den": total.where(total > 0)})
    return frames


def load_scotland(s: requests.Session, geo: dict) -> tuple[dict[str, pd.DataFrame], str]:
    r = s.get(find_zip(s, TABLES_PAGE, r"Census-2022-Output-Area"), timeout=900)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    wanted = {t for t, _, _ in MAPPING.values()} | {POPULATION[0]}
    tables = {}
    for name in z.namelist():
        prefix = name.split(" ")[0]
        if prefix in wanted and prefix not in tables:
            tables[prefix] = read_table(z.read(name).decode("utf-8", "replace"))
    g = s.get(find_zip(s, GEOGRAPHY_PAGE, r"pwc"), timeout=300)
    g.raise_for_status()
    gz = zipfile.ZipFile(io.BytesIO(g.content))
    c = centroids(gz.read(next(n for n in gz.namelist() if n.lower().endswith(".dbf"))))
    lon, lat = en_to_lonlat(c["e"], c["n"])
    oa_seat = pd.Series(SeatLocator(geo).seats(lon, lat), index=c.index).dropna()
    oa_seat = oa_seat[oa_seat.str.startswith("S")]
    log.info("Scotland census: %d tables, %d of %d output areas placed in %d seats", len(tables), len(oa_seat), len(c),
             oa_seat.nunique())
    return seat_frames(tables, oa_seat), "March 2022"
