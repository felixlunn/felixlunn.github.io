"""Optional REST API over the same dataset the dashboard uses.

The dashboard itself is fully static (analytics run in the browser), so this
API is for programmatic access: other tools, notebooks, briefings.

    WHIPS_DATA=frontend/public/data/data.json uvicorn whips.api:app

``WHIPS_DATA`` may also be an https URL to a deployed ``data.json``.
"""

from __future__ import annotations

import json
import os
import urllib.request
from functools import lru_cache

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import engine

app = FastAPI(title="Whips Dashboard API", version="0.1.0",
              description="Constituency statistics, rankings, twin seats, and custom indices.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])


@lru_cache(maxsize=1)
def dataset() -> engine.Dataset:
    src = os.environ.get("WHIPS_DATA", "frontend/public/data/data.json")
    if src.startswith(("http://", "https://")):
        with urllib.request.urlopen(src, timeout=60) as r:  # noqa: S310 - configured by operator
            return engine.Dataset.from_json(json.load(r))
    return engine.Dataset.load(src)


def _seat(ds: engine.Dataset, code: str) -> dict:
    try:
        return ds.seats[ds.index_of(code)]
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from None


@app.get("/api/v1/metrics")
def metrics():
    return dataset().metrics


@app.get("/api/v1/constituencies")
def constituencies():
    return dataset().seats


@app.get("/api/v1/constituencies/{code}")
def constituency(code: str):
    ds = dataset()
    seat = _seat(ds, code)
    return {**seat, "metrics": {m["id"]: {**ds.rank(m["id"], code), "national": m["national"]} for m in ds.metrics}}


@app.get("/api/v1/twins/{code}")
def twins(code: str, top_n: int = Query(10, ge=1, le=100), method: str = Query("euclidean", pattern="^(euclidean|cosine)$"),
          metrics: str | None = Query(None, description="Comma-separated metric ids (default: census profile)"),
          country: str | None = None, region: str | None = None):
    ds = dataset()
    _seat(ds, code)
    ids = metrics.split(",") if metrics else None
    try:
        return engine.twins(ds, code, ids, method, top_n, country, region)
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from None


@app.post("/api/v1/index")
def custom_index(weights: dict[str, float] = Body(..., examples=[{"private_rented": 0.4, "level4_plus": 0.3, "inactive_sick": 0.3}])):
    try:
        return engine.composite_index(dataset(), weights)
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from None
