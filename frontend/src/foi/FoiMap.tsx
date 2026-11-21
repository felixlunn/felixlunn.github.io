import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource, type Map as MLMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { classify, isDark, quantileBreaks, ramp } from "../lib/colors";

export interface MapItem { code: string; name: string; value: number | null; label: string; sub?: string; lat?: number; lon?: number }

interface Props {
  /** Shapes for area geographies (police force areas, NHS areas); null for point geographies. */
  shapes: GeoJSON.FeatureCollection | null;
  items: MapItem[];
  /** Higher is better: flip the ramp so red still means the worse end. */
  reverse: boolean;
  selected: string | null;
  /** Codes to outline, e.g. those serving the chosen seat. */
  highlight: Set<string>;
  /** Outliers: outlined dashed (areas) or ringed (points). */
  flagged?: Set<string>;
  /** Filtered out: faded on the map. */
  dimmed?: Set<string>;
  /** The key: what is shown, and how to write its values. */
  title?: string;
  format?: (v: number) => string;
  onSelect: (code: string) => void;
}

const UK_BOUNDS: [number, number, number, number] = [-8.6, 49.85, 1.8, 60.9];
const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

function css(name: string) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#ccc"; }

const NONE = new Set<string>();

export default function FoiMap({ shapes, items, reverse, selected, highlight, flagged = NONE, dimmed = NONE, title, format = (v) => v.toLocaleString("en-GB"), onSelect }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(false);
  const [hover, setHover] = useState<{ x: number; y: number; code: string } | null>(null);
  const pick = useRef(onSelect);
  pick.current = onSelect;

  const byCode = useMemo(() => new Map(items.map((i) => [i.code, i])), [items]);
  const { breaks, colours } = useMemo(() => {
    const c = ramp();
    return { breaks: quantileBreaks(items.map((i) => i.value), c.length), colours: reverse ? [...c].reverse() : c };
  }, [items, reverse]);
  // The key: one line per colour, with the range of values it covers (highest first).
  const legend = useMemo(() => {
    const vals = items.map((i) => i.value).filter((v): v is number => v !== null).sort((a, b) => a - b);
    if (!vals.length) return [];
    const used = breaks.length + 1;
    const step = (colours.length - 1) / Math.max(used - 1, 1);
    const out = [];
    for (let k = 0; k < used; k++) {
      const inClass = vals.filter((v) => classify(v, breaks) === k);
      if (inClass.length) out.push({ colour: colours[Math.round(k * step)], lo: inClass[0], hi: inClass[inClass.length - 1] });
    }
    return out.reverse();
  }, [items, breaks, colours]);
  const colour = (v: number | null) => {
    if (v === null) return css("--map-nodata");
    const used = breaks.length + 1;
    const step = (colours.length - 1) / Math.max(used - 1, 1);
    return colours[Math.round(classify(v, breaks) * step)];
  };

  useEffect(() => {
    if (!el.current) return;
    const dark = isDark();
    const m = new maplibregl.Map({
      container: el.current, bounds: UK_BOUNDS, fitBoundsOptions: { padding: 20 }, attributionControl: false,
      dragRotate: false, pitchWithRotate: false, maxZoom: 13, minZoom: 3,
      style: {
        version: 8,
        sources: { osm: { type: "raster", tileSize: 256, maxzoom: 19, tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
          attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors' } },
        layers: [{ id: "osm", type: "raster", source: "osm", paint: dark ? { "raster-brightness-max": 0.55, "raster-saturation": -0.4 } : { "raster-saturation": -0.15 } }],
      },
    });
    m.touchZoomRotate.disableRotation();
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: "Boundaries: ONS (OGL); courts: HMCTS; NHS bodies: NHS ODS" }));
    m.on("load", () => {
      m.addSource("areas", { type: "geojson", data: EMPTY, promoteId: "code" });
      m.addSource("pts", { type: "geojson", data: EMPTY, promoteId: "code" });
      m.addLayer({ id: "fill", type: "fill", source: "areas", paint: { "fill-color": ["get", "c"], "fill-opacity": ["case", ["==", ["get", "x"], 1], 0.12, ["boolean", ["feature-state", "hover"], false], 0.85, 0.68] } });
      m.addLayer({ id: "line", type: "line", source: "areas", paint: { "line-color": css("--map-line"), "line-width": 0.8 } });
      m.addLayer({ id: "flag", type: "line", source: "areas", filter: ["==", ["get", "f"], 1], paint: { "line-color": css("--text-1"), "line-width": 2, "line-dasharray": [2, 1.5] } });
      m.addLayer({ id: "hl", type: "line", source: "areas", filter: ["==", ["get", "h"], 1], paint: { "line-color": css("--accent"), "line-width": 2.5 } });
      m.addLayer({ id: "sel", type: "line", source: "areas", filter: ["==", ["get", "s"], 1], paint: { "line-color": css("--accent-2"), "line-width": 3.5 } });
      m.addLayer({ id: "dots", type: "circle", source: "pts", paint: {
        "circle-color": ["get", "c"], "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, ["case", ["==", ["get", "s"], 1], 8, 5], 10, 10],
        "circle-stroke-color": ["case", ["==", ["get", "s"], 1], css("--accent-2"), ["==", ["get", "h"], 1], css("--accent"), ["==", ["get", "f"], 1], css("--text-1"), "#ffffff"],
        "circle-stroke-width": ["case", ["==", ["get", "s"], 1], 3, ["==", ["get", "h"], 1], 2.5, ["==", ["get", "f"], 1], 2, 1],
        "circle-opacity": ["case", ["==", ["get", "x"], 1], 0.12, ["==", ["get", "v"], 1], 0.95, 0.35],
        "circle-stroke-opacity": ["case", ["==", ["get", "x"], 1], 0.2, 1],
      } });
      let hovered: string | null = null;
      for (const id of ["fill", "dots"]) {
        m.on("mousemove", id, (e) => {
          const f = e.features?.[0];
          if (!f) return;
          const code = String(f.properties?.code);
          if (id === "fill") {
            if (hovered && hovered !== code) m.setFeatureState({ source: "areas", id: hovered }, { hover: false });
            m.setFeatureState({ source: "areas", id: code }, { hover: true });
            hovered = code;
          }
          m.getCanvas().style.cursor = "pointer";
          setHover({ x: e.point.x, y: e.point.y, code });
        });
        m.on("mouseleave", id, () => {
          if (hovered) m.setFeatureState({ source: "areas", id: hovered }, { hover: false });
          hovered = null;
          m.getCanvas().style.cursor = "";
          setHover(null);
        });
        m.on("click", id, (e) => { const c = e.features?.[0]?.properties?.code; if (c) pick.current(String(c)); });
      }
      setReady(true);
    });
    map.current = m;
    return () => { m.remove(); map.current = null; };
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const flags = (code: string) => ({ s: code === selected ? 1 : 0, h: highlight.has(code) ? 1 : 0, f: flagged.has(code) && !dimmed.has(code) ? 1 : 0, x: dimmed.has(code) ? 1 : 0 });
    const areas: GeoJSON.FeatureCollection = shapes ? {
      type: "FeatureCollection",
      features: shapes.features.map((f) => {
        const code = String(f.properties?.code);
        const it = byCode.get(code);
        return { ...f, properties: { ...f.properties, c: colour(it?.value ?? null), ...flags(code) } };
      }),
    } : EMPTY;
    // Places drawn as shapes aren't also drawn as dots; the rest (e.g. trusts without a catchment) are.
    const shaped = new Set((shapes?.features ?? []).map((f) => String(f.properties?.code)));
    const pts: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      // Points with values draw on top of those without.
      features: [...items].sort((a, b) => Number(a.value !== null) - Number(b.value !== null) || Number(highlight.has(a.code)) - Number(highlight.has(b.code)))
        .filter((i) => i.lat !== undefined && !shaped.has(i.code))
        .map((i) => ({ type: "Feature", properties: { code: i.code, c: colour(i.value), v: i.value === null ? 0 : 1, ...flags(i.code) },
          geometry: { type: "Point", coordinates: [i.lon!, i.lat!] } })),
    };
    (m.getSource("areas") as GeoJSONSource).setData(areas);
    (m.getSource("pts") as GeoJSONSource).setData(pts);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, shapes, items, breaks, colours, selected, highlight, flagged, dimmed]);

  const h = hover ? byCode.get(hover.code) : null;
  return (
    <div className="foi-map">
      <div ref={el} className="foi-map-canvas" />
      {h && hover && (
        <div className="tooltip" style={{ left: hover.x + 14, top: hover.y + 14 }}>
          <div className="tt-name">{h.name}</div>
          {h.sub && <div className="tt-sub">{h.sub}</div>}
          <div className="tt-value">{h.label}</div>
        </div>
      )}
      {legend.length > 0 && (
        <div className="foi-legend">
          {title && <div className="lg-title">{title}</div>}
          <ul>
            {legend.map((b, i) => (
              <li key={i}><span className="sw" style={{ background: b.colour }} />{b.lo === b.hi ? format(b.lo) : `${format(b.lo)} – ${format(b.hi)}`}</li>
            ))}
            <li className="muted"><span className="sw" style={{ background: css("--map-nodata") }} />No figure</li>
            {dimmed.size > 0 && <li className="muted"><span className="sw faded" />Filtered out (faded)</li>}
          </ul>
        </div>
      )}
    </div>
  );
}
