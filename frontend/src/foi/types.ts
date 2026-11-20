/** FOI research section: shared types. */

export type Department = "policing" | "justice" | "health";
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
  seats: { code: string; name: string; mp: string | null; party: string | null }[];
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
  file_path: string | null;
  created_by: string | null;
  created_by_email: string;
  created_at: string;
  updated_at: string;
}

export type NewDataset = Omit<Dataset, "id" | "created_by" | "created_by_email" | "created_at" | "updated_at">;

export const DEPARTMENTS: { id: Department; label: string; geographies: Geography[]; blurb: string }[] = [
  { id: "policing", label: "Policing", geographies: ["police_force"], blurb: "FOI responses from police forces, mapped by police force area." },
  { id: "justice", label: "Justice", geographies: ["court", "police_force"],
    blurb: "FOI responses from HMCTS, the MoJ, the CPS and others, by court or by criminal justice area (these follow police force areas)." },
  { id: "health", label: "Health", geographies: ["nhs_trust", "health_area"],
    blurb: "FOI responses from NHS trusts and boards, by trust or by NHS area (integrated care boards in England, health boards in Wales)." },
];

export const GEOGRAPHY_LABEL: Record<Geography, string> = {
  police_force: "Police force area",
  court: "Court or tribunal",
  nhs_trust: "NHS trust",
  health_area: "NHS area (ICB / health board)",
};

/** Area geographies are drawn as shapes and can be shown per head; the others are points. */
export const IS_AREA: Record<Geography, boolean> = { police_force: true, court: false, nhs_trust: false, health_area: true };
