/**
 * Area view: every dataset's headline figure for one trust, ICB, force, court or criminal justice area,
 * and an overview of which organisations most often fall in the worse half.
 */

import { ranked, summary, type Ranked } from "./analysis";
import { targets } from "./match";
import { withYearViews, type YearView } from "./periods";
import { GEO } from "./geographies";
import type { Column, Dataset, Geography, Reference, Target } from "./types";

/** A dataset's headline: the % change when it covers several years, otherwise its first figure. */
export interface Headline {
  d: Dataset;
  col: Column;
  view: YearView | null;
  stats: ReturnType<typeof summary>;
  byCode: Map<string, Ranked>;
  /** The dataset's rows by code (for year values). */
  rowsByCode: Map<string, Dataset["rows"][number]>;
  values: number[];
}

export function headline(ref: Reference, saved: Dataset): Headline | null {
  const { d, views } = withYearViews(saved);
  const view = views[0] ?? null;
  const candidates = view ? [view.change, view.years[view.years.length - 1]] : d.columns.slice(0, 1);
  for (const col of candidates) {
    const rows = ranked(ref, d, col.key, false);
    const values = rows.map((r) => r.value).filter((v): v is number => v !== null);
    if (values.length) {
      return { d, col, view, stats: summary(rows), byCode: new Map(rows.map((r) => [r.target.code, r])), rowsByCode: new Map(d.rows.map((r) => [r.code, r])), values };
    }
  }
  return null;
}

/** Is this value in the worse half (worse than the median)? null when the figure has no "better" direction. */
export function worseHalf(h: Headline, v: number | null): boolean | null {
  if (v === null || h.stats.median === null || h.col.direction === "neutral") return null;
  return h.col.direction === "higher_better" ? v < h.stats.median : v > h.stats.median;
}

/** The parent organisation's code: a trust's NHS area, a court's criminal justice (police force) area. */
const parents = new WeakMap<Reference, Map<string, string | null>>();

export function parentOf(ref: Reference, g: Geography, code: string): string | null {
  if (g !== "nhs_trust" && g !== "court") return null;
  // Built once per reference file: trust and court codes are distinct, so one map serves both.
  let m = parents.get(ref);
  if (!m) {
    m = new Map<string, string | null>([
      ...(ref.points.trusts ?? []).map((t) => [t.code, t.area] as [string, string | null]),
      ...(ref.points.courts ?? []).map((c) => [c.id, c.area] as [string, string | null]),
    ]);
    parents.set(ref, m);
  }
  return m.get(code) ?? null;
}

export interface Score { worse: number; of: number }

/** For each organisation of a kind: in how many of its datasets it's in the worse half. */
export function scores(heads: Headline[], g: Geography): Map<string, Score> {
  const out = new Map<string, Score>();
  for (const h of heads) {
    if (h.d.geography !== g) continue;
    for (const [code, r] of h.byCode) {
      const w = worseHalf(h, r.value);
      if (w === null) continue;
      const s = out.get(code) ?? { worse: 0, of: 0 };
      s.of++;
      if (w) s.worse++;
      out.set(code, s);
    }
  }
  return out;
}

/** The organisations to list for a kind: every area, or the trusts / courts that appear in any dataset. */
export function orgList(ref: Reference, heads: Headline[], g: Geography): Target[] {
  const all = targets(ref, g);
  if (GEO[g].isArea) return all;
  const seen = new Set(heads.filter((h) => h.d.geography === g).flatMap((h) => [...h.byCode.keys()]));
  return all.filter((t) => seen.has(t.code));
}
