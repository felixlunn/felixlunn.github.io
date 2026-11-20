import { useMemo, useState } from "react";
import type { DashboardData } from "../types";
import { findMetrics } from "../lib/findMetric";
import { fmt } from "../lib/format";

/** "Find a figure": type an everyday word (potholes, dentist, rent) and jump to the matching figure. */
export default function FigureSearch({ data, selected, onPick }: { data: DashboardData; selected: number | null; onPick: (id: string) => void }) {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const hits = useMemo(() => findMetrics(data.metrics, q), [data, q]);
  const themeLabel = useMemo(() => new Map(data.themes.map((t) => [t.id, t.label])), [data]);
  const pick = (id: string) => { onPick(id); setQ(""); };
  return (
    <div className="figure-search" role="search">
      <input type="search" value={q} placeholder="Find a figure, e.g. potholes, dentist, rent" aria-label="Find a figure"
        onChange={(e) => { setQ(e.target.value); setActive(0); }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, hits.length - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
          else if (e.key === "Enter" && hits[active]) pick(hits[active].id);
          else if (e.key === "Escape") setQ("");
        }} />
      {q.trim().length >= 2 && (
        <ul className="search-results figure-results" role="listbox">
          {hits.map((m, k) => (
            <li key={m.id} role="option" aria-selected={k === active} className={k === active ? "on" : ""} onMouseDown={(e) => { e.preventDefault(); pick(m.id); }}>
              <span>{m.label}<span className="tiny muted"> · {themeLabel.get(m.theme) ?? m.theme}</span></span>
              {selected !== null && data.values[m.id]?.[selected] != null && <span className="num">{fmt(m, data.values[m.id][selected])}</span>}
            </li>
          ))}
          {!hits.length && <li className="muted">No figure matches “{q.trim()}”.</li>}
        </ul>
      )}
    </div>
  );
}
