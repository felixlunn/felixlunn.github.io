import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource, type Map as MLMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Choropleth, Seat } from "../types";
import { classify, isDark, quantileBreaks, ramp } from "../lib/colors";

/** A finer layer drawn over the constituencies, e.g. the LSOAs of one seat. */
export interface Overlay {
  /** Changing the key re-fits the map to the overlay. */
  key: string;
  geo: GeoJSON.FeatureCollection;
  colours: Record<string, string>;
  label: (code: string) => { name: string; sub?: string; value: string };
}

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

interface Props {
  geo: GeoJSON.FeatureCollection;
  seats: Seat[];
  choropleth: Choropleth;
  selected: string | null;
  /** The user's own seat (office), always outlined. */
  mine?: string | null;
  overlay?: Overlay | null;
  focus: { code: string; n: number } | null;
  onSelect: (code: string) => void;
}

/**
 * Base map: OpenFreeMap (open-source vector tiles from OpenStreetMap; no API key, no usage limits).
 * "Positron" is a pale style made to sit under data; the dark style matches dark mode.
 * Our layers go beneath its labels, so place names stay readable over the shading.
 */
const BASEMAP_URL = (dark: boolean) => `https://tiles.openfreemap.org/styles/${dark ? "dark" : "positron"}`;
const PLAIN: maplibregl.StyleSpecification = { version: 8, sources: {}, layers: [] };

/** Fill opacity: lets the base map show through as you zoom in; solid without one. */
function fillOpacity(hover: number, solid: number, zoomed: number, baseMap: boolean): maplibregl.DataDrivenPropertyValueSpecification<number> {
  const h = ["boolean", ["feature-state", "hover"], false];
  if (!baseMap) return ["case", h, hover, solid] as never;
  return ["interpolate", ["linear"], ["zoom"], 7, ["case", h, hover, solid], 11, ["case", h, zoomed - 0.2, zoomed]] as never;
}

const UK_BOUNDS: [number, number, number, number] = [-8.6, 49.85, 1.8, 60.9];

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#ccc";
}

function bbox(geom: GeoJSON.Geometry): [number, number, number, number] {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  const walk = (c: unknown): void => {
    if (Array.isArray(c) && typeof c[0] === "number") {
      const [x, y] = c as number[];
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    } else if (Array.isArray(c)) c.forEach(walk);
  };
  if ("coordinates" in geom) walk(geom.coordinates);
  return [minX, minY, maxX, maxY];
}

export function useColours(ch: Choropleth) {
  return useMemo(() => {
    const colours = ramp();
    const breaks = quantileBreaks(ch.values, colours.length);
    const palette = colours;
    // With fewer distinct breaks than classes, use the darker end of the ramp evenly.
    const used = palette.slice(0, breaks.length + 1);
    const step = (palette.length - 1) / Math.max(used.length - 1, 1);
    const pick = (k: number) => palette[Math.round(k * step)];
    return { breaks, pick, classes: breaks.length + 1 };
  }, [ch]);
}

