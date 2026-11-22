import { useMemo, useState } from "react";
import { campaignLine, displayName, fmtValue, inScope, ldOf, mainServer, summary, type LdScope, type Ranked } from "./analysis";
import { type YearView } from "./periods";
import { csv, download, slug } from "../lib/format";
import { type Column, type Dataset, type Reference, type Target } from "./types";
/** The Lib Dem seats panel: each held or target seat, the body serving it, its figure and a campaign line. */

/** The figure as it reads in a sentence: "stop and search (average per year, 2021/22–2024/25)". */
export function measureName(d: Dataset, col: Column, view: YearView | null): string {
  const base = view?.series || d.title;
  if (col.derived === "average" && view) return `${base} (average per year, ${view.years[0].period}–${view.years[view.years.length - 1].period})`;
  if (col.derived === "change") return base;
  if (col.period) return `${base} in ${col.period}`;
  return col.label;
}

/**
 * Lib Dem seats first: for each held (or target) seat, the body that mainly serves it, its figure and rank, a
 * summary, and a campaign line to copy. Worst first, so the strongest angles are at the top.
 */
export function LibDemPanel({ ref_, d, col, rows, stats, ph, view, scope, setScope, plural, names, onPick }: {
  ref_: Reference; d: Dataset; col: Column | undefined; rows: Ranked[]; stats: ReturnType<typeof summary>; ph: boolean; view: YearView | null;
  scope: LdScope; setScope: (s: LdScope) => void; plural: string; names: Map<string, Target>; onPick: (seat: string, server: string) => void;
}) {
  const [all, setAll] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const inResponse = useMemo(() => new Set(d.rows.map((r) => r.code)), [d.rows]);
  const servers = useMemo(() => mainServer(ref_, d.geography, inResponse), [ref_, d.geography, inResponse]);
  const counts = { held: ref_.seats.filter((s) => ldOf(s) === "held").length, target: ref_.seats.filter((s) => ldOf(s) === "target").length };
  if (!col || !counts.held) return null;
  const byCode = new Map(rows.map((r) => [r.target.code, r]));
  const values = rows.map((r) => r.value).filter((v): v is number => v !== null);
  const worseHigh = col.direction !== "higher_better";
  const measure = measureName(d, col, view);
  const list = ref_.seats.filter((s) => inScope(s, scope)).map((s) => {
    const srv = servers.get(s.code);
    const r = srv ? byCode.get(srv.code) : undefined;
    const raw = srv ? names.get(srv.code)?.name ?? srv.code : null;
    const server = raw && displayName(d.geography, raw);
    return {
      seat: s, srv, r, server,
      line: server ? campaignLine({ seat: s.name, server, measure, col, value: r?.value ?? null, suppressed: r?.suppressed, values, median: stats.median, plural, perHead: ph }) : null,
    };
  }).sort((a, b) => {
    const av = a.r?.value ?? null, bv = b.r?.value ?? null;
    if (av === null || bv === null) return Number(av === null) - Number(bv === null);
    return worseHigh ? bv - av : av - bv;
  });
  const withFig = list.filter((x) => x.r?.value !== null && x.r?.value !== undefined);
  const mid = col.change ? 0 : stats.mean;
  const above = mid === null ? 0 : withFig.filter((x) => x.r!.value! > mid).length;
  const below = mid === null ? 0 : withFig.filter((x) => x.r!.value! < mid).length;
  const shown = all ? list : list.slice(0, 8);
  const who = scope === "held" ? "Lib Dem seats" : scope === "target" ? "Lib Dem target seats" : "Lib Dem seats and targets";
  const copy = async (text: string, id: string) => {
    try { await navigator.clipboard.writeText(text); setCopied(id); setTimeout(() => setCopied(null), 1500); } catch { /* clipboard blocked */ }
  };
  const exportCsv = () => {
    const head = ["Seat", "Status", "MP", "Served by", measure, "Rank", "Campaign line"];
    const body = list.map((x) => [x.seat.name, ldOf(x.seat), x.seat.mp, x.server, x.r?.suppressed ?? x.r?.value ?? null, x.r?.rank ? `${x.r.rank} of ${stats.n}` : null, x.line]);
    download(`${slug(d.title)}-lib-dem-seats.csv`, csv([head, ...body]));
  };
  return (
    <section className="foi-ld">
      <div className="foi-ld-head">
        <span className="tiny muted">Which seats</span>
        <div className="seg mini" role="tablist" aria-label="Which seats">
          <button className={scope === "held" ? "on" : ""} onClick={() => setScope("held")}>Held ({counts.held})</button>
          {counts.target > 0 && <button className={scope === "target" ? "on" : ""} onClick={() => setScope("target")}>Targets ({counts.target})</button>}
          {counts.target > 0 && <button className={scope === "both" ? "on" : ""} onClick={() => setScope("both")}>Both</button>}
        </div>
      </div>
      <p className="small">
        {withFig.length ? (
          col.change
            ? <><strong>{above}</strong> of {withFig.length} {who} are served by {plural} where it <strong>rose</strong>; <strong>{below}</strong> where it fell.</>
            : <><strong>{above}</strong> of {withFig.length} {who} are served by {plural} <strong>above the average</strong> ({fmtValue(stats.mean, col, ph)}); {below} below.</>
        ) : <>None of the {who} are served by anyone with a figure in this response.</>}
        {list.length > withFig.length && <span className="muted"> {list.length - withFig.length} with no figure.</span>}
      </p>
      <table className="foi-ld-table">
        <thead><tr><th>Seat</th><th>Served by</th><th className="num">{col.change ? "Change" : "Figure"}</th><th aria-label="Copy" /></tr></thead>
        <tbody>
          {shown.map((x) => (
            <tr key={x.seat.code} onClick={() => x.srv && onPick(x.seat.code, x.srv.code)}>
              <td><strong>{x.seat.name}</strong>{ldOf(x.seat) === "target" && <span className="tag tgt">target</span>}<div className="tiny muted">{x.seat.mp}</div></td>
              <td className="small">{x.server ?? <span className="muted">none in response</span>}{x.r?.rank && <div className="tiny muted">{x.r.rank} of {stats.n}</div>}</td>
              <td className="num">{x.r?.suppressed ? <span className="muted">withheld</span> : x.r?.value !== null && x.r?.value !== undefined ? <strong>{fmtValue(x.r.value, col, ph)}</strong> : "–"}</td>
              <td>{x.line && <button className="icon-btn copy" title={x.line} aria-label={`Copy a line for ${x.seat.name}`} onClick={(e) => { e.stopPropagation(); copy(x.line!, x.seat.code); }}>{copied === x.seat.code ? "✓" : "⧉"}</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="foi-ld-foot">
        {list.length > 8 && <button className="link-btn small" onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show all ${list.length}`}</button>}
        <button className="link-btn small" onClick={() => copy(list.map((x) => x.line).filter(Boolean).join("\n"), "all")}>{copied === "all" ? "✓ Copied" : "Copy all lines"}</button>
        <button className="link-btn small" onClick={exportCsv}>Download CSV</button>
      </div>
      <p className="tiny muted">Worst first. Click a seat to see it on the map. Each seat is matched to the {plural.replace(/s$/, "")} that mainly serves it.</p>
    </section>
  );
}
