"""Shared HTTP session with retries and a polite user agent."""

from __future__ import annotations

import logging
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

USER_AGENT = "WhipsDashboard/0.1 (+https://github.com/felixlunnLD/Whips-Dashboard)"


def session(pool: int = 16) -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=pool, pool_maxsize=pool)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers["User-Agent"] = USER_AGENT
    return s


def get_json(s: requests.Session, url: str, **kwargs):
    t0 = time.time()
    r = s.get(url, timeout=kwargs.pop("timeout", 120), **kwargs)
    r.raise_for_status()
    log.debug("GET %s (%.1fs)", r.url, time.time() - t0)
    return r.json()