export default function MapView({ geo, seats, choropleth, selected, mine = null, overlay = null, focus, onSelect }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(false);
  // Base map on/off, remembered per browser.
  const [baseMap, setBaseMap] = useState(() => {
    try { return localStorage.getItem("whips.baseMap") !== "off"; } catch { return true; }
  });
  useEffect(() => {
    try { localStorage.setItem("whips.baseMap", baseMap ? "on" : "off"); } catch { /* keep for this visit */ }
    const m = map.current;
    if (!m || !ready) return;
    const visibility = baseMap ? "visible" : "none";
    for (const id of baseLayers.current) m.setLayoutProperty(id, "visibility", visibility);
    m.setLayoutProperty("bg", "visibility", baseMap && baseLayers.current.length ? "none" : "visible");
    // Without the base map there's nothing to see through to, so keep the fills solid.
    m.setPaintProperty("fill", "fill-opacity", fillOpacity(0.75, 1, 0.6, baseMap));
    m.setPaintProperty("sub-fill", "fill-opacity", fillOpacity(0.7, 0.95, 0.65, baseMap));
  }, [baseMap, ready]);
  const baseMapRef = useRef(baseMap);
  baseMapRef.current = baseMap;
  const baseLayers = useRef<string[]>([]); // the base map's own layers, hidden when it's switched off
  const [hover, setHover] = useState<{ x: number; y: number; i: number } | null>(null);
  const [subHover, setSubHover] = useState<{ x: number; y: number; code: string } | null>(null);
  const indexByCode = useMemo(() => new Map(seats.map((s, i) => [s.code, i])), [seats]);
  const { breaks, pick } = useColours(choropleth);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    if (!el.current) return;
    const m = new maplibregl.Map({
      container: el.current,
      style: BASEMAP_URL(isDark()),
      bounds: UK_BOUNDS,
      fitBoundsOptions: { padding: 20 },
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
      maxZoom: 13,
      minZoom: 3,
    });
    m.touchZoomRotate.disableRotation();
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: "Boundaries: ONS (OGL), Contains OS data © Crown copyright" }));
    // If the base map can't load (offline, blocked), carry on with a plain background.
    let fellBack = false;
    m.on("error", (e) => {
      if (!fellBack && !m.isStyleLoaded() && !baseLayers.current.length) {
        fellBack = true;
        console.warn("Base map unavailable; using a plain background", e.error);
        m.setStyle(PLAIN);
      }
    });
    m.on("load", () => {
      const styleLayers = m.getStyle().layers ?? [];
      baseLayers.current = styleLayers.map((l) => l.id);
      const labels = styleLayers.find((l) => l.type === "symbol")?.id; // our layers go just beneath the labels
      const on = baseMapRef.current && baseLayers.current.length > 0;
      for (const id of baseLayers.current) m.setLayoutProperty(id, "visibility", on ? "visible" : "none");
      m.addLayer({ id: "bg", type: "background", layout: { visibility: on ? "none" : "visible" }, paint: { "background-color": cssVar("--map-sea") } }, styleLayers[0]?.id);
      const add = (layer: maplibregl.AddLayerObject) => m.addLayer(layer, labels);
      m.addSource("pcon", { type: "geojson", data: geo, promoteId: "code" });
      add({ id: "fill", type: "fill", source: "pcon", paint: { "fill-color": cssVar("--map-nodata"), "fill-opacity": fillOpacity(0.75, 1, 0.6, on) } });
      add({ id: "line", type: "line", source: "pcon", paint: { "line-color": cssVar("--map-line"), "line-width": ["interpolate", ["linear"], ["zoom"], 4, 0.2, 9, 1.2] } });
      m.addSource("sub", { type: "geojson", data: EMPTY, promoteId: "code" });
      add({ id: "sub-fill", type: "fill", source: "sub", paint: { "fill-color": cssVar("--map-nodata"), "fill-opacity": fillOpacity(0.7, 0.95, 0.65, on) } });
      add({ id: "sub-line", type: "line", source: "sub", paint: { "line-color": cssVar("--map-line"), "line-width": 0.6 } });
      add({ id: "highlight", type: "line", source: "pcon", filter: ["in", ["get", "code"], ["literal", []]], paint: { "line-color": cssVar("--accent-2"), "line-width": 2.2 } });
      add({ id: "mine", type: "line", source: "pcon", filter: ["==", ["get", "code"], ""], paint: { "line-color": cssVar("--accent"), "line-width": 3, "line-dasharray": [2, 1] } });
      add({ id: "selected", type: "line", source: "pcon", filter: ["==", ["get", "code"], ""], paint: { "line-color": cssVar("--text-1"), "line-width": 3 } });
      // Fit to the data itself (covers the UK for real boundaries).
      const all: [number, number, number, number] = [Infinity, Infinity, -Infinity, -Infinity];
      geo.features.forEach((f) => {
        // Expand the seat's box so neighbouring seats stay in view for context.
    const [x0, y0, x1, y1] = bbox(f.geometry);
    const ex = (x1 - x0) * 0.8, ey = (y1 - y0) * 0.8;
    const [a, b, c, d] = [x0 - ex, y0 - ey, x1 + ex, y1 + ey];
        all[0] = Math.min(all[0], a); all[1] = Math.min(all[1], b);
        all[2] = Math.max(all[2], c); all[3] = Math.max(all[3], d);
      });
      if (Number.isFinite(all[0]) && !focus) m.fitBounds(all, { padding: 20, duration: 0 });
      setReady(true);
    });
    let hovered: string | null = null;
    let subHovered: string | null = null;
    const overSub = (p: maplibregl.PointLike) => m.getLayer("sub-fill") && m.queryRenderedFeatures(p, { layers: ["sub-fill"] }).length > 0;
    m.on("mousemove", "sub-fill", (e) => {
      const code = e.features?.[0]?.properties?.code;
      if (!code) return;
      if (subHovered !== code) {
        if (subHovered) m.setFeatureState({ source: "sub", id: subHovered }, { hover: false });
        subHovered = String(code);
        m.setFeatureState({ source: "sub", id: subHovered }, { hover: true });
      }
      setSubHover({ x: e.point.x, y: e.point.y, code: String(code) });
    });
    m.on("mouseleave", "sub-fill", () => {
      if (subHovered) m.setFeatureState({ source: "sub", id: subHovered }, { hover: false });
      subHovered = null;
      setSubHover(null);
    });
    m.on("mousemove", "fill", (e) => {
      if (overSub(e.point)) { setHover(null); return; }
      const f = e.features?.[0];
      if (!f) return;
      const code = String(f.properties?.code);
      if (hovered !== code) {
        if (hovered) m.setFeatureState({ source: "pcon", id: hovered }, { hover: false });
        hovered = code;
        m.setFeatureState({ source: "pcon", id: code }, { hover: true });
      }
      m.getCanvas().style.cursor = "pointer";
      const i = indexByCode.get(code);
      if (i !== undefined) setHover({ x: e.point.x, y: e.point.y, i });
    });
    m.on("mouseleave", "fill", () => {
      if (hovered) m.setFeatureState({ source: "pcon", id: hovered }, { hover: false });
      hovered = null;
      m.getCanvas().style.cursor = "";
      setHover(null);
    });
    m.on("click", "fill", (e) => {
      if (overSub(e.point)) return;
      const code = e.features?.[0]?.properties?.code;
      if (code) onSelectRef.current(String(code));
    });
    map.current = m;
    return () => m.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Data updates (e.g. a different data.json) without rebuilding the map.
  useEffect(() => {
    if (ready) (map.current?.getSource("pcon") as GeoJSONSource | undefined)?.setData(geo);
  }, [geo, ready]);

  // Recolour: one `match` expression, no geometry reload.
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const expr: unknown[] = ["match", ["get", "code"]];
    seats.forEach((s, i) => {
      const v = choropleth.values[i];
      if (v === null || v === undefined) return;
      expr.push(s.code, choropleth.categories ? (choropleth.categories[v]?.colour ?? cssVar("--map-nodata")) : pick(classify(v, breaks)));
    });
    expr.push(cssVar("--map-nodata"));
    m.setPaintProperty("fill", "fill-color", expr.length > 3 ? expr : cssVar("--map-nodata"));
    m.setFilter("highlight", ["in", ["get", "code"], ["literal", choropleth.highlight ?? []]]);
  }, [choropleth, breaks, pick, seats, ready]);

  useEffect(() => {
    if (ready) map.current?.setFilter("selected", ["==", ["get", "code"], selected ?? ""]);
  }, [selected, ready]);

  // Overlay: data and fit when the overlay (seat) changes, colours whenever they change.
  const overlayKey = overlay?.key ?? null;
  const overlayRef = useRef<string | null>(null);
  overlayRef.current = overlayKey;
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    (m.getSource("sub") as GeoJSONSource | undefined)?.setData(overlay?.geo ?? EMPTY);
    if (overlay?.geo.features.length) {
      const all: [number, number, number, number] = [Infinity, Infinity, -Infinity, -Infinity];
      overlay.geo.features.forEach((f) => {
        const [a, b, c, d] = bbox(f.geometry);
        all[0] = Math.min(all[0], a); all[1] = Math.min(all[1], b); all[2] = Math.max(all[2], c); all[3] = Math.max(all[3], d);
      });
      const w = m.getContainer().clientWidth;
      m.fitBounds(all, { padding: w < 700 ? 20 : { top: 40, bottom: 40, left: 40, right: 40 }, maxZoom: 13, duration: 600 });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overlayKey, ready]);
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !overlay) return;
    const expr: unknown[] = ["match", ["get", "code"]];
    for (const [code, colour] of Object.entries(overlay.colours)) expr.push(code, colour);
    expr.push(cssVar("--map-nodata"));
    m.setPaintProperty("sub-fill", "fill-color", expr.length > 3 ? expr : cssVar("--map-nodata"));
  }, [overlay, ready]);

  useEffect(() => {
    if (ready) map.current?.setFilter("mine", ["==", ["get", "code"], mine ?? ""]);
  }, [mine, ready]);

  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !focus || overlayRef.current) return; // an overlay frames the map itself
    const f = geo.features.find((x) => x.properties?.code === focus.code);
    if (!f) return;
    // Expand the seat's box so neighbouring seats stay in view for context.
    const [x0, y0, x1, y1] = bbox(f.geometry);
    const ex = (x1 - x0) * 0.8, ey = (y1 - y0) * 0.8;
    const [a, b, c, d] = [x0 - ex, y0 - ey, x1 + ex, y1 + ey];
    // Leave room for the dossier panel on the right on wide screens.
    const w = m.getContainer().clientWidth;
    const padding = window.innerWidth < 860 || w < 900 ? 30 : { top: 80, bottom: 80, left: 80, right: 480 };
    m.fitBounds([a, b, c, d], { padding, maxZoom: 9, duration: 700 });
  }, [focus, geo, ready]);

  const sub = overlay && subHover ? overlay.label(subHover.code) : null;
  const hv = hover && !sub ? seats[hover.i] : null;
  const hvValue = hover ? choropleth.values[hover.i] : null;
  return (
    <div className="map-wrap">
      <div ref={el} className="map" role="application" aria-label="Map of Westminster constituencies" data-dark={isDark()} />
      <button className={`map-toggle ${baseMap ? "on" : ""}`} onClick={() => setBaseMap((b) => !b)} aria-pressed={baseMap}
        title={baseMap ? "Hide the base map (streets and place names)" : "Show the base map (streets and place names)"}>
        {baseMap ? "Base map: on" : "Base map: off"}
      </button>
      {sub && subHover && (
        <div className="tooltip" style={{ left: subHover.x + 14, top: subHover.y + 14 }}>
          <div className="tt-name">{sub.name}</div>
          {sub.sub && <div className="tt-sub">{sub.sub}</div>}
          <div className="tt-val"><strong>{sub.value}</strong></div>
        </div>
      )}
      {hv && hover && (
        <div className="tooltip" style={{ left: hover.x + 14, top: hover.y + 14 }}>
          <div className="tt-name">{hv.name}</div>
          <div className="tt-sub">{hv.party ?? hv.country}</div>
          {choropleth.title && (
            <div className="tt-val">
              <span className="muted">{choropleth.title}: </span>
              <strong>{hvValue === null || hvValue === undefined ? "No data" : choropleth.format(hvValue)}</strong>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
