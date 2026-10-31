import type { DashboardData } from "../types";
import type { Scored } from "../lib/analytics";
import { csv, download, slug } from "../lib/format";

export interface TwinSettings {
  themes: string[];
  method: "euclidean" | "cosine";
  scope: "uk" | "country" | "region";
  n: number;
}

interface Props {
  data: DashboardData;
  selected: number | null;
  settings: TwinSettings;
  setSettings: (s: TwinSettings) => void;
  results: Scored[];
  metricCount: number;
  onSelect: (i: number) => void;
}

export default function TwinsTab({ data, selected, settings, setSettings, results, metricCount, onSelect }: Props) {
  const themes = data.themes.filter((t) => data.metrics.some((m) => m.theme === t.id && m.unit === "%"));
  const seat = selected !== null ? data.seats[selected] : null;
  const toggle = (id: string) => {
    const has = settings.themes.includes(id);
    const next = has ? settings.themes.filter((t) => t !== id) : [...settings.themes, id];
    if (next.length) setSettings({ ...settings, themes: next });
  };

  return (
    <div className="tab-body">
      <p className="small">
        Find the constituencies that look most like a chosen seat. Each seat is described by {metricCount} standardised
        percentage metrics from the themes ticked below, and seats are ranked by how close they are across all of them.
      </p>
      {!seat && <div className="empty">Select a constituency on the map or search for one to find its twins.</div>}

      <fieldset className="field">
        <legend>Compare on</legend>
        <div className="checks">
          {themes.map((t) => (
            <label key={t.id} className="check">
              <input type="checkbox" checked={settings.themes.includes(t.id)} onChange={() => toggle(t.id)} /> {t.label}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="row2">
        <label className="field">
          <span>Similarity</span>
          <select value={settings.method} onChange={(e) => setSettings({ ...settings, method: e.target.value as TwinSettings["method"] })}>
            <option value="euclidean">Closest levels (Euclidean)</option>
            <option value="cosine">Same shape (cosine)</option>
          </select>
        </label>
        <label className="field">
          <span>Search in</span>
          <select value={settings.scope} onChange={(e) => setSettings({ ...settings, scope: e.target.value as TwinSettings["scope"] })}>
            <option value="uk">All seats</option>
            <option value="country">Same nation{seat ? ` (${seat.country})` : ""}</option>
            <option value="region">Same region{seat?.region ? ` (${seat.region})` : ""}</option>
          </select>
        </label>
      </div>

      {seat && (
        <section className="card">
          <div className="rank-head">
            <h3>Twins of {seat.name}</h3>
            <button className="link" onClick={() => download(`twins-${slug(seat.name)}.csv`, csv([["rank", "code", "constituency", "region", "party", "similarity"],
              ...results.map((r, k) => [k + 1, r.code, r.name, data.seats[r.index].region, data.seats[r.index].party, r.score.toFixed(4)])]))}>
              CSV
            </button>
          </div>
          {results.length === 0 && <p className="small muted">No comparable seats: this seat lacks data for the chosen themes (Census 2021 covers England & Wales only).</p>}
          <ol className="rank-list twins">
            {results.map((r, k) => {
              const s = data.seats[r.index];
              return (
                <li key={r.code}>
                  <span className="rk">{k + 1}</span>
                  <span className="grow">
                    <button className="link" onClick={() => onSelect(r.index)}>{r.name}</button>
                    <span className="tiny muted"> {s.party ? `${s.party} · ` : ""}{s.region || s.country}</span>
                  </span>
                  <span className="bar" aria-label={`Similarity ${(r.score * 100).toFixed(0)}%`}>
                    <span style={{ width: `${Math.max(0, r.score) * 100}%` }} />
                  </span>
                  <span className="num">{(r.score * 100).toFixed(0)}%</span>
                </li>
              );
            })}
          </ol>
          <p className="tiny muted">
            {settings.method === "euclidean"
              ? "Score = 1 / (1 + RMS distance in standard deviations). 100% would be identical."
              : "Score = cosine similarity of standardised profiles: 100% means the same pattern of above/below-average traits."}
          </p>
        </section>
      )}
    </div>
  );
}
