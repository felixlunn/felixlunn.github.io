/** Reading uploaded FOI responses: CSV or Excel into a plain table, and messy cell values into numbers. */

export interface Table { headers: string[]; rows: string[][]; sheet?: string; sheets?: string[] }

/** RFC 4180 CSV, tolerant of a BOM, CRLF, and ; or tab separators. */
export function parseCsv(text: string): string[][] {
  const t = text.replace(/^﻿/, "");
  const firstLine = t.slice(0, t.search(/\r?\n|$/));
  const counts = [",", ";", "\t"].map((d) => [d, firstLine.split(d).length] as const);
  const delim = counts.sort((a, b) => b[1] - a[1])[0][0];
  const rows: string[][] = [];
  let row: string[] = [], cell = "", quoted = false;
  for (let i = 0; i < t.length; i++) {
    const c = t[i];
    if (quoted) {
      if (c === '"') {
        if (t[i + 1] === '"') { cell += '"'; i++; } else quoted = false;
      } else cell += c;
    } else if (c === '"' && cell === "") quoted = true;
    else if (c === delim) { row.push(cell); cell = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && t[i + 1] === "\n") i++;
      row.push(cell); rows.push(row); row = []; cell = "";
    } else cell += c;
  }
  if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
  return rows.map((r) => r.map((c) => c.trim()));
}

/**
 * FOI spreadsheets often start with a title, a reference and blank lines. The header is taken as the first row
 * with at least two filled cells that is followed by a row of the same shape.
 */
export function toTable(grid: string[][]): Table {
  const filled = (r: string[]) => r.filter((c) => c !== "").length;
  const rows = grid.filter((r) => filled(r) > 0);
  let h = rows.findIndex((r, i) => filled(r) >= 2 && rows[i + 1] && filled(rows[i + 1]) >= 2);
  if (h < 0) h = 0;
  const width = Math.max(0, ...rows.slice(h).map((r) => r.length));
  const pad = (r: string[]) => Array.from({ length: width }, (_, k) => r[k] ?? "");
  const headers = pad(rows[h] ?? []).map((c, k) => c || `Column ${k + 1}`);
  return { headers, rows: rows.slice(h + 1).map(pad) };
}

export async function readFile(file: File, sheet?: string): Promise<Table> {
  if (/\.(xlsx|xlsm|xls|ods)$/i.test(file.name)) {
    const XLSX = await import("xlsx");
    const wb = XLSX.read(await file.arrayBuffer(), { type: "array", cellDates: true });
    const name = sheet && wb.SheetNames.includes(sheet) ? sheet : wb.SheetNames[0];
    const grid = XLSX.utils.sheet_to_json<unknown[]>(wb.Sheets[name], { header: 1, raw: false, defval: "" })
      .map((r) => r.map((c) => String(c ?? "").trim()));
    return { ...toTable(grid), sheet: name, sheets: wb.SheetNames };
  }
  return toTable(parseCsv(await file.text()));
}

export type Parsed = { value: number | null; suppressed?: string };

const BLANK = /^(|-|–|—|n\/?a|not applicable|\.\.|:|none recorded|not held|no data)$/i;
const SUPPRESSED = /^(\*+|x|c|~|<\s*\d+(\.\d+)?|≤\s*\d+|less than \d+|fewer than \d+|\d+\s*-\s*\d+|redacted|suppressed|withheld)$/i;

/** "1,234" -> 1234, "£5.2m" -> 5200000, "12%" -> 12, "(3)" -> -3, "<5" -> withheld, "n/a" -> blank. */
export function parseValue(raw: string): Parsed {
  const s = raw.trim();
  if (BLANK.test(s)) return { value: null };
  if (SUPPRESSED.test(s)) return { value: null, suppressed: s };
  if (/^nil$/i.test(s)) return { value: 0 };
  let t = s.replace(/[£$€,\s%]/g, "");
  let neg = false;
  if (/^\(.*\)$/.test(t)) { neg = true; t = t.slice(1, -1); }
  let mult = 1;
  const m = t.match(/^(-?[\d.]+)(k|m|bn|b)$/i);
  if (m) { t = m[1]; mult = { k: 1e3, m: 1e6, bn: 1e9, b: 1e9 }[m[2].toLowerCase() as "k"]; }
  if (!/^-?(\d+\.?\d*|\.\d+)(e-?\d+)?$/i.test(t)) return { value: null };
  const v = Number(t) * mult;
  return { value: Number.isFinite(v) ? (neg ? -v : v) : null };
}

/** Share of a column's non-blank cells that read as numbers (or withheld numbers): used to suggest value columns. */
export function numericShare(rows: string[][], col: number): number {
  const cells = rows.map((r) => r[col] ?? "").filter((c) => c.trim() !== "");
  if (!cells.length) return 0;
  return cells.filter((c) => { const p = parseValue(c); return p.value !== null || !!p.suppressed; }).length / cells.length;
}
