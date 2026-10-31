import type { Choropleth } from "../types";
import { useColours } from "./MapView";

export default function Legend({ ch }: { ch: Choropleth }) {
  const { breaks, pick, classes } = useColours(ch);
  const vals = ch.values.filter((v): v is number => v !== null);
  const min = vals.length ? Math.min(...vals) : null;
  const max = vals.length ? Math.max(...vals) : null;
  const missing = ch.values.length - vals.length;
  return (
    <div className={`legend ${ch.categories ? "wide" : ""}`} aria-label="Map legend">
      <div className="legend-title">{ch.title}</div>
      {ch.subtitle && <div className="legend-sub">{ch.subtitle}</div>}
      {ch.categories && (
        <ul className="legend-cats">
          {ch.categories.map((c) => (
            <li key={c.label}>
              <span className="swatch" style={{ background: c.colour }} />
              <span className="cat-label">{c.label}</span>
              <span className="num">{c.count}</span>
            </li>
          ))}
        </ul>
      )}
      {!ch.categories && min !== null && max !== null && (
        <>
          <div className="legend-bar">
            {Array.from({ length: classes }, (_, k) => (
              <span key={k} style={{ background: pick(k) }} />
            ))}
          </div>
          <div className="legend-labels">
            <span>{ch.format(min)}</span>
            {breaks.length > 2 && <span>{ch.format(breaks[Math.floor(breaks.length / 2)])}</span>}
            <span>{ch.format(max)}</span>
          </div>
          {ch.invert && <div className="legend-sub">{ch.invertNote ?? "Darker = closer match"}</div>}
        </>
      )}
      {missing > 0 && (
        <div className="legend-nodata">
          <span className="swatch nodata" /> {ch.nodataLabel ?? "No data"} ({missing} seats)
        </div>
      )}
      {ch.highlight && ch.highlight.length > 0 && (
        <div className="legend-nodata">
          <span className="swatch outline" /> {ch.highlightLabel ?? "Highlighted"} ({ch.highlight.length})
        </div>
      )}
    </div>
  );
}
