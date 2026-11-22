/**
 * Approximate areas for places that have no published boundary (courts): each place gets the land nearer to it
 * than to any other place in the same response (a Voronoi diagram), clipped to the coast of its own jurisdiction.
 */

import { Delaunay } from "d3-delaunay";
import polygonClipping, { type MultiPolygon, type Polygon } from "polygon-clipping";
import { LON_SCALE } from "./nearest";

export interface Place { code: string; lon: number; lat: number; jurisdiction: string }

function asMulti(g: GeoJSON.Geometry): MultiPolygon {
  if (g.type === "Polygon") return [g.coordinates as Polygon];
  if (g.type === "MultiPolygon") return g.coordinates as MultiPolygon;
  return [];
}

function bbox(m: MultiPolygon): [number, number, number, number] {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const poly of m) for (const [x, y] of poly[0]) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
  return [x0, y0, x1, y1];
}

/** Land polygons, each with its bounding box, so a cell is only clipped against the land near it. */
function indexLand(m: MultiPolygon) {
  return m.map((poly) => ({ poly, box: bbox([poly]) }));
}

export function nearestAreas(places: Place[], lands: Record<string, GeoJSON.Geometry>): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = [];
  for (const [jur, landGeom] of Object.entries(lands)) {
    const pts = places.filter((p) => p.jurisdiction === jur);
    if (!pts.length) continue;
    const land = asMulti(landGeom);
    const parts = indexLand(land);
    const [x0, y0, x1, y1] = bbox(land);
    // Nudge exact duplicates (two courts in one building) so each still gets a cell.
    const seen = new Map<string, number>();
    const xy = pts.map((p) => {
      const k = `${p.lon},${p.lat}`;
      const n = seen.get(k) ?? 0;
      seen.set(k, n + 1);
      return [(p.lon + n * 1e-4) * LON_SCALE, p.lat + n * 1e-4] as [number, number];
    });
    const vor = Delaunay.from(xy).voronoi([x0 * LON_SCALE - 1, y0 - 1, x1 * LON_SCALE + 1, y1 + 1]);
    pts.forEach((p, i) => {
      const cell = vor.cellPolygon(i);
      if (!cell) return;
      const ring = cell.map(([x, y]) => [x / LON_SCALE, y] as [number, number]);
      const cb = bbox([[ring]]);
      const near = parts.filter(({ box }) => box[0] <= cb[2] && box[2] >= cb[0] && box[1] <= cb[3] && box[3] >= cb[1]).map((x) => x.poly);
      if (!near.length) return;
      const clipped = polygonClipping.intersection([ring], near);
      if (clipped.length) features.push({ type: "Feature", properties: { code: p.code }, geometry: { type: "MultiPolygon", coordinates: clipped } });
    });
  }
  return { type: "FeatureCollection", features };
}

