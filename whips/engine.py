"""Constituency analytics engine.

The same algorithms run in the browser (``frontend/src/lib/analytics.ts``) so
that sliders and weights respond instantly; this Python implementation powers
the pipeline (peer groups) and the optional REST API, and is the reference the
TypeScript port is tested against.

Everything is plain NumPy: with ~650 constituencies and ~60 metrics an exact
nearest-neighbour search takes well under a millisecond, so approximate
indexes (FAISS/Annoy) would add complexity without any speed benefit. They
become worthwhile only for small-area data (e.g. 180k Output Areas).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class Dataset:
    seats: list[dict]
    metrics: list[dict]
    values: dict[str, np.ndarray]

    @classmethod
    def from_json(cls, data: dict) -> "Dataset":
        values = {
            k: np.array([np.nan if v is None else float(v) for v in arr], dtype=float)
            for k, arr in data["values"].items()
        }
        return cls(seats=data["seats"], metrics=data["metrics"], values=values)

    @classmethod
    def load(cls, path: str | Path) -> "Dataset":
        return cls.from_json(json.loads(Path(path).read_text()))

    # --- lookups --------------------------------------------------------
    @property
    def codes(self) -> list[str]:
        return [s["code"] for s in self.seats]

    def index_of(self, code: str) -> int:
        try:
            return self.codes.index(code)
        except ValueError:
            raise KeyError(f"Unknown constituency code {code}") from None

    def metric(self, metric_id: str) -> dict:
        for m in self.metrics:
            if m["id"] == metric_id:
                return m
        raise KeyError(f"Unknown metric {metric_id}")

    def default_profile_metrics(self) -> list[str]:
        """Census proportions: the demographic 'DNA' used for twins and peer groups."""
        return [m["id"] for m in self.metrics if "census" in m.get("tags", []) and m["unit"] == "%"]

    def matrix(self, metric_ids: list[str]) -> np.ndarray:
        return np.column_stack([self.values[m] for m in metric_ids])

    # --- single-metric statistics --------------------------------------
    def rank(self, metric_id: str, code: str) -> dict:
        """Rank 1 = highest value. Ties share the best rank."""
        v = self.values[metric_id]
        x = v[self.index_of(code)]
        valid = v[~np.isnan(v)]
        if np.isnan(x):
            return {"value": None, "rank": None, "of": int(valid.size), "percentile": None}
        rank = int((valid > x).sum()) + 1
        pct = float((valid < x).sum() + 0.5 * ((valid == x).sum() - 1)) / max(valid.size - 1, 1) * 100
        return {"value": float(x), "rank": rank, "of": int(valid.size), "percentile": round(pct, 1)}


def zscore(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mu = np.nanmean(X, axis=0)
    sd = np.nanstd(X, axis=0)
    sd = np.where(sd > 0, sd, 1.0)
    return (X - mu) / sd, mu, sd


def _filter_mask(ds: Dataset, country: str | None, region: str | None) -> np.ndarray:
    mask = np.ones(len(ds.seats), dtype=bool)
    if country:
        mask &= np.array([s.get("country") == country for s in ds.seats])
    if region:
        mask &= np.array([s.get("region") == region for s in ds.seats])
    return mask


def twins(ds: Dataset, code: str, metric_ids: list[str] | None = None, method: str = "euclidean",
          top_n: int = 10, country: str | None = None, region: str | None = None) -> list[dict]:
    """Constituencies most similar to ``code`` across standardised metrics.

    ``euclidean`` compares levels (a seat with 40% renters matches others near 40%);
    ``cosine`` compares the *shape* of the profile relative to the national mean.
    Seats lacking any of the chosen metrics are skipped.
    """
    metric_ids = metric_ids or ds.default_profile_metrics()
    X = ds.matrix(metric_ids)
    complete = ~np.isnan(X).any(axis=1)
    i = ds.index_of(code)
    if not complete[i]:
        raise ValueError(f"{code} lacks data for the selected metrics")
    Z = np.full_like(X, np.nan)
    Z[complete], _, _ = zscore(X[complete])
    t = Z[i]
    if method == "cosine":
        norms = np.linalg.norm(Z, axis=1) * (np.linalg.norm(t) or 1.0)
        score = (Z @ t) / np.where(norms > 0, norms, 1.0)
        order = np.argsort(-np.nan_to_num(score, nan=-np.inf))
    elif method == "euclidean":
        dist = np.sqrt(np.nansum((Z - t) ** 2, axis=1) / len(metric_ids))
        score = 1 / (1 + dist)  # 1 = identical
        order = np.argsort(np.where(complete, dist, np.inf))
    else:
        raise ValueError("method must be 'cosine' or 'euclidean'")
    mask = _filter_mask(ds, country, region) & complete
    mask[i] = False
    out = []
    for j in order:
        if mask[j]:
            out.append({"code": ds.seats[j]["code"], "name": ds.seats[j]["name"], "similarity": round(float(score[j]), 4)})
            if len(out) >= top_n:
                break
    return out


def composite_index(ds: Dataset, weights: dict[str, float]) -> list[dict]:
    """Weighted sum of z-scores, divided by total absolute weight. Negative weights invert a metric.

    Seats missing any weighted metric get no score. Returns all seats ranked (1 = highest score).
    """
    weights = {k: float(v) for k, v in weights.items() if v}
    if not weights:
        raise ValueError("At least one non-zero weight is required")
    ids = list(weights)
    X = ds.matrix(ids)
    complete = ~np.isnan(X).any(axis=1)
    Z = np.full_like(X, np.nan)
    Z[complete], _, _ = zscore(X[complete])
    w = np.array([weights[k] for k in ids])
    score = (Z @ w) / np.abs(w).sum()
    order = np.argsort(-np.where(complete, score, -np.inf))
    out, rank = [], 0
    for j in order:
        if not complete[j]:
            continue
        rank += 1
        out.append({"code": ds.seats[j]["code"], "name": ds.seats[j]["name"], "score": round(float(score[j]), 4), "rank": rank})
    return out


def match_profile(ds: Dataset, targets: dict[str, float], top_n: int = 10,
                  country: str | None = None, region: str | None = None) -> list[dict]:
    """Seats closest to a target profile, e.g. {"private_rented": 35, "age_20_34": 30}.

    Distance is Euclidean in standard-deviation units, so a 1-SD miss on any metric costs the same.
    """
    ids = list(targets)
    X = ds.matrix(ids)
    complete = ~np.isnan(X).any(axis=1)
    _, mu, sd = zscore(X[complete])
    Z = (X - mu) / sd
    t = (np.array([targets[k] for k in ids], dtype=float) - mu) / sd
    dist = np.sqrt(((Z - t) ** 2).mean(axis=1))
    mask = _filter_mask(ds, country, region) & complete
    order = np.argsort(np.where(mask, dist, np.inf))
    return [
        {"code": ds.seats[j]["code"], "name": ds.seats[j]["name"], "distance": round(float(dist[j]), 4),
         "values": {k: float(X[j, n]) for n, k in enumerate(ids)}}
        for j in order[:top_n] if mask[j]
    ]


def kmeans(Z: np.ndarray, k: int, seed: int = 7, iters: int = 100) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic k-means with k-means++ initialisation."""
    rng = np.random.default_rng(seed)
    n = len(Z)
    centres = [Z[rng.integers(n)]]
    for _ in range(1, k):
        d2 = np.min([((Z - c) ** 2).sum(axis=1) for c in centres], axis=0)
        centres.append(Z[rng.choice(n, p=d2 / d2.sum())])
    C = np.array(centres)
    labels = np.zeros(n, dtype=int)
    for _ in range(iters):
        d = ((Z[:, None, :] - C[None, :, :]) ** 2).sum(axis=2)
        new = d.argmin(axis=1)
        if _ > 0 and (new == labels).all():
            break
        labels = new
        for j in range(k):
            if (labels == j).any():
                C[j] = Z[labels == j].mean(axis=0)
    return labels, C


