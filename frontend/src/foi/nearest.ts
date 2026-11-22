/**
 * "Nearest" on the ground, used wherever courts are matched to land or seats (the shaded court areas in cells.ts,
 * and which court serves a seat in analysis.ts), so the map and the seat panels always agree.
 */

import type { Reference } from "./types";

/** Longitude degrees are shorter than latitude degrees in Britain: scale them so "nearest" means nearest on the ground. */
export const LON_SCALE = Math.cos((54 * Math.PI) / 180);

/** England & Wales, Scotland or Northern Ireland, from an ONS code (police force area or seat): courts never cross. */
export function jurisdictionOf(code: string | null | undefined): "EW" | "S" | "N" {
  return code?.startsWith("S") ? "S" : code?.startsWith("N") ? "N" : "EW";
}

/** Seat code -> the court in ``inResponse`` nearest to the seat's centre, within the seat's jurisdiction. */
export function nearestCourtBySeat(ref: Reference, inResponse: Set<string>): Map<string, string> {
  const courts = (ref.points.courts ?? []).filter((c) => inResponse.has(c.id));
  const out = new Map<string, string>();
  for (const s of ref.seats) {
    if (s.lon === undefined || s.lat === undefined) continue;
    let best: string | null = null, bestD = Infinity;
    for (const c of courts) {
      if (jurisdictionOf(c.area) !== jurisdictionOf(s.code)) continue;
      const d = ((c.lon - s.lon) * LON_SCALE) ** 2 + (c.lat - s.lat) ** 2;
      if (d < bestD) { bestD = d; best = c.id; }
    }
    if (best) out.set(s.code, best);
  }
  return out;
}
