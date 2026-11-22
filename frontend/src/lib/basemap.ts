import type { StyleSpecification } from "maplibre-gl";
import { isDark } from "./colors";

/**
 * Base map for both maps (dashboard and FOI): the standard OpenStreetMap tiles (no API key). Use follows the OSM
 * tile usage policy: attribution is shown and the browser sends its normal Referer. Dimmed in dark mode.
 * If tiles can't load, the plain background underneath simply shows through.
 */
export function osmStyle(): StyleSpecification {
  const dark = isDark();
  return {
    version: 8,
    sources: {
      osm: {
        type: "raster", tileSize: 256, maxzoom: 19,
        tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors',
      },
    },
    layers: [{
      id: "osm", type: "raster", source: "osm",
      paint: dark ? { "raster-brightness-max": 0.55, "raster-saturation": -0.4 } : { "raster-saturation": -0.15 },
    }],
  };
}

/** The UK's bounding box, for the initial view. */
export const UK_BOUNDS: [number, number, number, number] = [-8.6, 49.85, 1.8, 60.9];