def peer_groups(ds: Dataset, k: int = 8, metric_ids: list[str] | None = None) -> tuple[list[int | None], list[dict]]:
    """Cluster seats into ``k`` peer groups on their census profile.

    Each group is described by the metrics where its centre deviates most from
    the national mean, e.g. "High: Private rented, Aged 20-34 · Low: Owned outright".
    """
    metric_ids = metric_ids or ds.default_profile_metrics()
    X = ds.matrix(metric_ids)
    complete = ~np.isnan(X).any(axis=1)
    if complete.sum() < k:
        return [None] * len(ds.seats), []
    Z, _, _ = zscore(X[complete])
    labels, C = kmeans(Z, k)
    # Order groups by size (largest first) for stable, readable ids.
    sizes = np.bincount(labels, minlength=k)
    order = np.argsort(-sizes, kind="stable")
    remap = {old: new for new, old in enumerate(order)}
    groups = []
    label_by_name = {m["id"]: m["label"] for m in ds.metrics}
    for new, old in enumerate(order):
        c = C[old]
        hi = [metric_ids[i] for i in np.argsort(-c)[:3] if c[i] > 0.5]
        lo = [metric_ids[i] for i in np.argsort(c)[:2] if c[i] < -0.5]
        parts = []
        if hi:
            parts.append("above average on " + ", ".join(label_by_name[m] for m in hi))
        if lo:
            parts.append("below average on " + ", ".join(label_by_name[m] for m in lo))
        groups.append({
            "id": new,
            "label": f"Group {chr(65 + new)}",
            "description": "; ".join(parts) or "Close to the national profile",
            "size": int(sizes[old]),
            "high": hi,
            "low": lo,
        })
    out: list[int | None] = [None] * len(ds.seats)
    idx = np.flatnonzero(complete)
    for j, lab in zip(idx, labels):
        out[j] = remap[int(lab)]
    return out, groups
