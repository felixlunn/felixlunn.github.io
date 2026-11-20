/**
 * Ranks, summary statistics and peer-group averages for the seat briefing and Themes tab.
 */
import type { DashboardData } from "../types";

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
