/**
 * Map keys people set themselves: their own band boundaries (e.g. just "50", to split a % change map into rises
 * of 50% or more and the rest), remembered per dataset and figure in this browser.
 */

import { classify } from "../lib/colors";

export interface Band {
  /** The colour class (as classify() numbers them: 0 is the lowest band). */
  k: number;
  label: string;
}

/** A number as people type it: "50", "+50%", "£1,200", "−3.5". null when it isn't one. */
export function parseNumber(raw: string): number | null {
  const s = raw.trim().replace(/[£%,\s]/g, "").replace(/^\+/, "").replace(/^[−–]/, "-");
  if (!/^-?(\d+\.?\d*|\.\d+)$/.test(s)) return null;
  const v = Number(s);
  return Number.isFinite(v) ? v : null;
}

/** Boundaries as typed, made usable: numbers only, no repeats, lowest first. */
export function cleanBreaks(raw: string[]): number[] {
  return [...new Set(raw.map(parseNumber).filter((v): v is number => v !== null))].sort((a, b) => a - b);
}

/** The bands a set of boundaries makes, highest first (as the key lists them). A value on a boundary goes in the band above. */
export function bands(breaks: number[], fmt: (v: number) => string): Band[] {
  const out: Band[] = [];
  for (let k = breaks.length; k >= 0; k--) {
    const lo = k > 0 ? breaks[k - 1] : null, hi = k < breaks.length ? breaks[k] : null;
    const label = lo === null ? `Under ${fmt(hi!)}` : hi === null ? `${fmt(lo)} or more` : `${fmt(lo)} to under ${fmt(hi)}`;
    out.push({ k, label });
  }
  return out;
}

/** How many values fall in each band (by class number). */
export function bandCounts(values: (number | null)[], breaks: number[]): number[] {
  const n = new Array(breaks.length + 1).fill(0);
  for (const v of values) if (v !== null) n[classify(v, breaks)]++;
  return n;
}

const STORE = "foi.keys";

/** Saved keys: "<dataset id>|<figure>" -> boundaries. Browser storage only; a blocked store just forgets. */
export function loadKeys(): Record<string, number[]> {
  try {
    const o = JSON.parse(localStorage.getItem(STORE) || "{}") as Record<string, unknown>;
    return Object.fromEntries(Object.entries(o).filter(([, v]) => Array.isArray(v) && v.every((x) => typeof x === "number"))) as Record<string, number[]>;
  } catch {
    return {};
  }
}

export function saveKeys(keys: Record<string, number[]>): void {
  try { localStorage.setItem(STORE, JSON.stringify(keys)); } catch { /* kept for this visit only */ }
}
