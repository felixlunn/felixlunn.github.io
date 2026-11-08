import { useEffect, useState } from "react";
import type { Metric } from "../types";
import { dataUrl } from "./dataUrl";
import { fmt } from "./format";

/** history.json: past periods for metrics whose source publishes them. */
export interface History {
  metrics: Record<string, { periods: string[]; national: (number | null)[]; values: (number | null)[][] }>;
}

let cached: History | null | undefined;
let pending: Promise<History | null> | null = null;

function load(): Promise<History | null> {
  pending ??= fetch(dataUrl("history.json"))
    .then((r) => (r.ok ? (r.json() as Promise<History>) : null))
    .catch(() => null)
    .then((h) => (cached = h));
  return pending;
}

/** The history file, loaded once when first needed (null until loaded, or if this deploy has none). */
export function useHistory(enabled = true): History | null {
  const [h, setH] = useState<History | null>(cached ?? null);
  useEffect(() => {
    if (!enabled) return;
    if (cached !== undefined) { setH(cached); return; }
    let live = true;
    load().then((x) => live && setH(x));
    return () => { live = false; };
  }, [enabled]);
  return h;
}

export interface Point { period: string; value: number }
export interface Series { seat: Point[]; national: Point[] }

/** A seat's points (and the national figure's) for a metric, oldest first; null with fewer than two seat points. */
export function seriesFor(h: History | null, metricId: string, seat: number): Series | null {
  const m = h?.metrics[metricId];
  if (!m) return null;
  const seatPts = m.periods.map((p, k) => ({ period: p, value: m.values[k]?.[seat] ?? null }))
    .filter((x): x is Point => x.value !== null && Number.isFinite(x.value));
  if (seatPts.length < 2) return null;
  const national = m.periods.map((p, k) => ({ period: p, value: m.national[k] }))
    .filter((x): x is Point => x.value !== null && Number.isFinite(x.value));
  return { seat: seatPts, national };
}

export interface Change { from: Point; to: Point; delta: number; text: string; dir: "up" | "down" | "flat"; tone: "good" | "bad" | "neutral" }

/** How a figure moved between two points: percentage points for % figures, otherwise percent change. */
export function change(m: Metric, from: Point, to: Point): Change {
  const delta = to.value - from.value;
  let text: string;
  let size: number;
  if (m.unit === "%") {
    size = Math.abs(delta);
    text = `${size.toFixed(size < 10 ? 1 : 0)} pts`;
  } else if (from.value !== 0) {
    size = Math.abs(delta / from.value) * 100;
    text = `${size.toFixed(size < 10 ? 1 : 0)}%`;
  } else {
    size = Math.abs(delta);
    text = fmt(m, size);
  }
  const flat = size < (m.unit === "%" ? 0.05 : 0.5);
  const dir = flat ? "flat" : delta > 0 ? "up" : "down";
  const tone = flat || m.polarity === "neutral" ? "neutral"
    : (dir === "up") === (m.polarity === "higher_better") ? "good" : "bad";
  return { from, to, delta, text, dir, tone };
}

/** Change since the previous period, and since the first. */
export function changes(m: Metric, s: Series): { last: Change; since: Change } {
  const pts = s.seat;
  return { last: change(m, pts[pts.length - 2], pts[pts.length - 1]), since: change(m, pts[0], pts[pts.length - 1]) };
}

const verb = (c: Change) => (c.dir === "up" ? "rose" : c.dir === "down" ? "fell" : "was unchanged");

/** A sentence offices can quote, with the national comparison and source. */
export function quote(m: Metric, seatName: string, s: Series): string {
  const c = change(m, s.seat[0], s.seat[s.seat.length - 1]);
  const body = c.dir === "flat"
    ? `${m.label} in ${seatName} was ${fmt(m, c.to.value)} in ${c.to.period}, unchanged from ${c.from.period}`
    : `${m.label} in ${seatName} ${verb(c)} from ${fmt(m, c.from.value)} in ${c.from.period} to ${fmt(m, c.to.value)} in ${c.to.period}`;
  const n0 = s.national.find((p) => p.period === c.from.period);
  const n1 = s.national.find((p) => p.period === c.to.period);
  const nat = n0 && n1 ? `; national figure ${fmt(m, n0.value)} to ${fmt(m, n1.value)}` : "";
  return `${body}${nat} (${m.source}).`;
}

/** The number behind a change: percentage points for % figures, otherwise percent change. */
export function changeValue(m: Metric, from: number, to: number): number | null {
  if (m.unit === "%") return to - from;
  return from !== 0 ? ((to - from) / Math.abs(from)) * 100 : null;
}

export function formatChange(m: Metric, v: number): string {
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  const a = Math.abs(v);
  return `${sign}${a.toFixed(a < 10 ? 1 : 0)}${m.unit === "%" ? " pts" : "%"}`;
}

/** Every seat's change between the metric's first and latest periods (for the map); null where either is missing. */
export function mapChange(h: History | null, m: Metric): { from: string; to: string; values: (number | null)[] } | null {
  const hm = h?.metrics[m.id];
  if (!hm || hm.periods.length < 2) return null;
  const a = 0, b = hm.periods.length - 1;
  const values = hm.values[b].map((to, i) => {
    const from = hm.values[a][i];
    return to === null || from === null ? null : changeValue(m, from, to);
  });
  return { from: hm.periods[a], to: hm.periods[b], values };
}
