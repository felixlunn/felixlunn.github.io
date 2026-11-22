import { fmtValue } from "./analysis";
import { type YearView } from "./periods";
import { type Dataset } from "./types";
/** Multi-year responses: the view switch (average / % change / one year) and the per-area year chart. */

/**
 * What to map. Multi-year responses get the standard views (average per year, % change, or one year) for each
 * measure; any other figures are listed after them.
 */
export function ViewPicker({ d, views, colKey, setColKey }: { d: Dataset; views: YearView[]; colKey: string; setColKey: (k: string) => void }) {
  const inView = new Set(views.flatMap((v) => [v.average.key, v.change.key, ...v.years.map((y) => y.key)]));
  const others = d.columns.filter((c) => !inView.has(c.key));
  const current = views.find((v) => [v.average.key, v.change.key, ...v.years.map((y) => y.key)].includes(colKey));
  const v = current ?? views[0];
  const chips = (cols: typeof others) => (
    <div className="chips">
      {cols.map((c) => <button key={c.key} className={`chip ${c.key === colKey ? "on" : ""}`} onClick={() => setColKey(c.key)}>{c.label}</button>)}
    </div>
  );
  if (!views.length) return chips(d.columns);
  const year = v.years.find((y) => y.key === colKey);
  // Switching measure keeps the same kind of view (average / change / latest year).
  const sameKind = (next: YearView) => (colKey === v.change.key ? next.change.key : colKey === v.average.key ? next.average.key : next.years[next.years.length - 1].key);
  return (
    <div className="foi-views">
      {views.length > 1 && (
        <label className="foi-measure small">
          <span className="muted">Figure</span>
          <select value={v.series} onChange={(e) => setColKey(sameKind(views.find((x) => x.series === e.target.value)!))}>
            {views.map((x) => <option key={x.series} value={x.series}>{x.series || "Figures"}</option>)}
          </select>
        </label>
      )}
      <div className="seg" role="tablist" aria-label="Map view">
        <button role="tab" aria-selected={current === v && colKey === v.average.key} className={colKey === v.average.key ? "on" : ""} onClick={() => setColKey(v.average.key)}>
          <strong>Average per year</strong><span>{v.years[0].period}–{v.years[v.years.length - 1].period}</span>
        </button>
        <button role="tab" aria-selected={colKey === v.change.key} className={colKey === v.change.key ? "on" : ""} onClick={() => setColKey(v.change.key)}>
          <strong>% change</strong><span>{v.years[0].period} → {v.years[v.years.length - 1].period}</span>
        </button>
        <label className={`seg-year ${year ? "on" : ""}`}>
          <strong>One year</strong>
          <select aria-label="Year" value={year?.key ?? ""} onChange={(e) => e.target.value && setColKey(e.target.value)}>
            {!year && <option value="">Choose…</option>}
            {v.years.map((y) => <option key={y.key} value={y.key}>{y.period}</option>)}
          </select>
        </label>
      </div>
      {others.length > 0 && (<><div className="tiny muted">Other figures</div>{chips(others)}</>)}
    </div>
  );
}

/** A small bar chart of one area's figure in each year. */
export function YearBars({ view, values }: { view: YearView; values: Record<string, number | null> }) {
  const pts = view.years.map((y) => ({ label: y.period!, v: values[y.key] ?? null }));
  const max = Math.max(0, ...pts.map((p) => p.v ?? 0));
  if (!max) return null;
  const W = 300, H = 70, gap = 8, bw = (W - gap * (pts.length - 1)) / pts.length;
  return (
    <figure className="foi-bars" aria-label={`${view.series || "Figure"} by year`}>
      <svg viewBox={`0 -16 ${W} ${H + 40}`} role="img">
        {pts.map((p, i) => {
          const h = p.v === null ? 0 : Math.max(2, (p.v / max) * H);
          const x = i * (bw + gap);
          return (
            <g key={p.label}>
              {p.v === null ? <text x={x + bw / 2} y={H - 2} textAnchor="middle" className="nd">–</text>
                : <rect x={x} y={H - h} width={bw} height={h} rx={3} className={i === pts.length - 1 ? "last" : ""} />}
              {p.v !== null && <text x={x + bw / 2} y={H - h - 4} textAnchor="middle" className="val">{fmtValue(p.v, view.years[i])}</text>}
              <text x={x + bw / 2} y={H + 16} textAnchor="middle" className="yr">{p.label}</text>
            </g>
          );
        })}
      </svg>
      {values[view.change.key] !== null && values[view.change.key] !== undefined && (
        <figcaption className="tiny muted">{fmtValue(values[view.change.key]!, view.change)} from {view.years[0].period} to {view.years[view.years.length - 1].period}</figcaption>
      )}
    </figure>
  );
}
