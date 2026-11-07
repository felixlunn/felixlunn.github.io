import inspect
import re

import whips.demo as demo
from whips.metrics import CENSUS_METRICS, CLAIMANT_METRICS, ELECTION_METRICS, POLICE_METRICS, census_meta, source_url


def all_metas():
    names = re.search(r"extra = (.+)", inspect.getsource(demo)).group(1).split(" + ")
    metas = [census_meta(m) for m in CENSUS_METRICS] + list(CLAIMANT_METRICS) + list(ELECTION_METRICS) + list(POLICE_METRICS)
    for n in names:
        metas += list(getattr(demo, n.strip()))
    return metas


def test_every_metric_links_to_its_source():
    missing = sorted({m.source for m in all_metas() if not source_url(m.source)})
    assert missing == [], f"Add these sources to SOURCE_LINKS: {missing}"


def test_census_tables_link_to_nomis():
    assert source_url("Census 2021 TS007A (ONS via Nomis)") == "https://www.nomisweb.co.uk/datasets/c2021ts007a"
