"""Constituency analytics engine: the dataset model, ranks, and the peer groups the pipeline assigns.

Plain NumPy: with ~650 constituencies everything here takes well under a millisecond.
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
