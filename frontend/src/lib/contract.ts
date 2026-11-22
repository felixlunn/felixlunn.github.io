/** The shape of data.json, checked in the tests and when the site loads it (see lib/check.ts). */

import { each, field, type Problems } from "./check";

/** The data.json format this code reads. The pipeline writes "version"; bump both together on a breaking change. */
export const DATA_VERSION = 1;

export function checkDashboardData(d: unknown): Problems {
  const p: Problems = [];
  field(p, d, "version", ["number"], "data");
  if (d && typeof d === "object" && (d as { version?: unknown }).version !== DATA_VERSION) {
    p.push(`data.version: this site reads version ${DATA_VERSION}, the data is version ${(d as { version?: unknown }).version}`);
  }
  for (const k of ["themes", "metrics", "seats", "peer_groups", "sources"]) field(p, d, k, ["array"], "data");
  field(p, d, "values", ["object"], "data");
  const o = (d ?? {}) as Record<string, unknown>;
  each(p, o.metrics, "metrics", (m, at) => {
    for (const k of ["id", "label", "theme", "unit", "polarity"]) field(p, m, k, ["string"], at);
    for (const k of ["decimals", "coverage"]) field(p, m, k, ["number"], at);
    field(p, m, "national", ["number", "null"], at);
  });
  each(p, o.seats, "seats", (s, at) => {
    for (const k of ["code", "name", "country"]) field(p, s, k, ["string"], at);
    for (const k of ["mp", "party"]) field(p, s, k, ["string", "null"], at);
  });
  each(p, o.sources, "sources", (s, at) => {
    for (const k of ["id", "name", "status"]) field(p, s, k, ["string"], at);
  });
  // Every metric has one value per seat.
  const seats = Array.isArray(o.seats) ? o.seats.length : 0;
  const values = (o.values ?? {}) as Record<string, unknown>;
  each(p, o.metrics, "metrics", (m, at) => {
    const id = (m as { id?: string }).id ?? "";
    const v = values[id];
    if (!Array.isArray(v) || v.length !== seats) p.push(`${at}: values["${id}"] should have ${seats} entries`);
  });
  return p;
}
