/**
 * Area view: every dataset's headline figure for one trust, ICB, force, court or criminal justice area,
 * and an overview of which organisations most often fall in the worse half.
 */

import { fmtValue, ranked, seatsServed, summary, type Ranked } from "./analysis";
import { targets } from "./match";
import { withYearViews, type YearView } from "./periods";
import { GEO } from "./geographies";
import type { Column, Dataset, DatasetSummary, Geography, NewDataset, Reference, Target } from "./types";

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

/** What's saved with a dataset at upload: its size and headline figure, so the list needn't load the rows. */
export function summarise(ref: Reference, d: NewDataset): DatasetSummary {
  const h = headline(ref, { ...d, id: "", created_by: null, created_by_email: "", created_at: "", updated_at: "" });
  return {
    rows: d.rows.length,
    unmatched: d.unmatched.length,
    headline: h ? { col: h.col, median: h.stats.median, n: h.stats.n } : null,
  };
}

/** The saved headline in words, e.g. "Median 412 · Stop and search" or "Median +3.2% · % change 2019 → 2024". */
export function headlineText(s: DatasetSummary | null): string | null {
  const h = s?.headline;
  if (!h || h.median === null) return null;
  const what = h.col.change ? `% change ${h.col.change.from} → ${h.col.change.to}` : h.col.label;
  return `Median ${fmtValue(h.median, h.col)} · ${what}`;
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

/** Constituency view: for one dataset, the organisations with a figure that serve each seat (seat -> codes). */
const bySeatCache = new WeakMap<Headline, Map<string, string[]>>();

export function servingBySeat(ref: Reference, h: Headline): Map<string, string[]> {
  let out = bySeatCache.get(h);
  if (out) return out;
  out = new Map();
  for (const [code, seats] of seatsServed(ref, h.d.geography, new Set(h.byCode.keys()))) {
    if (!h.byCode.has(code)) continue;
    for (const s of seats) {
      const list = out.get(s);
      if (list) list.push(code); else out.set(s, [code]);
    }
  }
  bySeatCache.set(h, out);
  return out;
}

/** Each seat's record: of the figures for the organisations serving it (one per dataset and organisation), how
 * many are in the worse half. */
export function seatScores(ref: Reference, heads: Headline[]): Map<string, Score> {
  const out = new Map<string, Score>();
  for (const h of heads) {
    for (const [seat, codes] of servingBySeat(ref, h)) {
      for (const code of codes) {
        const w = worseHalf(h, h.byCode.get(code)?.value ?? null);
        if (w === null) continue;
        const sc = out.get(seat) ?? { worse: 0, of: 0 };
        sc.of++;
        if (w) sc.worse++;
        out.set(seat, sc);
      }
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
