/**
 * Everything the FOI section knows about each kind of organisation, in one place: how it's named, whether it's an
 * area (drawn as shapes, can be shown per head) or a place (courts, trusts), its map layer, how it nests (a trust in
 * an NHS area, a court in a criminal justice area), and which departments use it. Adding a geography means adding
 * an entry here (and its reference data in datadash/sources/foi_geo/).
 */

import type { Department, Geography } from "./types";

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
  layer: "police" | "health" | "trust" | null;
  parent?: Geography;
  child?: Geography;
  /** Shown over the map when the shapes need explaining. */
  mapNote?: string;
}

export const GEO: Record<Geography, GeographyInfo> = {
  police_force: {
    label: "Police force area", plural: "police force areas", one: "Force", many: "Forces", find: "Find a force",
    isArea: true, layer: "police", child: "court",
  },
  court: {
    label: "Court or tribunal", plural: "courts and tribunals", one: "Court", many: "Courts", find: "Find a court",
    isArea: false, layer: null, parent: "police_force",
    mapNote: "Court areas are approximate: HMCTS doesn't publish catchments, so each court covers the land nearest to it among the courts with figures.",
  },
  nhs_trust: {
    label: "NHS trust", plural: "NHS trusts", one: "Trust", many: "Trusts", find: "Find a trust",
    isArea: false, layer: "trust", parent: "health_area",
    mapNote: "Shaded areas are each acute trust's catchment (OHID: where most local residents are admitted). Trusts without one (mental health, community, ambulance) are dots.",
  },
  health_area: {
    label: "NHS area (ICB / health board)", plural: "NHS areas", one: "ICB / health board", many: "ICBs", find: "Find an ICB or health board",
    isArea: true, layer: "health", child: "nhs_trust",
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
  { id: "health", label: "Health", geographies: ["nhs_trust", "health_area"],
    blurb: "FOI responses from NHS trusts and boards, by trust or by NHS area (integrated care boards in England, health boards in Wales).",
    areaViewHint: "Every dataset for one NHS trust or ICB" },
];

export const DEPARTMENT: Record<Department, DepartmentInfo> = Object.fromEntries(DEPARTMENTS.map((d) => [d.id, d])) as Record<Department, DepartmentInfo>;
