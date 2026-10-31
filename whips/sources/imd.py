"""English Indices of Deprivation 2025 (MHCLG), by LSOA (2021), England only.

Uses File 7 (all ranks, scores, deciles and population denominators), found
through the GOV.UK content API so a reissued file doesn't break the pipeline.
Constituency figures are built from LSOAs with the ONS best-fit lookup,
weighting each LSOA by the population the measure refers to, as the House of
Commons Library does.
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

CONTENT_API = "https://www.gov.uk/api/content/government/statistics/english-indices-of-deprivation-2025"
PAGE_URL = "https://www.gov.uk/government/statistics/english-indices-of-deprivation-2025"
FALLBACK_URL = ("https://assets.publishing.service.gov.uk/media/691ded56d140bbbaa59a2a7d/"
                "File_7_IoD2025_All_Ranks_Scores_Deciles_Population_Denominators.csv")
SOURCE = "English Indices of Deprivation 2025 (MHCLG)"

# column key -> regex on File 7 headers
COLUMNS = {
    "lsoa": r"^LSOA code",
    "score": r"^Index of Multiple Deprivation \(IMD\) Score",
    "decile": r"^Index of Multiple Deprivation \(IMD\) Decile",
    "income": r"^Income Score",
    "employment": r"^Employment Score",
    "idaci": r"\(IDACI\) Score",
    "idaopi": r"\(IDAOPI\) Score",
    "pop": r"^Total population",
    "pop_children": r"^Dependent Children",
    "pop_older": r"^Older population",
    "pop_working": r"^Working age population",
}


def _m(id, label, unit, description, decimals=1) -> MetricMeta:
    return MetricMeta(id, label, "deprivation", unit, description, SOURCE, "higher_worse", decimals, ("imd",))


IMD_METRICS = [
    _m("imd_most_deprived_10", "In most deprived 10% of areas", "%",
       "Share of residents living in neighbourhoods (LSOAs) among the 10% most deprived in England on the Index of Multiple Deprivation 2025."),
    _m("imd_most_deprived_20", "In most deprived 20% of areas", "%",
       "Share of residents living in neighbourhoods (LSOAs) among the 20% most deprived in England on the Index of Multiple Deprivation 2025."),
    _m("imd_score", "IMD score (average)", "score",
       "Population-weighted average Index of Multiple Deprivation 2025 score of the constituency's neighbourhoods. Higher is more deprived."),
    _m("income_deprived", "Income deprived", "%",
       "Share of residents in income deprivation (IoD 2025 income domain). The 2025 index uses a broader income measure than 2019, so rates are not comparable with earlier editions."),
    _m("employment_deprived", "Employment deprived", "%",
       "Share of working-age residents involuntarily out of work through unemployment, sickness, disability or caring (IoD 2025 employment domain)."),
    _m("idaci", "Children in income-deprived households", "%",
       "Share of children aged 0-15 living in income-deprived families (IDACI 2025). Not comparable with IDACI 2019, which used a narrower income measure."),
    _m("idaopi", "Older people in income deprivation", "%",
       "Share of people aged 60 and over in income deprivation (IDAOPI 2025)."),
]

# metric -> (File 7 column, population column it is a rate of)
RATES = {
    "income_deprived": ("income", "pop"),
    "employment_deprived": ("employment", "pop_working"),
    "idaci": ("idaci", "pop_children"),
    "idaopi": ("idaopi", "pop_older"),
}


def find_file_url(s: requests.Session) -> str:
    try:
        data = get_json(s, CONTENT_API)
        for a in data.get("details", {}).get("attachments", []):
            if str(a.get("title", "")).startswith("File 7") and str(a.get("url", "")).lower().endswith(".csv"):
                return a["url"]
    except (requests.RequestException, ValueError) as exc:
        log.warning("GOV.UK content API failed (%s); using the known File 7 URL", exc)
    return FALLBACK_URL


def parse_file7(df: pd.DataFrame) -> pd.DataFrame:
    """Tidy File 7 to one row per LSOA with the columns in ``COLUMNS``."""
    cols = {}
    for key, pattern in COLUMNS.items():
        hit = next((c for c in df.columns if re.search(pattern, str(c).strip(), re.I)), None)
        if hit is None:
            raise ValueError(f"IMD file has no column matching {pattern!r}")
        cols[key] = hit
    out = df[list(cols.values())].copy()
    out.columns = list(cols)
    out["lsoa"] = out["lsoa"].astype(str).str.strip()
    for c in out.columns[1:]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out.set_index("lsoa")


def load_imd(s: requests.Session) -> pd.DataFrame:
    url = find_file_url(s)
    r = s.get(url, timeout=180)
    r.raise_for_status()
    imd = parse_file7(pd.read_csv(io.BytesIO(r.content)))
    if len(imd) < 30_000:
        raise ValueError(f"IMD file looks incomplete: {len(imd)} LSOAs")
    return imd


def lsoa_frames(imd: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Per-LSOA values: the score, and each rate as a percentage."""
    one = pd.Series(1.0, index=imd.index)
    out = {"imd_score": pd.DataFrame({"num": imd["score"], "den": one})}
    for mid, (col, _) in RATES.items():
        out[mid] = pd.DataFrame({"num": imd[col] * 100, "den": one})
    return out


def seat_frames(imd: pd.DataFrame, lookup: dict[str, str]) -> dict[str, pd.DataFrame]:
    """Constituency num/den frames, summing LSOAs with the best-fit lookup and population weights."""
    d = imd.assign(pcon=imd.index.map(lookup)).dropna(subset=["pcon"])
    g = d.groupby("pcon")
    pop = g["pop"].sum()
    out = {
        "imd_most_deprived_10": pd.DataFrame({"num": g.apply(lambda x: x.loc[x["decile"] <= 1, "pop"].sum()) * 100, "den": pop}),
        "imd_most_deprived_20": pd.DataFrame({"num": g.apply(lambda x: x.loc[x["decile"] <= 2, "pop"].sum()) * 100, "den": pop}),
        "imd_score": pd.DataFrame({"num": (d["score"] * d["pop"]).groupby(d["pcon"]).sum(), "den": pop}),
    }
    for mid, (col, base) in RATES.items():
        out[mid] = pd.DataFrame({"num": (d[col] * d[base] * 100).groupby(d["pcon"]).sum(), "den": g[base].sum()})
    return out
