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
    if (c.period && !c.change && !c.derived) groups.set(c.series ?? "", [...(groups.get(c.series ?? "") ?? []), c]);
  }
  return [...groups].filter(([, cs]) => new Set(cs.map((c) => c.period)).size >= 2)
    .map(([series, cs]) => ({ series, cols: [...cs].sort((a, b) => (parsePeriod(a.period!)?.key ?? 0) - (parsePeriod(b.period!)?.key ?? 0)) }));
}

export function changeValue(from: Cell, to: Cell, mode: "percent" | "absolute"): Cell {
  if (from === null || to === null) return null;
  if (mode === "absolute") return to - from;
  return from === 0 ? null : ((to - from) / Math.abs(from)) * 100;
}

export interface YearView {
  /** The measure (e.g. "Officers"); "" when the response has a single measure in year columns. */
  series: string;
  years: Column[];
  average: Column;
  change: Column;
}

/**
 * Multi-year responses: for each measure with two or more years, add (in the browser, not saved) its average per
 * year and its % change from the first year to the last. Returns the dataset with these columns, and the views.
 */
export function withYearViews(d: Dataset): { d: Dataset; views: YearView[] } {
  const views: YearView[] = [];
  const columns = [...d.columns];
  const extra: Record<string, Record<string, Cell>> = {};
  for (const { series, cols } of timeSeries(d.columns)) {
    const first = cols[0], last = cols[cols.length - 1];
    const name = series ? `${series}: ` : "";
    const average: Column = { key: `avg:${series}`, label: `${name}average per year`, unit: first.unit, direction: first.direction, series, derived: "average" };
    const change: Column = {
      key: `chg:${series}`, label: `${name}% change ${first.period} to ${last.period}`, unit: "percent", direction: first.direction, series,
      derived: "change", change: { from: first.period!, to: last.period!, mode: "percent" },
    };
    for (const r of d.rows) {
      const vals = cols.map((c) => r.values[c.key] ?? null).filter((v): v is number => v !== null);
      extra[r.code] = {
        ...extra[r.code],
        [average.key]: vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null,
        [change.key]: changeValue(r.values[first.key] ?? null, r.values[last.key] ?? null, "percent"),
      };
    }
    columns.push(average, change);
    views.push({ series, years: cols, average, change });
  }
  if (!views.length) return { d, views };
  return { d: { ...d, columns, rows: d.rows.map((r) => ({ ...r, values: { ...r.values, ...extra[r.code] } })) }, views };
}
