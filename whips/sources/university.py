"""Young people going on to higher education, by neighbourhood (Office for Students TUNDRA). England.

TUNDRA gives, for each neighbourhood (LSOA, 2011 codes), the share of state-
school pupils who sat GCSEs at 16 and went on to higher education by age 19
(cohorts aged 16 in 2012 to 2016; the latest neighbourhood release). Seats
average their neighbourhoods weighted by cohort size; small neighbourhoods
are suppressed and neighbourhoods recoded in 2021 drop out.
"""

from __future__ import annotations

import io
import logging
import zipfile

import pandas as pd
import requests

from ..metrics import MetricMeta

log = logging.getLogger(__name__)

URL = "https://www.officeforstudents.org.uk/media/5535/tundra-lsoa-msoa-notes-csv.zip"
SOURCE_URL = "https://www.officeforstudents.org.uk/data-and-analysis/young-participation-by-area/about-tundra/"

UNIVERSITY_METRICS = [
    MetricMeta("he_progression", "Young people going on to higher education", "education", "%",
               "State-school pupils from the constituency's neighbourhoods who went on to higher education by age 19 "
               "(Office for Students TUNDRA, cohorts aged 16 in 2012-2016).", "Office for Students TUNDRA",
               "higher_better", 0, ("university",)),
]


def parse(csv: bytes) -> pd.DataFrame:
    d = pd.read_csv(io.BytesIO(csv))
    d = d.assign(rate=pd.to_numeric(d["progression_rate"], errors="coerce"),
                 pop=pd.to_numeric(d["total_pop"], errors="coerce")).dropna(subset=["rate", "pop"])
    return pd.DataFrame({"rate": d["rate"].values, "pop": d["pop"].values}, index=d.iloc[:, 0].astype(str).values)


def seat_frame(lsoa: pd.DataFrame, lsoa_to_pcon: dict[str, str]) -> pd.DataFrame:
    d = lsoa.assign(pcon=lsoa.index.map(lsoa_to_pcon)).dropna(subset=["pcon"])
    g = d.assign(n=d["rate"] * d["pop"]).groupby("pcon")
    return pd.DataFrame({"num": g["n"].sum() * 100, "den": g["pop"].sum()})


def load_university(s: requests.Session, lsoa_to_pcon: dict[str, str]) -> tuple[dict[str, pd.DataFrame], str]:
    r = s.get(URL, timeout=120)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    name = next(n for n in z.namelist() if n.lower().startswith("lsoa") and n.lower().endswith(".csv"))
    return {"he_progression": seat_frame(parse(z.read(name)), lsoa_to_pcon)}, "Cohorts aged 16 in 2012-2016"
