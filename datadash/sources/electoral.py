"""Electoral registration by constituency (ONS electoral statistics, latest 1 December register). UK.

Each December, councils report how many people are on the electoral register. ONS publishes the counts for the
current Westminster constituencies (from the December 2025 edition; earlier editions used the old boundaries and
are skipped). Three figures per seat:

* registered electors on the latest register;
* the change since the July 2024 general election (that election's electorate, from the results), which shows where
  the register has shrunk, a sign of people dropping off or not re-registering after moving;
* attainers per 1,000 electors: young people already registered who turn 18 before the next register, a sign of how
  well young people are being registered (England only; see seat_frames).
"""

from __future__ import annotations

import io
import logging
import re

import pandas as pd
import requests

from ..metrics import MetricMeta

log = logging.getLogger(__name__)

SOURCE_URL = "https://www.ons.gov.uk/peoplepopulationandcommunity/elections/electoralregistration/datasets/electoralstatisticsforuk"
SEAT_CODE = re.compile(r"^(E14|W07|S14|N05)\d{6}$")

ELECTORAL_METRICS = [
    MetricMeta("electors", "Registered electors", "politics", "people",
               "People on the electoral register for UK Parliament elections, 1 December (ONS electoral statistics, latest register).",
               "ONS electoral statistics", "neutral", 0, ("electoral_registration",)),
    MetricMeta("electors_change", "Change in electors since the 2024 election", "politics", "%",
               "Change in the number of registered electors between the July 2024 general election and the latest 1 December "
               "register (ONS electoral statistics; 2024 electorate from the election results). A fall can mean people "
               "dropping off the register, e.g. after moving home.",
               "ONS electoral statistics", "higher_better", 1, ("electoral_registration",)),
    MetricMeta("attainers_per_1000", "Young people registered early (per 1,000 electors)", "politics", "per 1,000",
               "Attainers: people on the latest register who turn 18 before the next one, per 1,000 electors (ONS electoral "
               "statistics). Higher means more young people are being registered ahead of being able to vote. England only: "
               "in Scotland and Wales, where 16- and 17-year-olds vote in devolved elections, young people register earlier.",
               "ONS electoral statistics", "higher_better", 1, ("electoral_registration",)),
]


def editions(html: str) -> list[str]:
    """The workbooks linked from the dataset page, in page order (newest first)."""
    return ["https://www.ons.gov.uk" + u for u in re.findall(r'href="(/file\?uri=[^"]+\.xlsx?)"', html)]


def parse_table(book: pd.ExcelFile) -> tuple[pd.DataFrame, str] | None:
    """(electors and attainers by current constituency, register date) from a workbook, or None if it has none.

    Looks for a sheet whose header row starts "Code" and has an "Electoral registrations" column; when a table gives
    several years, the latest is used."""
    for sheet in book.sheet_names:
        raw = pd.read_excel(book, sheet_name=sheet, header=None)
        if raw.empty:
            continue
        head = next((i for i in range(min(15, len(raw))) if str(raw.iloc[i, 0]).strip() == "Code"), None)
        if head is None:
            continue
        cols = [re.sub(r"\s+", " ", str(c)).strip() for c in raw.iloc[head]]
        regs = [j for j, c in enumerate(cols) if c.lower().startswith("electoral registrations")]
        atts = [j for j, c in enumerate(cols) if "attainers" in c.lower()]
        if not regs:
            continue
        t = raw.iloc[head + 1:]
        code = t[0].astype(str).str.strip()
        seat = code.str.match(SEAT_CODE)
        # Only the 2024 boundaries: their English codes run from E14001063 (earlier editions use E14000530-E14001062).
        english = code[seat & code.str.startswith("E14")].str[3:].astype(int)
        if seat.sum() < 600 or (english >= 1063).sum() < 500:
            continue
        num = lambda j: pd.to_numeric(t.loc[seat, j], errors="coerce").values  # noqa: E731
        out = pd.DataFrame({"electors": num(regs[-1])}, index=code[seat].values)
        if atts:
            out["attainers"] = num(atts[-1])
        title = " ".join(str(v) for v in raw.iloc[:head, 0].dropna())
        m = re.search(r"\b1 (\w+ \d{4})", title) or re.search(r"(December \d{4})", " ".join(cols[regs[-1]:regs[-1] + 1]))
        return out.dropna(subset=["electors"]), (m.group(1) if m else "latest")
    return None


def seat_frames(t: pd.DataFrame, electorate_2024: pd.Series | None) -> dict[str, pd.DataFrame]:
    out = {"electors": pd.DataFrame({"num": t["electors"], "den": 1.0})}
    if "attainers" in t:
        # England only: in Scotland and Wales 16- and 17-year-olds vote in devolved elections and young people are
        # registered earlier (medians in Dec 2025: 9.3 and 7.0 per 1,000, against 2.4 in England), so seats there
        # aren't comparable with English ones.
        a = t[t.index.str.startswith("E14")].dropna(subset=["attainers"])
        out["attainers_per_1000"] = pd.DataFrame({"num": a["attainers"] * 1000, "den": a["electors"]})
    if electorate_2024 is not None:
        before = electorate_2024.reindex(t.index)
        ok = before.notna() & (before > 0)
        out["electors_change"] = pd.DataFrame({"num": (t["electors"] - before)[ok] * 100, "den": before[ok]})
    return out


def load_electoral(s: requests.Session, electorate_2024: pd.Series | None) -> tuple[dict[str, pd.DataFrame], str]:
    """Figures from the newest edition on the current boundaries (older ones are tried if the newest has none)."""
    html = s.get(SOURCE_URL, timeout=60).text
    for url in editions(html)[:4]:
        r = s.get(url, timeout=120)
        r.raise_for_status()
        found = parse_table(pd.ExcelFile(io.BytesIO(r.content)))
        if found:
            t, when = found
            log.info("Electoral registers: %d seats (%s)", len(t), when)
            return seat_frames(t, electorate_2024), f"1 {when} register"
    raise LookupError("No electoral statistics for the current constituencies on the ONS page")
