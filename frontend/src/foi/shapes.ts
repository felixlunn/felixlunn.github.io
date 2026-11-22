/** What to shade on the FOI map for a geography: official boundaries, trust catchments, or approximate court areas (see GEO[g].layer). */

import { nearestAreas } from "./cells";
import { jurisdictionOf } from "./nearest";
import { GEO } from "./geographies";
import type { Geography, Reference } from "./types";

export function mapShapes(ref: Reference, all: GeoJSON.FeatureCollection, g: Geography, inResponse: Set<string>): GeoJSON.FeatureCollection {
  const of = (layer: string) => ({ ...all, features: all.features.filter((f) => f.properties?.layer === layer) });
  const layer = GEO[g].layer;
  if (layer) return of(layer);
  const lands = Object.fromEntries(of("land").features.map((f) => [String(f.properties?.code), f.geometry]));
  const courts = (ref.points.courts ?? []).filter((c) => inResponse.has(c.id))
    .map((c) => ({ code: c.id, lon: c.lon, lat: c.lat, jurisdiction: jurisdictionOf(c.area) }));
  return nearestAreas(courts, lands);
}
