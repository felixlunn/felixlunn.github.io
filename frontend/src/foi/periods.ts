/** Years and periods in FOI responses: spotting them, ordering them, and calculating change between them. */

import type { Cell, Column, Dataset } from "./types";

export interface Period { label: string; /** Sortable: start year, plus a fraction for quarters / months. */ key: number }

const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];

/**
 * A year or period in a header or cell: "2023", "2023/24", "2023-2024", "FY 2023/24", "2023 Q2", "Q2 2023", "Mar 2024".
 * Returns null for anything else (including bare numbers outside 1990-2049, so figures aren't mistaken for years).
 */
export function parsePeriod(raw: string): Period | null {
  const s = raw.trim();
  if (!s || s.length > 40) return null;
  const y = s.match(/\b((?:19|20)\d{2})(?:\s*[/\-–]\s*((?:19|20)?\d{2}))?\b/);
  if (!y) return null;
  const start = Number(y[1]);
  if (start < 1990 || start > 2049) return null;
  const q = s.match(/\bQ([1-4])\b/i);
  const m = MONTHS.findIndex((mo) => new RegExp(`\\b${mo}[a-z]*\\b`, "i").test(s));
  if (y[2]) {
    const end = y[2].length === 2 ? Number(String(start).slice(0, 2) + y[2]) : Number(y[2]);
    if (end !== start + 1) return null;
    return { label: `${start}/${String(end).slice(2)}${q ? ` Q${q[1]}` : ""}`, key: start + (q ? Number(q[1]) / 5 : 0.5) };
  }
  if (q) return { label: `${start} Q${q[1]}`, key: start + Number(q[1]) / 5 };
  if (m >= 0) return { label: `${MONTHS[m][0].toUpperCase()}${MONTHS[m].slice(1)} ${start}`, key: start + (m + 1) / 13 };
  return { label: String(start), key: start };
}

/** The measure name once the period is removed: "Officers 2023/24" -> "Officers"; "2023" -> "". */
export function seriesName(header: string): string {
  return header.replace(/\b(FY|financial year|year ending|YE|calendar year)\b/gi, " ")
    .replace(/\b(?:Q[1-4]|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b/gi, " ")
    .replace(/\b(?:19|20)\d{2}(?:\s*[/\-–]\s*(?:(?:19|20)?\d{2}))?\b/g, " ")
    .replace(/[()[\]:,]+/g, " ").replace(/\s+/g, " ").trim().replace(/^[-–]\s*|\s*[-–]$/g, "");
}

/** Columns grouped into time series (two or more periods of the same measure), each in period order. */
export function timeSeries(columns: Column[]): { series: string; cols: Column[] }[] {
  const groups = new Map<string, Column[]>();
  for (const c of columns) {
    if (c.period && !c.change) groups.set(c.series ?? "", [...(groups.get(c.series ?? "") ?? []), c]);
  }
  return [...groups].filter(([, cs]) => new Set(cs.map((c) => c.period)).size >= 2)
    .map(([series, cs]) => ({ series, cols: [...cs].sort((a, b) => (parsePeriod(a.period!)?.key ?? 0) - (parsePeriod(b.period!)?.key ?? 0)) }));
}

export function changeValue(from: Cell, to: Cell, mode: "percent" | "absolute"): Cell {
  if (from === null || to === null) return null;
  if (mode === "absolute") return to - from;
  return from === 0 ? null : ((to - from) / Math.abs(from)) * 100;
}

/**
 * Add a change column to a dataset: values for each area from ``from`` to ``to``. Each side is a column of this
 * dataset, or of another dataset of the same geography (matched by area code).
 */
export function addChange(d: Dataset, from: { d: Dataset; col: Column }, to: { d: Dataset; col: Column }, mode: "percent" | "absolute"): Dataset {
  const fromLabel = from.col.period ?? (from.d.id === d.id ? from.col.label : from.d.period ?? from.d.title);
  const toLabel = to.col.period ?? (to.d.id === d.id ? to.col.label : to.d.period ?? to.d.title);
  const measure = to.col.series ?? from.col.series ?? to.col.label;
  const key = `chg${d.columns.filter((c) => c.change).length + 1}_${Date.now().toString(36)}`;
  const fv = new Map(from.d.rows.map((r) => [r.code, r.values[from.col.key] ?? null]));
  const tv = new Map(to.d.rows.map((r) => [r.code, r.values[to.col.key] ?? null]));
  const col: Column = {
    key, unit: mode === "percent" ? "percent" : to.col.unit === "percent" ? "rate" : to.col.unit, direction: to.col.direction,
    label: `${measure ? `${measure}: ` : ""}${mode === "percent" ? "% change" : "change"} ${fromLabel} to ${toLabel}`,
    change: { from: fromLabel, to: toLabel, mode },
  };
  // Areas in the other dataset but not this one are added, so a change covers everyone with both figures.
  const codes = new Set([...d.rows.map((r) => r.code), ...fv.keys(), ...tv.keys()]);
  const byCode = new Map(d.rows.map((r) => [r.code, r]));
  const rows = [...codes].map((code) => {
    const r = byCode.get(code) ?? { code, source_name: "", values: {} };
    return { ...r, values: { ...r.values, [key]: changeValue(fv.get(code) ?? null, tv.get(code) ?? null, mode) } };
  });
  return { ...d, columns: [...d.columns, col], rows };
}

/** On upload: for every time series, the % change from its first to its last period. */
export function autoChanges(d: Dataset): Dataset {
  let out = d;
  for (const { cols } of timeSeries(d.columns)) {
    out = addChange(out, { d: out, col: cols[0] }, { d: out, col: cols[cols.length - 1] }, "percent");
  }
  return out;
}
