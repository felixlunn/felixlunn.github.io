/**
 * Everything the FOI section knows about each kind of organisation, in one place: how it's named, whether it's an
 * area (drawn as shapes, can be shown per head) or a place (courts, trusts), its map layer, how it nests (a trust in
 * an NHS area, a court in a criminal justice area), and which departments use it. Adding a geography means adding
 * an entry here (and its reference data in datadash/sources/foi_geo/).
 */

import type { AreaLayer, Department, Geography, RefArea, Reference } from "./types";

export interface GeographyInfo {
  /** "Police force area": one row of a dataset. */
  label: string;
  /** "police force areas": for counts and sentences. */
  plural: string;
  /** Area view names: "Force" / "Forces", and its search prompt. */
  one: string;
  many: string;
  find: string;
  /** Areas are drawn as shapes and can be shown per 100,000 residents; the others are places. */
  isArea: boolean;
  /** The map layer in data/foi/areas.geojson (courts have none: their areas are drawn in the browser). */
  layer: AreaLayer | "trust" | null;
  /** Areas: their list in the reference file (reference.layers). */
  areas?: AreaLayer;
  parent?: Geography;
  child?: Geography;
  /** Shown over the map when the shapes need explaining. */
  mapNote?: string;
}

export const GEO: Record<Geography, GeographyInfo> = {
  police_force: {
    label: "Police force area", plural: "police force areas", one: "Force", many: "Forces", find: "Find a force",
    isArea: true, layer: "police", areas: "police", child: "court",
  },
  court: {
    label: "Court or tribunal", plural: "courts and tribunals", one: "Court", many: "Courts", find: "Find a court",
    isArea: false, layer: null, parent: "police_force",
    mapNote: "Court areas are approximate: HMCTS doesn't publish catchments, so each court covers the land nearest to it among the courts with figures.",
  },
  nhs_trust: {
    label: "NHS trust", plural: "NHS trusts", one: "Trust", many: "Trusts", find: "Find a trust",
    isArea: false, layer: "trust", parent: "health_area",
    mapNote: "Shaded areas are each acute trust's catchment (OHID: where most local residents are admitted). Trusts without one (specialist and community trusts) are dots.",
  },
  health_area: {
    label: "NHS area (ICB / health board)", plural: "NHS areas", one: "ICB / health board", many: "ICBs", find: "Find an ICB or health board",
    isArea: true, layer: "health", areas: "health", child: "nhs_trust",
  },
  mh_trust: {
    label: "Mental health trust", plural: "mental health trusts", one: "Mental health trust", many: "Mental health", find: "Find a mental health trust",
    isArea: true, layer: "mental_health", areas: "mental_health",
    mapNote: "Areas are approximate: no boundaries are published, so each council goes to the mental health trust running the most sites there (NHS ODS).",
  },
  ambulance_trust: {
    label: "Ambulance trust", plural: "ambulance trusts", one: "Ambulance trust", many: "Ambulance", find: "Find an ambulance trust",
    isArea: true, layer: "ambulance", areas: "ambulance",
    mapNote: "Ambulance trust areas follow regions and counties (the South East is split by county); Wales, Scotland and Northern Ireland each have one service.",
  },
};

export interface DepartmentInfo {
  id: Department;
  label: string;
  /** The geographies its datasets can use; the first is the default (upload, Area view). */
  geographies: Geography[];
  blurb: string;
  /** Shown on the Area view switch. */
  areaViewHint: string;
}

export const DEPARTMENTS: DepartmentInfo[] = [
  { id: "policing", label: "Policing", geographies: ["police_force"], blurb: "FOI responses from police forces, mapped by police force area.",
    areaViewHint: "Every dataset for one police force" },
  { id: "health", label: "Health", geographies: ["nhs_trust", "health_area", "mh_trust", "ambulance_trust"],
    blurb: "FOI responses from NHS bodies, by hospital trust, NHS area (ICBs in England, health boards in Wales), mental health trust or ambulance trust.",
    areaViewHint: "Every dataset for one trust, ICB, mental health trust or ambulance trust" },
];

export const DEPARTMENT: Record<Department, DepartmentInfo> = Object.fromEntries(DEPARTMENTS.map((d) => [d.id, d])) as Record<Department, DepartmentInfo>;

/** An area geography's areas from the reference file (empty for places, or a layer an older file lacks). */
export function areasOf(ref: Reference, g: Geography): RefArea[] {
  const l = GEO[g].areas;
  return l ? ref.layers[l]?.areas ?? [] : [];
}

/** Trusts on the "Trusts" layer: hospital (and community) trusts; mental health and ambulance trusts have their own. */
export function hospitalTrusts(ref: Reference) {
  return (ref.points.trusts ?? []).filter((t) => !t.groups || t.groups.includes("hospital"));
}
