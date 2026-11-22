/**
 * Checks for the FOI section's data: the reference file the pipeline writes (foi/reference.json), and datasets as
 * they come back from the database. Uploaded datasets are stored as JSON the database doesn't check, so each is
 * cleaned up on load: anything malformed is dropped (and reported in the console) rather than crashing a view.
 */

import { each, field, type Problems } from "../lib/check";
import { DEPARTMENT, GEO } from "./geographies";
import type { Cell, Column, DataRow, Dataset, DatasetSummary } from "./types";

/** The reference.json format this code reads (the pipeline writes "version"; bump both together). */
export const REFERENCE_VERSION = 1;

export function checkReference(r: unknown): Problems {
  const p: Problems = [];
  const o = (r ?? {}) as Record<string, unknown>;
  if (o.version !== REFERENCE_VERSION) p.push(`reference.version: this site reads version ${REFERENCE_VERSION}, the file is version ${String(o.version)}`);
  field(p, o, "layers", ["object"], "reference");
  field(p, o, "points", ["object"], "reference");
  field(p, o, "seats", ["array"], "reference");
  const layers = (o.layers ?? {}) as Record<string, { areas?: unknown }>;
  for (const l of ["police", "health"]) {
    field(p, layers, l, ["object"], "reference.layers");
    each(p, layers[l]?.areas, `layers.${l}.areas`, (a, at) => {
      for (const k of ["code", "name"]) field(p, a, k, ["string"], at);
      for (const k of ["aliases", "seats"]) field(p, a, k, ["array"], at);
      field(p, a, "population", ["number", "null"], at);
    });
  }
  const points = (o.points ?? {}) as Record<string, unknown>;
  each(p, points.courts, "points.courts", (c, at) => {
    for (const k of ["id", "name"]) field(p, c, k, ["string"], at);
    for (const k of ["lat", "lon"]) field(p, c, k, ["number"], at);
  });
  each(p, points.trusts, "points.trusts", (t, at) => {
    for (const k of ["code", "name", "kind"]) field(p, t, k, ["string"], at);
    for (const k of ["lat", "lon"]) field(p, t, k, ["number"], at);
    field(p, t, "catchment", ["array", "undefined"], at);
  });
  each(p, o.seats, "seats", (s, at) => {
    for (const k of ["code", "name"]) field(p, s, k, ["string"], at);
    field(p, s, "ld", ["string", "undefined"], at);
  });
  return p;
}

const UNITS: Column["unit"][] = ["count", "rate", "percent", "money", "other"];
const DIRECTIONS: Column["direction"][] = ["higher_worse", "higher_better", "neutral"];
const str = (v: unknown): string | null => (typeof v === "string" ? v : null);
const num = (v: unknown): Cell => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** A dataset from the database, cleaned up: null if it can't be used at all. ``problems`` collects what was fixed. */
export function normaliseDataset(raw: unknown, problems: Problems = []): Dataset | null {
  const o = (raw ?? {}) as Record<string, unknown>;
  const id = str(o.id), title = str(o.title);
  if (!id || !title || !(String(o.department) in DEPARTMENT) || !(String(o.geography) in GEO)) {
    problems.push(`dataset ${String(o.id)}: missing id, title, department or geography`);
    return null;
  }
  const columns: Column[] = [];
  for (const c of Array.isArray(o.columns) ? o.columns : []) {
    const cc = (c ?? {}) as Record<string, unknown>;
    if (!str(cc.key) || !str(cc.label)) { problems.push(`dataset ${id}: dropped a column without a key or label`); continue; }
    columns.push({
      ...(cc as unknown as Column),
      unit: UNITS.includes(cc.unit as Column["unit"]) ? (cc.unit as Column["unit"]) : "other",
      direction: DIRECTIONS.includes(cc.direction as Column["direction"]) ? (cc.direction as Column["direction"]) : "neutral",
    });
  }
  const rows: DataRow[] = [];
  for (const r of Array.isArray(o.rows) ? o.rows : []) {
    const rr = (r ?? {}) as Record<string, unknown>;
    const code = str(rr.code);
    if (!code) { problems.push(`dataset ${id}: dropped a row without a code`); continue; }
    const values: Record<string, Cell> = {};
    for (const [k, v] of Object.entries((rr.values ?? {}) as Record<string, unknown>)) values[k] = num(v);
    const suppressed = rr.suppressed && typeof rr.suppressed === "object"
      ? Object.fromEntries(Object.entries(rr.suppressed as Record<string, unknown>).filter(([, v]) => typeof v === "string")) as Record<string, string>
      : undefined;
    rows.push({ code, source_name: str(rr.source_name) ?? "", values, ...(suppressed && Object.keys(suppressed).length ? { suppressed } : {}) });
  }
  const opt = (k: string) => str(o[k]);
  return {
    id, title, department: o.department as Dataset["department"], geography: o.geography as Dataset["geography"],
    foi_reference: opt("foi_reference"), authority: opt("authority"), period: opt("period"), requested_on: opt("requested_on"),
    received_on: opt("received_on"), notes: opt("notes"), columns, rows,
    unmatched: Array.isArray(o.unmatched) ? (o.unmatched as Dataset["unmatched"]) : [],
    summary: normaliseSummary(o.summary),
    file_path: opt("file_path"), created_by: opt("created_by"), created_by_email: opt("created_by_email") ?? "",
    created_at: opt("created_at") ?? "", updated_at: opt("updated_at") ?? "",
  };
}

/** A saved summary, or null when it's missing or malformed (the list then shows less, nothing breaks). */
function normaliseSummary(raw: unknown): DatasetSummary | null {
  const s = (raw ?? {}) as Record<string, unknown>;
  if (typeof s.rows !== "number" || typeof s.unmatched !== "number") return null;
  const h = (s.headline ?? null) as Record<string, unknown> | null;
  const col = (h?.col ?? {}) as Record<string, unknown>;
  const ok = h && typeof col.key === "string" && typeof col.label === "string" && (typeof h.median === "number" || h.median === null);
  return { rows: s.rows, unmatched: s.unmatched, headline: ok ? (h as unknown as DatasetSummary["headline"]) : null };
}

/** Clean up a list of datasets, dropping unusable ones; problems are reported in the console. */
export function normaliseDatasets(raw: unknown[]): Dataset[] {
  const problems: Problems = [];
  const out = raw.map((d) => normaliseDataset(d, problems)).filter((d): d is Dataset => d !== null);
  if (problems.length) console.warn("FOI datasets needed fixing:", problems);
  return out;
}
