"""Upcoming Commons debates from the UK Parliament "What's On" calendar API.

Each debate is tagged with topics by keyword rules, and each topic points at
dashboard metrics. The dashboard then flags seats that stand out on those
metrics (e.g. a policing debate flags seats with unusually high crime).

Only debates are kept: oral questions, PMQs, statements, Private Members'
Bills and other non-debate business are dropped.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

import requests

from ..http import get_json

API = "https://whatson-api.parliament.uk/calendar/events/list.json"
SOURCE_URL = "https://whatson.parliament.uk/"

DEBATE_CATEGORIES = {
    "Adjournment", "Backbench Business", "Debate", "Legislation", "Opposition Day Debate",
    "Westminster Hall debate", "Estimates Day", "Lords Amendments",
}  # Private Members' Bills are deliberately left out

# topic id -> (label, title regex, metric ids that matter for it). Metric ids missing from the
# dataset are ignored by the dashboard.
TOPICS: dict[str, tuple[str, str, list[str]]] = {
    "policing": ("Policing & crime",
                 r"police|policing|crime|criminal|knife|anti-?social|burglar|shoplift|theft|drug|county lines|"
                 r"violence|abuse|assault|strangulation|fraud|victims|justice|prison|sentenc|stalking|vawg|off-road bikes",
                 ["crime_rate", "crime_violence", "crime_asb", "crime_burglary", "crime_shoplifting", "crime_vehicle",
                  "crime_drugs", "outcome_no_suspect"]),
    "health": ("Health & care",
               r"\bnhs\b|health|hospital|\bgps?\b|general practi|dent(al|ist)|cancer|ambulance|hospice|patients?|"
               r"social care|carers?\b|disab|dementia|stroke|nurs|gynaecolog|menopaus|endometriosis|maternity|medic",
               ["gp_contact_good", "gp_wait_ok", "nhs_diabetes", "nhs_depression", "nhs_dementia", "nhs_copd", "bad_health",
                "disabled_a_lot", "carers_50h"]),
    "housing": ("Housing",
                r"housing|\bhomes?\b|planning|\brent(ers?|ed|ing|s)?\b|leasehold|homeless|landlord|mortgage|council tax|"
                r"stamp duty|temporary accommodation",
                ["private_rented", "social_rented", "overcrowded", "deprived_2plus", "hh_no_english", "flats"]),
    "cost_of_living": ("Cost of living & work",
                       r"cost of living|economy|economic|jobs?\b|employment|unemploy|wages?|\bpay\b|benefit|universal credit|"
                       r"welfare|poverty|minimum wage|budget|\btax|pensions?|bereavement support|household support",
                       ["income_deprived", "employment_deprived", "claimant_rate", "imd_most_deprived_20", "aps_inactive",
                        "inactive_sick", "never_worked"]),
    "energy": ("Energy & heating",
               r"energy|fuel|heating|heat pump|net zero|climate|electricity|\bgas\b|insulation|solar",
               ["epc_f_g", "heat_oil", "heat_electric", "no_central_heating"]),
    "transport": ("Transport",
                  r"transport|\bbus(es)?\b|\brail|\btrains?\b|\broads?\b|pothole|cycl|motorist|driving|car park|travel|airport",
                  ["no_car", "commute_bus", "commute_train", "commute_car", "commute_30km_plus"]),
    "education": ("Education & children",
                  r"school|education|teacher|\bsend\b|special educational|universit|students?|skills|apprentice|"
                  r"childcare|nurser|children|young people|learning",
                  ["gcse_em4", "school_fsm", "idaci", "no_qualifications", "age_0_14", "hh_dependent_children"]),
    "rural": ("Rural & farming",
              r"farm|agricultur|rural|countryside|fishing|fisheries|food security|coastal|national park",
              ["jobs_agriculture", "heat_oil", "commute_30km_plus"]),
    "older_people": ("Older people",
                     r"pension|older people|elderly|winter fuel|retire|loneliness|later life",
                     ["idaopi", "age_65_plus", "age_80_plus", "hh_alone_66", "hh_pensioner", "carers_50h"]),
    "immigration": ("Immigration",
                    r"immigra|asylum|migra|refugee|visa|small boats|border",
                    ["born_outside_uk", "arrived_since_2011", "english_not_main"]),
    "business": ("Business & high streets",
                 r"business|hospitality|high streets?|retail|\bshops?\b|\bpubs?\b|tourism|small firms|business rates",
                 ["jobs_hospitality", "jobs_retail", "business_micro", "self_employed"]),
}


def topics_for(title: str) -> list[str]:
    t = title.lower()
    return [tid for tid, (_, pattern, _) in TOPICS.items() if re.search(pattern, t)]


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def parse_events(events: list[dict]) -> list[dict]:
    """Keep debates only, tag topics and lead members, sorted by date and time."""
    out = []
    for e in sorted(events, key=lambda e: ((e.get("StartDate") or "")[:10], e.get("SortOrder") or 0)):
        category = _clean(e.get("Category"))
        if category not in DEBATE_CATEGORIES or e.get("CancelledDate") or e.get("Type") not in ("Main Chamber", "Westminster Hall"):
            continue
        day = (e.get("StartDate") or "")[:10]
        title = _clean(e.get("Description")) or _clean(e.get("BillName")) or category
        members = [
            {"name": m.get("Name"), "party": m.get("Party"), "constituency": m.get("MemberFrom")}
            for m in e.get("Members") or [] if m.get("Name")
        ]
        out.append({
            "id": e.get("Id"),
            "date": day,
            "time": e.get("StartTime"),
            "venue": e.get("Type"),
            "category": category,
            "title": title,
            "members": members,
            "topics": topics_for(title),
        })
    return out


def load_debates(s: requests.Session, days: int = 21, today: date | None = None) -> list[dict]:
    start = today or date.today()
    events = get_json(s, API, params={
        "queryParameters.startDate": start.isoformat(),
        "queryParameters.endDate": (start + timedelta(days=days)).isoformat(),
        "queryParameters.house": "Commons",
    })
    return parse_events(events if isinstance(events, list) else [])


def topic_catalogue() -> list[dict]:
    return [{"id": tid, "label": label, "metrics": metrics} for tid, (label, _, metrics) in TOPICS.items()]
