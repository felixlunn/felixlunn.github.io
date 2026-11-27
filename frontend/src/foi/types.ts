/** FOI research section: shared types. */

export type Department = "policing" | "health";
export type Geography = "police_force" | "court" | "nhs_trust" | "health_area";
export type Direction = "higher_worse" | "higher_better" | "neutral";

export interface RefArea {
  code: string;
  name: string;
  aliases: string[];
  population: number | null;
  /** [seat code, share of that seat inside the area] */
  seats: [string, number][];
}

export interface RefCourt { id: string; name: string; types: string[]; lat: number; lon: number; codes: string[]; area: string | null; seat: string | null }
export interface RefTrust {
  code: string; name: string; kind: string; postcode: string; lat: number; lon: number; area: string | null; seat: string | null;
  /** Acute trusts: seats in the trust's official catchment (OHID), with the share of each seat covered. */
  catchment?: [string, number][];
}

export interface Reference {
  version: number;
  as_of: string;
  layers: { police: { label: string; areas: RefArea[] }; health: { label: string; areas: RefArea[] } };
  points: { courts?: RefCourt[]; trusts?: RefTrust[] };
  /** ld: "held" (Lib Dem seat) or "target" (Lib Dems second in 2024). */
  seats: { code: string; name: string; mp: string | null; party: string | null; lon?: number; lat?: number; ld?: "held" | "target" }[];
}

/** One thing an uploaded row can be matched to. */
export interface Target {
  code: string;
  name: string;
  /** Names and codes it may appear under in an FOI response. */
  keys: string[];
  population?: number | null;
  sub?: string;
}

export interface Column {
  key: string;
  label: string;
  /** "count" values can be shown per 100,000 residents on area geographies. */
  unit: "count" | "rate" | "percent" | "money" | "other";
  direction: Direction;
  /** Year or period this column covers (e.g. "2023", "2023/24"), when the response gives several. */
  period?: string;
  /** The measure the period belongs to (e.g. "Officers"): columns with the same series and different periods form a time series. */
  series?: string;
  /** A change between two periods: shown with a sign (+/−). */
  change?: { from: string; to: string; mode: "percent" | "absolute" };
  /** Worked out in the browser from the year columns (not stored): the average per year, or the % change. */
  derived?: "average" | "change";
}

export type Cell = number | null;

export interface DataRow {
  code: string;
  source_name: string;
  values: Record<string, Cell>;
  /** Values the response withheld (e.g. "<5", "*"), kept as written. */
  suppressed?: Record<string, string>;
}

export interface Dataset {
  id: string;
  department: Department;
  geography: Geography;
  title: string;
  foi_reference: string | null;
  authority: string | null;
  period: string | null;
  requested_on: string | null;
  received_on: string | null;
  notes: string | null;
  columns: Column[];
  rows: DataRow[];
  unmatched: { source_name: string; values: Record<string, Cell> }[];
  /** Ready-made public data (e.g. "police.uk"), built with the site's data: read-only, and never in the database. */
  builtin?: string;
  /** Saved at upload, so datasets can be listed without their rows. null on datasets saved before summaries. */
  summary: DatasetSummary | null;
  file_path: string | null;
  created_by: string | null;
  created_by_email: string;
  created_at: string;
  updated_at: string;
}

export type NewDataset = Omit<Dataset, "id" | "created_by" | "created_by_email" | "created_at" | "updated_at">;

/** A dataset as listed: everything but its rows, which load when it's opened (or when Area view needs them). */
export type DatasetInfo = Omit<Dataset, "rows" | "unmatched">;

export interface DatasetSummary {
  rows: number;
  unmatched: number;
  /** The headline figure (the % change when the response covers several years, otherwise its first figure):
   * which column it is, and its median across the organisations in the response. */
  headline: { col: Column; median: number | null; n: number } | null;
}
