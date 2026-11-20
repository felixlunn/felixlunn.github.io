/** Descriptive statistics and outlier detection for an FOI column. */

export interface Describe {
  n: number;
  total: number;
  mean: number | null;
  median: number | null;
  sd: number | null;
  q1: number | null;
  q3: number | null;
  min: number | null;
  max: number | null;
  /** Values outside these are outliers (Tukey's fences, 1.5 × the interquartile range beyond the quartiles). */
  low: number | null;
  high: number | null;
}

/** Linear-interpolated quantile of sorted values (the same method as Excel's QUARTILE.INC). */
export function quantile(sorted: number[], q: number): number | null {
  if (!sorted.length) return null;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos), hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

/** Fewer values than this and outliers aren't flagged: there's too little to judge what's unusual. */
export const MIN_FOR_OUTLIERS = 8;

export function describe(values: (number | null)[]): Describe {
  const v = values.filter((x): x is number => x !== null && Number.isFinite(x)).sort((a, b) => a - b);
  const n = v.length;
  const total = v.reduce((a, b) => a + b, 0);
  const mean = n ? total / n : null;
  const sd = n > 1 ? Math.sqrt(v.reduce((a, x) => a + (x - mean!) ** 2, 0) / (n - 1)) : null;
  const q1 = quantile(v, 0.25), q3 = quantile(v, 0.75);
  const iqr = q1 !== null && q3 !== null ? q3 - q1 : null;
  const fences = n >= MIN_FOR_OUTLIERS && iqr !== null && iqr > 0;
  return {
    n, total, mean, sd, q1, q3, median: quantile(v, 0.5), min: v[0] ?? null, max: v[n - 1] ?? null,
    low: fences ? q1! - 1.5 * iqr! : null, high: fences ? q3! + 1.5 * iqr! : null,
  };
}

export type Outlier = "high" | "low" | null;

export function outlier(v: number | null, d: Describe): Outlier {
  if (v === null) return null;
  if (d.high !== null && v > d.high) return "high";
  if (d.low !== null && v < d.low) return "low";
  return null;
}

/** "2.3× the median", "40% below the median": how far a value sits from the middle. */
export function vsMedian(v: number, median: number | null): string | null {
  if (median === null || median === 0) return null;
  const r = v / median;
  if (r >= 1.5) return `${r.toFixed(r >= 10 ? 0 : 1)}× the median`;
  const pct = Math.round((r - 1) * 100);
  if (pct === 0) return "at the median";
  return `${Math.abs(pct)}% ${pct > 0 ? "above" : "below"} the median`;
}
