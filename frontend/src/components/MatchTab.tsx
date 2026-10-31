import type { DashboardData } from "../types";
import { stats, type Scored } from "../lib/analytics";
import { csv, download, fmt } from "../lib/format";

interface Props {
  data: DashboardData;
  targets: Record<string, number>;
  setTargets: (t: Record<string, number>) => void;
  results: Scored[];
  selected: number | null;
  onSelect: (i: number) => void;
}

export default function MatchTab({ data, targets, setTargets, results, selected, onSelect }: Props) {
  const byId = new Map(data.metrics.map((m) => [m.id, m]));
  const ids = Object.keys(targets).filter((k) => byId.has(k));
  const available = data.metrics.filter((m) => !(m.id in targets));

  const add = (id: string) => {
    const m = byId.get(id);
    if (m) setTargets({ ...targets, [id]: Math.round((m.national ?? stats(data.values[id]).mean) * 10) / 10 });
  };
  const fromSelected = () => {
    if (selected === null) return;
    const next: Record<string, number> = {};
    for (const id of ids) {
      const v = data.values[id][selected];
      if (v !== null) next[id] = v;
    }
    setTargets(next);
  };

  return (
    <div className="tab-body">
      <p className="small">
        Describe the kind of place you are looking for (for example "35% private renters and 30% aged 20-34") and
        find the constituencies that match it best. Misses are measured in standard deviations, so every metric counts equally.
      </p>
      <div className="weights">
        {ids.map((id) => {
          const m = byId.get(id)!;
          const st = stats(data.values[id]);
          const step = m.unit === "people" ? 1000 : (st.max - st.min) / 200 || 0.1;
          return (
            <div key={id} className="weight">
              <div className="weight-head">
                <span>{m.label}</span>
                <input className="num-input" type="number" step={step} value={Number(targets[id].toFixed(m.decimals))} aria-label={`Target for ${m.label}`}
                  onChange={(e) => setTargets({ ...targets, [id]: Number(e.target.value) })} />
                <button className="icon" aria-label={`Remove ${m.label}`} onClick={() => {
                  const next = { ...targets };
                  delete next[id];
                  setTargets(next);
                }}>×</button>
              </div>
              <input type="range" min={st.min} max={st.max} step={step} value={targets[id]} aria-label={`Target slider for ${m.label}`}
                onChange={(e) => setTargets({ ...targets, [id]: Number(e.target.value) })} />
              <div className="range-ends tiny muted"><span>{fmt(m, st.min)}</span><span>national {fmt(m, m.national)}</span><span>{fmt(m, st.max)}</span></div>
            </div>
          );
        })}
      </div>
      <div className="row2">
        <label className="field">
          <span>Add a criterion</span>
          <select value="" onChange={(e) => e.target.value && add(e.target.value)}>
            <option value="" disabled>Choose…</option>
            {data.themes.map((t) => {
              const ms = available.filter((m) => m.theme === t.id);
              return ms.length ? (
                <optgroup key={t.id} label={t.label}>
                  {ms.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
                </optgroup>
              ) : null;
            })}
          </select>
        </label>
        <div className="field">
          <span>&nbsp;</span>
          <button className="btn" disabled={selected === null || !ids.length} onClick={fromSelected}
            title="Set every target to the selected constituency's value">Use selected seat's values</button>
        </div>
      </div>

      {results.length > 0 && (
        <section className="card">
          <div className="rank-head">
            <h3>Best matches</h3>
            <button className="link" onClick={() => download("profile-matches.csv", csv([
              ["rank", "code", "constituency", "region", "party", "distance_sd", ...ids.map((i) => byId.get(i)!.label)],
              ...results.map((r, k) => [k + 1, r.code, r.name, data.seats[r.index].region, data.seats[r.index].party, r.score.toFixed(4), ...ids.map((i) => data.values[i][r.index])]),
            ]))}>CSV</button>
          </div>
          <ol className="rank-list">
            {results.slice(0, 15).map((r, k) => (
              <li key={r.code} className={r.index === selected ? "sel" : ""}>
                <span className="rk">{k + 1}</span>
                <span className="grow">
                  <button className="link" onClick={() => onSelect(r.index)}>{r.name}</button>
                  <span className="tiny muted"> {ids.map((i) => `${byId.get(i)!.label} ${fmt(byId.get(i)!, data.values[i][r.index])}`).join(" · ")}</span>
                </span>
                <span className="num" title="RMS distance in standard deviations">{r.score.toFixed(2)} SD</span>
              </li>
            ))}
          </ol>
          <p className="tiny muted">Distance = root-mean-square miss across criteria, in standard deviations. 0 = exact match.</p>
        </section>
      )}
    </div>
  );
}
