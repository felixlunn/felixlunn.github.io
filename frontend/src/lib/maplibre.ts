/**
 * MapLibre, set up for this site. Import maps from here, not from "maplibre-gl" directly.
 *
 * MapLibre 6 draws in a background worker loaded from its own file; once bundled, MapLibre can't find that file by
 * itself, so the build ships it as an asset and MapLibre is told where it is.
 */
import * as maplibregl from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";

maplibregl.setWorkerUrl(workerUrl);

export default maplibregl;
