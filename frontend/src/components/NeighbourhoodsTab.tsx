import { useMemo } from "react";
import type { DashboardData, Metric, NeighbourhoodFile } from "../types";
import { csv, download, fmt, slug } from "../lib/format";

interface Props {
  data: DashboardData;
  seat: number | null;
  file: NeighbourhoodFile | null;
  status: "idle" | "loading" | "error";
  metricId: string | null;
  setMetricId: (id: string) => void;
}

/** "Top 4% in England & Wales" style label for an LSOA percentile, or null if unremarkable. */
export function pctLabel(p: number | null | undefined): string | null {
  if (p === null || p === undefined) return null;
  if (p >= 90) return `Top ${Math.max(1, 100 - p)}%`;
  if (p <= 10) return `Bottom ${Math.max(1, p)}%`;
  return null;
}

export default function NeighbourhoodsTab({ data, seat, file, status, metricId, setMetricId }: Props) {
  const available = data.neighbourhoods?.seats ?? [];
  const seatCode = seat !== null ? data.seats[seat].code : null;

  const metrics = useMemo(() => {
    if (!file) return [] as Metric[];
    const ids = new Set(file.metrics);
    return data.metrics.filter((m) => ids.has(m.id));
  }, [data, file]);
  const metric = metrics.find((m) => m.id === metricId) ?? null;

  const rows = useMemo(() => {
    if (!file || !metric) return [];
    const v = file.values[metric.id], p = file.pct[metric.id];
    return file.lsoas.map((l, k) => ({ l, v: v[k], p: p[k] })).sort((a, b) => (b.v ?? -Infinity) - (a.v ?? -Infinity));
  }, [file, metric]);

  if (seat === null) {
    return <div className="tab-body"><p className="small muted">Set your office in the header, or pick a seat on the map, to see its neighbourhoods.</p></div>;
  }
  if (!seatCode || !available.includes(seatCode)) {
    return (
      <div className="tab-body">
        <p className="small"><strong>{data.seats[seat].name}</strong> doesn't have neighbourhood profiles.</p>
        <p className="small muted">
          Neighbourhood (LSOA) census profiles are published for the {available.length} seats held by Lib Dem MPs in England and Wales
          (Census 2021 small-area data doesn't cover Scotland or Northern Ireland).
        </p>
      </div>
    );
  }
  if (status === "error") return <div className="tab-body"><p className="small bad">Couldn't load the neighbourhood data for this seat.</p></div>;
  if (!file) return <div className="tab-body"><p className="small muted">Loading neighbourhoods…</p></div>;

  const themeLabel = (id: string) => data.themes.find((t) => t.id === id)?.label ?? id;
  const byTheme = [...new Set(metrics.map((m) => m.theme))];

  const exportCsv = () => download(`${slug(file.name)}-neighbourhoods.csv`, csv([
    ["lsoa_code", "lsoa_name", "ward", "council", ...metrics.flatMap((m) => [m.label, `${m.label} (E&W percentile)`])],
    ...file.lsoas.map((l, k) => [l.code, l.name, l.ward, l.council, ...metrics.flatMap((m) => [file.values[m.id][k], file.pct[m.id][k]])]),
  ]));

  return (
    <div className="tab-body">
      <p className="small"><strong>{file.name}</strong>: {file.lsoas.length} neighbourhoods (LSOAs, about 1,500 residents each), Census 2021.</p>
      <label className="field">
        <span>Show</span>
        <select value={metric?.id ?? ""} onChange={(e) => setMetricId(e.target.value)}>
          {byTheme.map((t) => (
            <optgroup key={t} label={themeLabel(t)}>
              {metrics.filter((m) => m.theme === t).map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </optgroup>
          ))}
        </select>
      </label>
      {metric && (
        <section className="card">
          <div className="rank-head">
            <h3>{metric.label}</h3>
            <button className="link small" onClick={exportCsv}>Download all (CSV)</button>
          </div>
          <p className="tiny muted">Highest first. Badges compare each neighbourhood with all 35,672 in England and Wales.</p>
          <ol className="rank-list nb">
            {rows.map((r, k) => {
              const badge = pctLabel(r.p);
              return (
                <li key={r.l.code}>
                  <span className="rk">{k + 1}</span>
                  <span className="grow">
                    <span className="nb-ward">{r.l.ward ?? r.l.name}</span>
                    <span className="tiny muted"> {r.l.name}</span>
                  </span>
                  {badge && <span className={`nb-badge ${r.p! >= 90 ? "hi" : "lo"}`}>{badge}</span>}
                  <span className="num">{fmt(metric, r.v)}</span>
                </li>
              );
            })}
          </ol>
        </section>
      )}
    </div>
  );
}
