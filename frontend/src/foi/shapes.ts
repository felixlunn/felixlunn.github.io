/** What to shade on the FOI map for a geography: official boundaries, trust catchments, or approximate court areas. */

import { jurisdictionOf, nearestAreas } from "./cells";
import { IS_AREA, type Geography, type Reference } from "./types";

export function mapShapes(ref: Reference, all: GeoJSON.FeatureCollection, g: Geography, inResponse: Set<string>): GeoJSON.FeatureCollection {
  const of = (layer: string) => ({ ...all, features: all.features.filter((f) => f.properties?.layer === layer) });
  if (IS_AREA[g]) return of(g === "police_force" ? "police" : "health");
  if (g === "nhs_trust") return of("trust");
  const lands = Object.fromEntries(of("land").features.map((f) => [String(f.properties?.code), f.geometry]));
  const courts = (ref.points.courts ?? []).filter((c) => inResponse.has(c.id))
    .map((c) => ({ code: c.id, lon: c.lon, lat: c.lat, jurisdiction: jurisdictionOf(c.area) }));
  return nearestAreas(courts, lands);
}

export const MAP_NOTE: Partial<Record<Geography, string>> = {
  court: "Court areas are approximate: HMCTS doesn't publish catchments, so each court covers the land nearest to it among the courts with figures.",
  nhs_trust: "Shaded areas are each acute trust's catchment (OHID: where most local residents are admitted). Trusts without one (mental health, community, ambulance) are dots.",
};
