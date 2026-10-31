import type { DashboardData } from "../types";
import type { Scored } from "../lib/analytics";
import { csv, download, slug } from "../lib/format";

export const PRESETS: { name: string; weights: Record<string, number> }[] = [
  { name: "Cost-of-living vulnerability", weights: { private_rented: 0.3, deprived_2plus: 0.3, claimant_rate: 0.2, no_central_heating: 0.1, inactive_sick: 0.1 } },
  { name: "Housing pressure", weights: { private_rented: 0.3, overcrowded: 0.4, social_rented: 0.1, flats: 0.2 } },
  { name: "Health & care strain", weights: { age_65_plus: 0.3, bad_health: 0.3, disabled: 0.2, unpaid_carers: 0.2 } },
  { name: "Skills gap", weights: { no_qualifications: 0.4, level4_plus: -0.3, inactive_sick: 0.3 } },
  { name: "Crime & justice pressure", weights: { crime_rate: 0.4, crime_asb: 0.2, outcome_no_suspect: 0.4 } },
  { name: "Commuter dependency", weights: { commute_30km_plus: 0.4, commute_public: 0.3, commute_car: 0.3 } },
  { name: "Young renters", weights: { age_20_34: 0.4, private_rented: 0.4, level4_plus: 0.2 } },
];

interface Props {
  data: DashboardData;
  weights: Record<string, number>;
  setWeights: (w: Record<string, number>) => void;
  ranking: Scored[];
  selected: number | null;
  onSelect: (i: number) => void;
}

export default function IndexTab({ data, weights, setWeights, ranking, selected, onSelect }: Props) {
  const byId = new Map(data.metrics.map((m) => [m.id, m]));
  const ids = Object.keys(weights).filter((k) => byId.has(k));
  const available = data.metrics.filter((m) => !(m.id in weights) && m.unit !== "people");
  const selPos = selected === null ? -1 : ranking.findIndex((r) => r.index === selected);

  const applyPreset = (name: string) => {
    const p = PRESETS.find((x) => x.name === name);
    if (p) setWeights(Object.fromEntries(Object.entries(p.weights).filter(([k]) => byId.has(k))));
  };

  return (
    <div className="tab-body">
      <p className="small">
        Build a composite index from any metrics. Each metric is converted to a z-score (how many standard deviations
        from the average seat), multiplied by its weight, and averaged. Negative weights count a metric against the index.
      </p>
      <label className="field">
        <span>Start from a preset</span>
        <select value="" onChange={(e) => applyPreset(e.target.value)}>
          <option value="" disabled>Choose a preset…</option>
          {PRESETS.filter((p) => Object.keys(p.weights).some((k) => byId.has(k))).map((p) => (
            <option key={p.name} value={p.name}>{p.name}</option>
          ))}
        </select>
      </label>

      <div className="weights">
        {ids.map((id) => {
          const m = byId.get(id)!;
          const w = weights[id];
          return (
            <div key={id} className="weight">
              <div className="weight-head">
                <span>{m.label}</span>
                <span className="num">{w > 0 ? "+" : ""}{w.toFixed(1)}</span>
                <button className="icon" aria-label={`Remove ${m.label}`} onClick={() => {
                  const next = { ...weights };
                  delete next[id];
                  setWeights(next);
                }}>×</button>
              </div>
              <input type="range" min={-1} max={1} step={0.1} value={w} aria-label={`Weight for ${m.label}`}
                onChange={(e) => setWeights({ ...weights, [id]: Number(e.target.value) })} />
            </div>
          );
        })}
      </div>
      <label className="field">
        <span>Add a metric</span>
        <select value="" onChange={(e) => e.target.value && setWeights({ ...weights, [e.target.value]: 0.5 })}>
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

      {ranking.length > 0 && (
        <section className="card">
          <div className="rank-head">
            <h3>Index ranking</h3>
            <button className="link" onClick={() => download(`custom-index-${slug(ids.join("-"))}.csv`, csv([
              ["rank", "code", "constituency", "region", "party", "index_score", ...ids.map((i) => byId.get(i)!.label)],
              ...ranking.map((r, k) => [k + 1, r.code, r.name, data.seats[r.index].region, data.seats[r.index].party, r.score.toFixed(4),
                ...ids.map((i) => data.values[i][r.index])]),
            ]))}>Download all (CSV)</button>
          </div>
          {selPos >= 0 && <p className="small"><strong>{data.seats[selected!].name}</strong> ranks {selPos + 1} of {ranking.length} (score {ranking[selPos].score.toFixed(2)}).</p>}
          <ol className="rank-list">
            {ranking.slice(0, 15).map((r, k) => (
              <li key={r.code} className={r.index === selected ? "sel" : ""}>
                <span className="rk">{k + 1}</span>
                <button className="link grow" onClick={() => onSelect(r.index)}>{r.name}</button>
                <span className="num">{r.score.toFixed(2)}</span>
              </li>
            ))}
          </ol>
          <p className="tiny muted">Score in standard deviations above (+) or below (−) the average seat. {ranking.length} seats have data for every chosen metric.</p>
        </section>
      )}
    </div>
  );
}
