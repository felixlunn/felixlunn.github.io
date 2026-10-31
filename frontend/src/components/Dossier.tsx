import { useMemo } from "react";
import type { DashboardData } from "../types";
import { groupMean, profileMetrics, rankOf, similarity, stats, topN } from "../lib/analytics";
import { textOn } from "../lib/colors";
import { csv, download, fmt, rankText, slug } from "../lib/format";

interface Props {
  data: DashboardData;
  index: number;
  onClose: () => void;
  onSelect: (i: number) => void;
  onShowMetric: (id: string) => void;
}

export default function Dossier({ data, index, onClose, onSelect, onShowMetric }: Props) {
  const seat = data.seats[index];
  const group = data.peer_groups.find((g) => g.id === seat.peer_group);
  const val = (id: string) => data.values[id]?.[index] ?? null;
  const metricById = useMemo(() => new Map(data.metrics.map((m) => [m.id, m])), [data]);

  const standouts = useMemo(() => {
    return data.metrics
      .filter((m) => m.theme !== "politics" && m.unit !== "people")
      .map((m) => {
        const v = data.values[m.id][index];
        if (v === null) return null;
        const s = stats(data.values[m.id]);
        return { m, v, z: (v - s.mean) / s.sd };
      })
      .filter((x): x is NonNullable<typeof x> => x !== null)
      .sort((a, b) => Math.abs(b.z) - Math.abs(a.z))
      .slice(0, 8);
  }, [data, index]);

  const twins = useMemo(() => {
    const ids = profileMetrics(data.metrics);
    return ids.length ? topN(data, similarity(data, index, ids, "euclidean"), 5, { exclude: index }) : [];
  }, [data, index]);

  const exportDossier = () => {
    const rows: (string | number | null)[][] = [["theme", "metric", "unit", "value", "national", "rank", "of", "peer_group_average", "source"]];
    for (const m of data.metrics) {
      const r = rankOf(data.values[m.id], index);
      rows.push([m.theme, m.label, m.unit, r.value, m.national, r.rank, r.of, groupMean(data, m.id, seat.peer_group), m.source]);
    }
    download(`dossier-${slug(seat.name)}.csv`, csv([[seat.name, seat.code], [], ...rows]));
  };

  const majority = val("majority_pct");
  const turnout = val("turnout");

  return (
    <aside className="dossier" aria-label={`Constituency dossier: ${seat.name}`}>
      <header className="dossier-head">
        <div>
          <div className="eyebrow">{[seat.region, seat.country].filter((x, i, a) => x && a.indexOf(x) === i).join(" · ")}</div>
          <h2>{seat.name}</h2>
          <div className="tiny muted">{seat.code}</div>
        </div>
        <button className="icon close" onClick={onClose} aria-label="Close dossier">×</button>
      </header>

      <div className="dossier-body">
        <section className="mp">
          {seat.party && (
            <span className="party" style={{ background: seat.party_colour ?? "var(--surface-3)", color: textOn(seat.party_colour) }}>
              {seat.party}
            </span>
          )}
          {seat.mp && <span className="mp-name">{seat.mp}</span>}
          <div className="kpis">
            {majority !== null && <div className="kpi"><span className="kpi-v">{fmt({ unit: "%", decimals: 1 }, majority)}</span><span className="kpi-l">Majority 2024</span></div>}
            {turnout !== null && <div className="kpi"><span className="kpi-v">{fmt({ unit: "%", decimals: 1 }, turnout)}</span><span className="kpi-l">Turnout 2024</span></div>}
            {val("population") !== null && <div className="kpi"><span className="kpi-v">{fmt({ unit: "people", decimals: 0 }, val("population"))}</span><span className="kpi-l">Residents (2021)</span></div>}
          </div>
          {seat.result_2024 && <div className="small muted">2024: {seat.result_2024}{seat.second_party_2024 ? ` · runner-up ${seat.second_party_2024}` : ""}</div>}
        </section>

        {group && (
          <section>
            <h3>Peer group</h3>
            <p className="small"><strong>{group.label}</strong> ({group.size} seats): {group.description}.</p>
          </section>
        )}

        {standouts.length > 0 && (
          <section>
            <h3>Where it stands out</h3>
            <p className="tiny muted">Largest differences from the average seat, in standard deviations.</p>
            <ul className="devs">
              {standouts.map(({ m, v, z }) => {
                const w = Math.min(Math.abs(z), 3) / 3 * 50;
                return (
                  <li key={m.id}>
                    <button className="link dev-label" onClick={() => onShowMetric(m.id)}>{m.label}</button>
                    <span className="dev-bar" title={`${z >= 0 ? "+" : ""}${z.toFixed(1)} SD`}>
                      <span className="axis" />
                      <span className={z >= 0 ? "pos" : "neg"} style={z >= 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }} />
                    </span>
                    <span className="num small">{fmt(m, v)}<span className="muted"> vs {fmt(m, m.national)}</span></span>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        <section>
          <h3>By theme</h3>
          {data.themes.map((t) => {
            const ms = data.metrics.filter((m) => m.theme === t.id);
            if (!ms.length) return null;
            return (
              <details key={t.id} className="theme-block">
                <summary>{t.label}</summary>
                <table className="metric-table compact">
                  <thead>
                    <tr><th scope="col">Metric</th><th className="num" scope="col">Seat</th><th className="num" scope="col">National</th><th className="num" scope="col">Peers</th></tr>
                  </thead>
                  <tbody>
                    {ms.map((m) => {
                      const r = rankOf(data.values[m.id], index);
                      return (
                        <tr key={m.id} onClick={() => onShowMetric(m.id)} title={rankText(r.rank, r.of)}>
                          <td>{m.label}<div className="m-rank">{rankText(r.rank, r.of)}</div></td>
                          <td className="num strong">{fmt(m, r.value)}</td>
                          <td className="num muted">{fmt(m, m.national)}</td>
                          <td className="num muted">{fmt(m, groupMean(data, m.id, seat.peer_group))}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </details>
            );
          })}
        </section>

        {twins.length > 0 && (
          <section>
            <h3>Demographic twins</h3>
            <ol className="rank-list">
              {twins.map((t, k) => (
                <li key={t.code}>
                  <span className="rk">{k + 1}</span>
                  <button className="link grow" onClick={() => onSelect(t.index)}>{t.name}</button>
                  <span className="tiny muted">{data.seats[t.index].party ?? ""}</span>
                  <span className="num">{(t.score * 100).toFixed(0)}%</span>
                </li>
              ))}
            </ol>
          </section>
        )}

        <div className="actions no-print">
          <button className="btn" onClick={exportDossier}>Download dossier (CSV)</button>
          <button className="btn" onClick={() => {
            document.querySelectorAll<HTMLDetailsElement>(".dossier details").forEach((d) => (d.open = true));
            window.print();
          }}>Print / save PDF</button>
        </div>
        <p className="tiny muted">
          {metricById.has("population") ? "Census figures cover England & Wales (2021). " : ""}
          National = all seats with data combined.
        </p>
      </div>
    </aside>
  );
}
