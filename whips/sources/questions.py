"""Written questions tabled by each MP (UK Parliament written questions API).

One request per MP asks how many written questions they tabled in the last 12
months (the API returns a total count). Government ministers and the Speaker
don't table written questions, so they show low or zero counts.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pandas as pd
import requests

from ..http import get_json
from ..metrics import MetricMeta

log = logging.getLogger(__name__)

API = "https://questions-statements-api.parliament.uk/api/writtenquestions/questions"
SOURCE_URL = "https://questions-statements.parliament.uk/written-questions"

QUESTION_METRICS = [
    MetricMeta("wq_last_year", "Written questions tabled (last 12 months)", "politics", "questions",
               "Written parliamentary questions tabled by the constituency's current MP in the last 12 months. Ministers and "
               "the Speaker don't table written questions. National figure: average per MP.",
               "UK Parliament written questions API", "neutral", 0, ("parliament",)),
]


def count(s: requests.Session, member_id: int, since: date) -> int:
    data = get_json(s, API, params={"askingMemberId": member_id, "tabledWhenFrom": since.isoformat(), "take": 1})
    return int(data.get("totalResults", 0))


def load_questions(s: requests.Session, members: dict[str, dict], today: date | None = None,
                   workers: int = 6) -> tuple[dict[str, pd.DataFrame], str]:
    """Written questions per seat's current MP. ``members`` maps seat code -> member record with ``mp_id``."""
    since = (today or date.today()) - timedelta(days=365)
    ids = {code: m["mp_id"] for code, m in members.items() if m.get("mp_id")}
    if not ids:
        raise ValueError("No current MPs to look up")
    with ThreadPoolExecutor(workers) as pool:
        counts = dict(zip(ids, pool.map(lambda mid: count(s, mid, since), ids.values())))
    n = pd.Series(counts, dtype=float)
    log.info("Written questions: %d MPs, %d questions", len(n), int(n.sum()))
    return {"wq_last_year": pd.DataFrame({"num": n, "den": 1.0})}, f"Tabled since {since.isoformat()}"
