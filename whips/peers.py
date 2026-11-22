"""Peer groups: seats clustered on their census profile, shown in each seat's briefing with the group's averages.

Plain NumPy: with ~650 constituencies this takes well under a millisecond.
"""

from __future__ import annotations

import numpy as np


def census_profile(metrics: list[dict]) -> list[str]:
    """Census proportions: the demographic profile seats are grouped on."""
    return [m["id"] for m in metrics if "census" in m.get("tags", []) and m["unit"] == "%"]


def matrix(values: dict[str, list], metric_ids: list[str]) -> np.ndarray:
    """Seats x metrics, with missing values as NaN."""
    return np.column_stack([np.array([np.nan if v is None else float(v) for v in values[m]], dtype=float) for m in metric_ids])


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


def peer_groups(seats: list[dict], metrics: list[dict], values: dict[str, list], k: int = 8,
                metric_ids: list[str] | None = None) -> tuple[list[int | None], list[dict]]:
    """Cluster seats into ``k`` peer groups on their census profile.

    Each group is described by the metrics where its centre deviates most from
    the national mean, e.g. "High: Private rented, Aged 20-34 · Low: Owned outright".
    """
    metric_ids = metric_ids or census_profile(metrics)
    X = matrix(values, metric_ids)
    complete = ~np.isnan(X).any(axis=1)
    if complete.sum() < k:
        return [None] * len(seats), []
    Z, _, _ = zscore(X[complete])
    labels, C = kmeans(Z, k)
    # Order groups by size (largest first) for stable, readable ids.
    sizes = np.bincount(labels, minlength=k)
    order = np.argsort(-sizes, kind="stable")
    remap = {old: new for new, old in enumerate(order)}
    groups = []
    label_by_name = {m["id"]: m["label"] for m in metrics}
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
    out: list[int | None] = [None] * len(seats)
    idx = np.flatnonzero(complete)
    for j, lab in zip(idx, labels):
        out[j] = remap[int(lab)]
    return out, groups
