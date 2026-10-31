import type { Metric } from "../types";

const nf = new Intl.NumberFormat("en-GB");

export function fmt(m: Pick<Metric, "unit" | "decimals">, v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const d = m.decimals ?? 1;
  const n = new Intl.NumberFormat("en-GB", { minimumFractionDigits: d, maximumFractionDigits: d }).format(v);
  if (m.unit === "%") return `${n}%`;
  return n;
}

export function unitSuffix(m: Metric): string {
  if (m.unit === "%") return "";
  if (m.unit === "people" || m.label.includes(m.unit)) return "";
  return ` ${m.unit}`;
}

export function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return nf.format(n) + (s[(v - 20) % 10] || s[v] || s[0]);
}

export function int(n: number): string {
  return nf.format(Math.round(n));
}

/** Plain-English rank: "42nd highest of 575". Uses "lowest" when that reads better. */
export function rankText(rank: number | null, of: number): string {
  if (rank === null) return "No data";
  if (rank > of / 2) return `${ordinal(of - rank + 1)} lowest of ${int(of)}`;
  return `${ordinal(rank)} highest of ${int(of)}`;
}

export function csv(rows: (string | number | null | undefined)[][]): string {
  return rows
    .map((r) =>
      r
        .map((c) => {
          const s = c === null || c === undefined ? "" : String(c);
          return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
        })
        .join(","),
    )
    .join("\n");
}

export function download(filename: string, text: string, type = "text/csv;charset=utf-8") {
  const blob = new Blob([text], { type });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

export function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}
