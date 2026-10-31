/**
 * Browser port of whips/engine.py. Runs in well under a millisecond for ~650
 * seats, so every slider move recomputes exactly (no approximate index needed).
 */
import type { DashboardData, Metric } from "../types";

export type Vec = (number | null)[];

export interface RankInfo {
  value: number | null;
  rank: number | null;
  of: number;
  percentile: number | null;
}

export function rankOf(values: Vec, i: number): RankInfo {
  const x = values[i];
  const valid = values.filter((v): v is number => v !== null);
  if (x === null || x === undefined) return { value: null, rank: null, of: valid.length, percentile: null };
  let above = 0, below = 0, equal = 0;
  for (const v of valid) {
    if (v > x) above++;
    else if (v < x) below++;
    else equal++;
  }
  const pct = ((below + 0.5 * (equal - 1)) / Math.max(valid.length - 1, 1)) * 100;
  return { value: x, rank: above + 1, of: valid.length, percentile: Math.round(pct * 10) / 10 };
}

export interface Stats {
  mean: number;
  sd: number;
  min: number;
  max: number;
}

export function stats(values: Vec, mask?: boolean[]): Stats {
  let n = 0, sum = 0, sq = 0, min = Infinity, max = -Infinity;
  values.forEach((v, i) => {
    if (v === null || (mask && !mask[i])) return;
    n++;
    sum += v;
    sq += v * v;
    if (v < min) min = v;
    if (v > max) max = v;
  });
  const mean = n ? sum / n : NaN;
  const variance = n ? sq / n - mean * mean : NaN;
  const sd = Math.sqrt(Math.max(variance, 0)) || 1;
  return { mean, sd, min, max };
}

/** Rows (seats) that have a value for every metric id. */
export function completeMask(data: DashboardData, ids: string[]): boolean[] {
  return data.seats.map((_, i) => ids.every((id) => data.values[id]?.[i] != null));
}

/** Standardised matrix (rows = seats) over complete rows; incomplete rows are null. */
export function zMatrix(data: DashboardData, ids: string[]): { Z: (Float64Array | null)[]; stats: Stats[]; mask: boolean[] } {
  const mask = completeMask(data, ids);
  const st = ids.map((id) => stats(data.values[id], mask));
  const Z = data.seats.map((_, i) => {
    if (!mask[i]) return null;
    const row = new Float64Array(ids.length);
    ids.forEach((id, k) => {
      row[k] = ((data.values[id][i] as number) - st[k].mean) / st[k].sd;
    });
    return row;
  });
  return { Z, stats: st, mask };
}

export interface Filter {
  country?: string;
  region?: string;
}

function passes(data: DashboardData, i: number, f: Filter): boolean {
  const s = data.seats[i];
  return (!f.country || s.country === f.country) && (!f.region || s.region === f.region);
}

export interface Scored {
  index: number;
  code: string;
  name: string;
  score: number;
}

/**
 * Similarity of every seat to seat `target` (1 = identical). Euclidean compares
 * levels in SD units; cosine compares the shape of the profile around the mean.
 */
export function similarity(data: DashboardData, target: number, ids: string[], method: "euclidean" | "cosine"): (number | null)[] {
  const { Z } = zMatrix(data, ids);
  const t = Z[target];
  if (!t) return data.seats.map(() => null);
  const tn = Math.hypot(...t) || 1;
  return Z.map((row) => {
    if (!row) return null;
    if (method === "cosine") {
      let dot = 0;
      for (let k = 0; k < t.length; k++) dot += row[k] * t[k];
      const rn = Math.hypot(...row) || 1;
      return dot / (rn * tn);
    }
    let d = 0;
    for (let k = 0; k < t.length; k++) d += (row[k] - t[k]) ** 2;
    return 1 / (1 + Math.sqrt(d / t.length));
  });
}

export function topN(data: DashboardData, scores: (number | null)[], n: number, opts: { exclude?: number; filter?: Filter; ascending?: boolean } = {}): Scored[] {
  const items: Scored[] = [];
  scores.forEach((s, i) => {
    if (s === null || i === opts.exclude || !passes(data, i, opts.filter ?? {})) return;
    items.push({ index: i, code: data.seats[i].code, name: data.seats[i].name, score: s });
  });
  items.sort((a, b) => (opts.ascending ? a.score - b.score : b.score - a.score));
  return items.slice(0, n);
}

/** Weighted mean of z-scores. Negative weights invert a metric. Null where any weighted metric is missing. */
export function compositeIndex(data: DashboardData, weights: Record<string, number>): (number | null)[] {
  const ids = Object.keys(weights).filter((k) => weights[k] !== 0 && data.values[k]);
  if (!ids.length) return data.seats.map(() => null);
  const { Z } = zMatrix(data, ids);
  const total = ids.reduce((a, k) => a + Math.abs(weights[k]), 0);
  return Z.map((row) => (row ? ids.reduce((a, k, j) => a + row[j] * weights[k], 0) / total : null));
}

/** RMS distance (in SD units) from each seat to a target profile. Lower is closer. */
export function profileDistance(data: DashboardData, targets: Record<string, number>): (number | null)[] {
  const ids = Object.keys(targets).filter((k) => data.values[k]);
  if (!ids.length) return data.seats.map(() => null);
  const { Z, stats: st } = zMatrix(data, ids);
  const t = ids.map((k, j) => (targets[k] - st[j].mean) / st[j].sd);
  return Z.map((row) => (row ? Math.sqrt(ids.reduce((a, _k, j) => a + (row[j] - t[j]) ** 2, 0) / ids.length) : null));
}

/** Census percentage metrics: the default "demographic DNA" for twins. */
export function profileMetrics(metrics: Metric[], themes?: string[]): string[] {
  return metrics
    .filter((m) => m.unit === "%" && (themes ? themes.includes(m.theme) : m.tags.includes("census")))
    .map((m) => m.id);
}

/** Standard score of seat i on a metric (null if missing). */
export function zOf(values: Vec, i: number): number | null {
  const x = values[i];
  if (x === null) return null;
  const s = stats(values);
  return (x - s.mean) / s.sd;
}

/** Mean of a metric across seats in a peer group. */
export function groupMean(data: DashboardData, metricId: string, group: number | null): number | null {
  if (group === null) return null;
  let n = 0, sum = 0;
  data.seats.forEach((s, i) => {
    const v = data.values[metricId][i];
    if (s.peer_group === group && v !== null) {
      n++;
      sum += v;
    }
  });
  return n ? sum / n : null;
}
