import { useMemo } from "react";
import type { Choropleth, DashboardData, Metric } from "../types";
import { PARTY_ID, partyStyle } from "../lib/parties";
import { rankOf } from "../lib/analytics";
import { csv, download, fmt, rankText, slug } from "../lib/format";
import Strip from "./Strip";

interface Props {
  data: DashboardData;
  theme: string;
  setTheme: (t: string) => void;
  metric: Metric;
  partyMode: boolean;
  parties: Choropleth;
  setMetric: (id: string) => void;
  selected: number | null;
  onSelect: (i: number) => void;
}

export default function ThemesTab({ data, theme, setTheme, metric, partyMode, parties, setMetric, selected, onSelect }: Props) {
  const themeMetrics = data.metrics.filter((m) => m.theme === theme);
  const hasParties = !!parties.categories?.length;
  const themesWithData = data.themes.filter((t) => data.metrics.some((m) => m.theme === t.id) || (t.id === "politics" && hasParties));
  const selParty = selected !== null && data.seats[selected].party ? partyStyle(data.seats[selected].party!, data.seats[selected].party_colour) : null;
  const themeInfo = data.themes.find((t) => t.id === theme);

  const ranking = useMemo(() => {
    const v = data.values[metric.id];
    return data.seats
      .map((s, i) => ({ i, s, v: v[i] }))
      .filter((r): r is { i: number; s: typeof r.s; v: number } => r.v !== null)
      .sort((a, b) => b.v - a.v);
  }, [data, metric]);

  const selPos = selected === null ? -1 : ranking.findIndex((r) => r.i === selected);
  const top = ranking.slice(0, 8);
  const bottom = ranking.slice(-5);

  const exportRanking = () =>
    download(
      `${slug(metric.label)}-ranking.csv`,
      csv([["rank", "code", "constituency", "region", "party", metric.label], ...ranking.map((r, k) => [k + 1, r.s.code, r.s.name, r.s.region, r.s.party, r.v])]),
    );

  return (
    <div className="tab-body">
      <div className="chips" role="tablist" aria-label="Themes">
        {themesWithData.map((t) => (
          <button key={t.id} role="tab" aria-selected={t.id === theme} className={`chip ${t.id === theme ? "on" : ""}`} onClick={() => setTheme(t.id)}>
            {t.label}
          </button>
        ))}
      </div>
      {themeInfo && <p className="muted small">{themeInfo.description}</p>}

      <table className="metric-table">
        <thead>
          <tr>
            <th scope="col">Metric</th>
            {selected !== null && <th scope="col" className="num">Seat</th>}
            <th scope="col" className="num">National</th>
            <th scope="col"><span className="sr-only">Distribution</span></th>
          </tr>
        </thead>
        <tbody>
          {theme === "politics" && hasParties && (
            <tr className={partyMode ? "active" : ""} onClick={() => setMetric(PARTY_ID)} tabIndex={0}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setMetric(PARTY_ID)} aria-label="Show party map">
              <td><div className="m-label">Party</div><div className="m-rank">Electoral map</div></td>
              {selected !== null && <td className="num strong">{selParty?.label ?? "–"}</td>}
              <td className={`num ${selected !== null ? "muted" : "strong"}`}>{parties.categories![0].label}</td>
              <td />
            </tr>
          )}
          {themeMetrics.map((m) => {
            const r = selected !== null ? rankOf(data.values[m.id], selected) : null;
            return (
              <tr key={m.id} className={!partyMode && m.id === metric.id ? "active" : ""} onClick={() => setMetric(m.id)} tabIndex={0}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setMetric(m.id)} aria-label={`Show ${m.label} on the map`}>
                <td>
                  <div className="m-label">{m.label}</div>
                  {r && <div className="m-rank">{rankText(r.rank, r.of)}</div>}
                </td>
                {r && <td className="num strong">{fmt(m, r.value)}</td>}
                <td className={`num ${r ? "muted" : "strong"}`}>{fmt(m, m.national)}</td>
                <td>
                  <Strip values={data.values[m.id]} selected={selected} national={m.national}
                    label={`Distribution of ${m.label} across ${m.coverage} seats`} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {partyMode && parties.categories ? (
        <section className="card">
          <h3>Seats by party</h3>
          <p className="small">Each seat is coloured by its current MP's party, which picks up by-elections and defections since July 2024.</p>
          <ol className="rank-list">
            {parties.categories.map((c) => (
              <li key={c.label} className={selParty?.label === c.label ? "sel" : ""}>
                <span className="swatch" style={{ background: c.colour }} />
                <span style={{ flex: 1 }}>{c.label}</span>
                <span className="num">{c.count}</span>
              </li>
            ))}
          </ol>
        </section>
      ) : (
      <section className="card">
        <h3>{metric.label}</h3>
        <p className="small">{metric.description}</p>
        <p className="small muted">
          Source: {metric.source} · {metric.coverage} seats with data · national {fmt(metric, metric.national)}
          {metric.unit !== "%" && metric.unit !== "people" ? ` ${metric.unit}` : ""}
        </p>
        <div className="rank-head">
          <h4>Highest</h4>
          <button className="link" onClick={exportRanking}>Download full ranking (CSV)</button>
        </div>
        <ol className="rank-list">
          {top.map((r, k) => (
            <li key={r.s.code} className={r.i === selected ? "sel" : ""}>
              <span className="rk">{k + 1}</span>
              <button className="link" onClick={() => onSelect(r.i)}>{r.s.name}</button>
              <span className="num">{fmt(metric, r.v)}</span>
            </li>
          ))}
        </ol>
        {selPos >= top.length && selPos < ranking.length - bottom.length && (
          <ol className="rank-list" start={selPos + 1}>
            <li className="sel">
              <span className="rk">{selPos + 1}</span>
              <span>{ranking[selPos].s.name}</span>
              <span className="num">{fmt(metric, ranking[selPos].v)}</span>
            </li>
          </ol>
        )}
        <h4>Lowest</h4>
        <ol className="rank-list">
          {bottom.map((r, k) => (
            <li key={r.s.code} className={r.i === selected ? "sel" : ""}>
              <span className="rk">{ranking.length - bottom.length + k + 1}</span>
              <button className="link" onClick={() => onSelect(r.i)}>{r.s.name}</button>
              <span className="num">{fmt(metric, r.v)}</span>
            </li>
          ))}
        </ol>
      </section>
      )}
    </div>
  );
}
