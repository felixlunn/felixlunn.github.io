"""Police officers per 100,000 people by police force area (Home Office police workforce statistics). England & Wales.

Each seat gets its police force area's figure (the area most of its
neighbourhoods fall in, as for the court backlog). London's two forces and
the three South Wales-area forces are grouped as in the court data, combining
officers and population.
"""

from __future__ import annotations

import logging
import re

import pandas as pd
import requests

from ..http import get_json
from ..metrics import MetricMeta
from ..ods import find_table, read_ods
from .courts import area_key, seat_areas

log = logging.getLogger(__name__)

COLLECTION = "https://www.gov.uk/api/content/government/collections/police-workforce-england-and-wales"
CONTENT = "https://www.gov.uk/api/content"
SOURCE_URL = "https://www.gov.uk/government/collections/police-workforce-england-and-wales"

POLICE_WORKFORCE_METRICS = [
    MetricMeta("police_officers_per_100k", "Police officers per 100,000 people", "policing", "per 100,000",
               "Full-time equivalent police officers in the seat's police force area per 100,000 residents (Home Office, "
               "latest March or September). Area-wide: every seat in the same force area has the same value.",
               "Home Office police workforce", "higher_better", 0, ("police_workforce",)),
]


def find_file(s: requests.Session) -> tuple[str, str]:
    docs = [d for d in get_json(s, COLLECTION).get("links", {}).get("documents", [])
            if re.search(r"police-workforce-england-and-wales-\d", d.get("base_path", ""))]
    for d in sorted(docs, key=lambda d: d.get("public_updated_at", ""), reverse=True)[:3]:
        for a in get_json(s, CONTENT + d["base_path"]).get("details", {}).get("attachments", []):
            t = str(a.get("title", "")).lower()
            if t.endswith("data tables") and str(a.get("url", "")).endswith(".ods"):
                return a["url"], d.get("title", "").split(": ")[-1]
    raise LookupError("No police workforce data tables found")


def by_force(sheet: pd.DataFrame) -> tuple[pd.DataFrame, float | None]:
    """Officers and population by area key; and the England & Wales rate."""
    t = find_table(sheet, "PFA code")
    col = lambda *w: next(c for c in t.columns if all(x in c.lower() for x in w))  # noqa: E731
    officers = pd.to_numeric(t[col("total officers", "fte")], errors="coerce")
    rate = pd.to_numeric(t[col("total officers per")], errors="coerce")
    code, name = t.iloc[:, 0].astype(str).str.strip(), t.iloc[:, 1].astype(str).str.strip()
    ew = rate[name.str.lower().str.startswith("england and wales")]
    forces = code.str.match(r"^(E23|W15)\d{6}$") & officers.notna() & rate.gt(0)
    d = pd.DataFrame({"area": name[forces].map(area_key).values, "officers": officers[forces].values,
                      "population": (officers / rate * 100_000)[forces].values})
    return d.groupby("area").sum(), (float(ew.iloc[0]) if len(ew) else None)


def seat_frames(forces: pd.DataFrame, seat_area: dict[str, str], population: pd.Series) -> pd.DataFrame:
    sa = pd.Series(seat_area)
    rate = (forces["officers"] * 100_000 / forces["population"]).reindex(sa.values)
    rate.index = sa.index
    pop = population.reindex(sa.index)
    return pd.DataFrame({"num": rate * pop, "den": pop.where(rate.notna())})


def load_police_workforce(s: requests.Session, lsoa_to_pcon: dict[str, str], population: pd.Series) -> tuple[dict[str, pd.DataFrame], str]:
    url, when = find_file(s)
    r = s.get(url, timeout=180)
    r.raise_for_status()
    sheets = read_ods(r.content)
    sheet = next(v for v in sheets.values() if "per 100,000" in str(v.iloc[0, 0]) and "police officers" in str(v.iloc[0, 0]).lower())
    forces, national = by_force(sheet)
    seat_area = seat_areas(s, lsoa_to_pcon)
    missing = sorted(set(seat_area.values()) - set(forces.index))
    if missing:
        log.warning("Police workforce: no figures for %s", missing)
    f = seat_frames(forces, seat_area, population)
    f.attrs["national"] = national
    return {"police_officers_per_100k": f}, f"As at {when}"
