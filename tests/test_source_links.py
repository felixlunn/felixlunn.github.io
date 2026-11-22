from datadash.metrics import CENSUS_METRICS, census_meta, source_url
from datadash.registry import all_metrics


def all_metas():
    return [census_meta(m) for m in CENSUS_METRICS] + all_metrics()


def test_every_metric_links_to_its_source():
    missing = sorted({m.source for m in all_metas() if not source_url(m.source)})
    assert missing == [], f"Add these sources to SOURCE_LINKS: {missing}"


def test_census_tables_link_to_nomis():
    assert source_url("Census 2021 TS007A (ONS via Nomis)") == "https://www.nomisweb.co.uk/datasets/c2021ts007a"
