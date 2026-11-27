import { useEffect, useMemo, useState } from "react";
import { usePersistentState } from "../lib/usePersistentState";
import { canPerHead, fmtValue, forSeat, libDemServed, overallRate, points, ranked, summary, type LdScope } from "./analysis";
import { outlier, vsMedian } from "./stats";
import { mapShapes } from "./shapes";
import { withYearViews } from "./periods";
import type { Backend } from "./backend";
import FoiMap, { type MapItem } from "./FoiMap";
import { targets } from "./match";
import { csv, download, slug } from "../lib/format";
import { areasOf, GEO, hospitalTrusts } from "./geographies";
import { type Dataset, type Reference } from "./types";
import { ViewPicker, YearBars } from "./YearViews";
import { LibDemPanel } from "./LibDemPanel";
import { useMapFilter } from "./useMapFilter";
import { bands, loadKeys, saveKeys } from "./key";
/** Dataset view: one FOI response on the map, with its Lib Dem seats, ranking and details. */

export function DatasetView({ d: saved, ref_, shapes, seat, backend, canEdit, onDeleted, onPickSeat, scope, setScope }: {
  d: Dataset; ref_: Reference; shapes: GeoJSON.FeatureCollection; seat: string | null; backend: Backend; canEdit: boolean; onDeleted: () => void;
  onPickSeat: (code: string) => void;
  scope: LdScope;
  setScope: (s: LdScope) => void;
}) {
  // Several years: an average per year and a % change are worked out and offered as the standard maps.
  const { d, views } = useMemo(() => withYearViews(saved), [saved]);
  const [colKey, setColKey] = useState(views[0]?.change.key ?? d.columns[0]?.key ?? "");
  const col = d.columns.find((c) => c.key === colKey);
  const view = views.find((v) => [v.average.key, v.change.key, ...v.years.map((y) => y.key)].includes(colKey)) ?? null;
  const [perHead, setPerHead] = useState(false);
  const ph = perHead && canPerHead(d, col);
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const rows = useMemo(() => ranked(ref_, d, colKey, ph), [ref_, d, colKey, ph]);
  const stats = useMemo(() => summary(rows), [rows]);
  const flagged = useMemo(() => rows.map((r) => ({ r, o: outlier(r.value, stats) })).filter((x) => x.o !== null), [rows, stats]);
  const flaggedSet = useMemo(() => new Set(flagged.map((x) => x.r.target.code)), [flagged]);

  // The key's own boundaries, if the user set some for this figure (remembered per dataset and figure).
  const [keys, setKeys] = useState(loadKeys);
  const keyId = `${saved.id}|${colKey}${ph ? "|per100k" : ""}`;
  const customBreaks = keys[keyId] ?? null;
  const setCustomBreaks = (b: number[] | null) => setKeys((k) => {
    const next = { ...k };
    if (b) next[keyId] = b; else delete next[keyId];
    saveKeys(next);
    return next;
  });

  const [tab, setTab] = usePersistentState("foi.tab", "ld", ["ld", "all", "about"] as const);
  const ld = useMemo(() => libDemServed(ref_, d.geography, new Set(d.rows.map((r) => r.code)), scope), [ref_, d.geography, d.rows, scope]);
  // Map filters (up / down, Lib Dem seats): one rule for the map, ranking, outliers and counts.
  const { dir, setDir, ldOnly, setLdOnly, band, setBand, directional: filtering, isChange, pass, visible, active: activeFilter, clear: clearFilters } = useMapFilter(rows, col, stats.mean, ld, customBreaks);
  const bandLabel = band !== null && customBreaks ? bands(customBreaks, (v) => fmtValue(v, col, ph)).find((b) => b.k === band)?.label : null;
  // The full ranking folds away (it's long for trusts and courts); it opens by itself when the map is filtered.
  const [rankOpen, setRankOpen] = usePersistentState("foi.rankOpen", "closed", ["open", "closed"] as const);
  useEffect(() => { if (activeFilter) setRankOpen("open"); }, [activeFilter, setRankOpen]);
  // Unusual figures: name the three furthest from the median; the rest are marked in the ranking.
  const unusual = useMemo(() => {
    const all = flagged.filter(({ r }) => pass(r));
    const far = (v: number | null) => (v === null || stats.median === null ? 0 : Math.abs(v - stats.median));
    return { top: [...all].sort((a, b) => far(b.r.value) - far(a.r.value)).slice(0, 3), all };
  }, [flagged, pass, stats.median]);
  const overall = ph ? overallRate(rows) : null;
  // How far from the middle: a ratio for levels ("2.3× the median"), a difference for changes ("+12 points above").
  const vsMid = (v: number): string | null => {
    if (!col?.change) return vsMedian(v, stats.median);
    if (stats.median === null) return null;
    const diff = v - stats.median;
    const unit = col.change.mode === "percent" ? " points" : "";
    return Math.abs(diff) < 1e-9 ? "at the median" : `${fmtValue(Math.abs(diff), { ...col, change: undefined, unit: col.change.mode === "percent" ? "other" : col.unit })}${unit} ${diff > 0 ? "above" : "below"} the median`;
  };
  const tByCode = useMemo(() => new Map(targets(ref_, d.geography).map((t) => [t.code, t])), [ref_, d.geography]);
  const rowByCode = useMemo(() => new Map(d.rows.map((r) => [r.code, r])), [d.rows]);
  const seatLinks = useMemo(() => (seat ? forSeat(ref_, d.geography, seat) : []), [ref_, d.geography, seat]);
  const highlight = useMemo(() => new Set(seatLinks.map((l) => l.code)), [seatLinks]);
  // What to shade: official boundaries (forces, NHS areas), official trust catchments, or approximate court areas.
  const layerShapes = useMemo(() => mapShapes(ref_, shapes, d.geography, new Set(rowByCode.keys())), [ref_, shapes, d.geography, rowByCode]);
  const mapNote = GEO[d.geography].mapNote ?? null;

  const unit = ph ? " per 100,000 residents" : "";
  // Trusts with an official catchment are always drawn (as shapes); other places only when in the response.
  const withCatchment = useMemo(() => new Set(d.geography === "nhs_trust" ? hospitalTrusts(ref_).filter((t) => t.catchment).map((t) => t.code) : []), [ref_, d.geography]);
  const rankedByCode = useMemo(() => new Map(rows.map((r) => [r.target.code, r])), [rows]);
  const items: MapItem[] = useMemo(() => {
    const val = rankedByCode;
    const base = GEO[d.geography].isArea ? [...tByCode.values()].map((t) => ({ code: t.code, name: t.name, sub: undefined as string | undefined, lat: undefined as number | undefined, lon: undefined as number | undefined }))
      // Courts and trusts: only those in the response (others would clutter the shaded areas as empty dots).
      : points(ref_, d.geography).filter((p) => rowByCode.has(p.code) || withCatchment.has(p.code))
        .map((p) => ({ code: p.code, name: p.name, sub: p.sub, lat: p.lat, lon: p.lon }));
    return base.map((b) => {
      const r = val.get(b.code);
      const o = r ? outlier(r.value, stats) : null;
      const label = !r ? "Not in this response" : r.suppressed ? `Withheld (${r.suppressed})`
        : `${fmtValue(r.value, col, ph)}${unit}${r.rank ? ` · ${r.rank} of ${stats.n}` : ""}${o ? ` · unusually ${o}` : ""}`;
      return { ...b, value: r?.value ?? null, label };
    });
  }, [rankedByCode, tByCode, ref_, d.geography, col, ph, unit, stats, rowByCode, withCatchment]);
  const notIn = useMemo(() => [...tByCode.values()].filter((t) => !rowByCode.has(t.code)), [tByCode, rowByCode]);

  const seatName = seat ? ref_.seats.find((s) => s.code === seat)?.name : null;
  const sel = selected ? tByCode.get(selected) : null;
  const selRow = selected ? rowByCode.get(selected) : null;
  const linkedSeats = (code: string) => {
    if (GEO[d.geography].isArea) {
      const a = areasOf(ref_, d.geography).find((x) => x.code === code);
      return a?.seats.length ?? 0;
    }
    return null;
  };

  const exportCsv = () => {
    const head = [GEO[d.geography].label, "Code", "Name in response", ...d.columns.map((c) => c.label)];
    const body = d.rows.map((r) => [tByCode.get(r.code)?.name ?? r.code, r.code, r.source_name, ...d.columns.map((c) => r.suppressed?.[c.key] ?? r.values[c.key])]);
    download(`${slug(d.title)}.csv`, csv([head, ...body]));
  };
  const openFile = async () => { try { window.open(await backend.fileUrl(d.file_path!), "_blank", "noopener"); } catch (e) { alert((e as Error).message); } };
  const remove = async () => {
    if (!confirm(`Delete “${d.title}” for everyone on the team? This can't be undone.`)) return;
    try { await backend.remove(d); onDeleted(); } catch (e) { alert((e as Error).message); }
  };

  const shown = rows.filter((r) => pass(r) && (!filter || r.target.name.toLowerCase().includes(filter.toLowerCase())));
  const dimmed = useMemo(() => (activeFilter ? new Set(items.map((i) => i.code).filter((c) => !visible.has(c))) : undefined), [activeFilter, items, visible]);
  return (
    <div className="foi-main">
      <div className="foi-map-wrap">
        {mapNote && <div className="foi-map-note tiny">{mapNote}</div>}
        <FoiMap shapes={layerShapes} items={items} reverse={col?.direction === "higher_better"} selected={selected} highlight={highlight} flagged={flaggedSet} dimmed={dimmed} onSelect={setSelected}
          title={`${col?.label ?? ""}${unit}`} format={(v) => fmtValue(v, col, ph)}
          customBreaks={customBreaks} onCustomBreaks={setCustomBreaks} band={band} onBand={setBand} />
      </div>
      <section className="foi-detail">
        <header className="foi-dh">
          <div className="foi-dh-text">
            <h2>{d.title}</h2>
            <div className="tiny muted">{[GEO[d.geography].label, d.authority, d.period || d.received_on].filter(Boolean).join(" · ")}</div>
          </div>
          <details className="foi-menu">
            <summary aria-label="More actions" title="Download, original file, delete">⋯</summary>
            <div className="foi-menu-list">
              <button onClick={exportCsv}>Download the data (CSV)</button>
              {d.file_path && <button onClick={openFile}>Open the original file</button>}
              {canEdit && <button className="bad" onClick={remove}>Delete this dataset</button>}
            </div>
          </details>
        </header>

        <ViewPicker d={d} views={views} colKey={colKey} setColKey={setColKey} />
        <div className="foi-filters" role="group" aria-label="Filter the map">
          {filtering && (
            <span className="seg mini">
              <button className={dir === "all" ? "on" : ""} onClick={() => setDir("all")}>All</button>
              <button className={dir === "up" ? "on" : ""} onClick={() => setDir("up")}>{isChange ? "▲ Up" : "Above avg"}</button>
              <button className={dir === "down" ? "on" : ""} onClick={() => setDir("down")}>{isChange ? "▼ Down" : "Below avg"}</button>
            </span>
          )}
          <button className={`chip ld ${ldOnly ? "on" : ""}`} aria-pressed={ldOnly} onClick={() => setLdOnly(!ldOnly)}
            title="Only those serving at least one of these seats">{scope === "held" ? "Lib Dem seats" : scope === "target" ? "Lib Dem targets" : "Lib Dem seats & targets"}</button>
          {canPerHead(d, col) && (
            <button className={`chip ${perHead ? "on" : ""}`} aria-pressed={perHead} onClick={() => setPerHead(!perHead)}
              title="Estimated from the residents of the seats each area covers">Per 100,000</button>
          )}
        </div>
        {activeFilter && (
          <p className="foi-showing">
            Showing <strong>{visible.size}</strong> of {rows.length}
            {filtering && dir !== "all" && <> · {isChange ? (dir === "up" ? "increased" : "decreased") : `${dir === "up" ? "above" : "below"} the average (${fmtValue(stats.mean, col, ph)})`}</>}
            {bandLabel && <> · {bandLabel}</>}
            {ldOnly && <> · serving {scope === "held" ? "a Lib Dem seat" : scope === "target" ? "a Lib Dem target" : "a Lib Dem seat or target"}</>}
            {" "}<button className="link-btn" onClick={clearFilters}>clear</button>
          </p>
        )}

        {sel && (
          <div className="foi-selected">
            <div className="foi-selected-head">
              <h3 className="foi-h">{sel.name}</h3>
              <button className="icon-btn" onClick={() => setSelected(null)} aria-label="Close">✕</button>
            </div>
            {sel.sub && <div className="tiny muted">{sel.sub}</div>}
            {view && selRow && <YearBars view={view} values={selRow.values} />}
            {!selRow ? <p className="small muted">Not in this response.</p> : (
              <>
                <table className="foi-kv"><tbody>
                  {col && <tr><th>{col.label}</th><td><strong>{selRow.suppressed?.[col.key] ? `Withheld (${selRow.suppressed[col.key]})` : fmtValue(selRow.values[col.key] ?? null, col)}</strong>
                    {(() => { const r = rankedByCode.get(sel.code); return r?.rank ? <span className="tiny muted"> · {r.rank} of {stats.n}</span> : null; })()}</td></tr>}
                  {ld.has(sel.code) && <tr><th>Lib Dem seats it serves</th><td>{ld.get(sel.code)!.join(", ")}</td></tr>}
                  {sel.population ? <tr><th>Residents (est.)</th><td>{sel.population.toLocaleString("en-GB")}</td></tr> : null}
                </tbody></table>
                <details className="tiny foi-allfig">
                  <summary>All figures</summary>
                  <table className="foi-kv"><tbody>
                    {d.columns.map((c) => <tr key={c.key}><th>{c.label}</th><td>{selRow.suppressed?.[c.key] ? `Withheld (${selRow.suppressed[c.key]})` : fmtValue(selRow.values[c.key] ?? null, c)}</td></tr>)}
                    <tr><th>Name in the response</th><td>{selRow.source_name}</td></tr>
                    {linkedSeats(sel.code) !== null && <tr><th>Seats it covers</th><td>{linkedSeats(sel.code)}</td></tr>}
                  </tbody></table>
                </details>
              </>
            )}
          </div>
        )}


        <div className="foi-tabs" role="tablist">
          {([["ld", "Lib Dem seats"], ["all", `All ${GEO[d.geography].plural}`], ["about", "About"]] as const).map(([k, label]) => (
            <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{label}</button>
          ))}
        </div>

        {tab === "ld" && (
          <>
            {seat && (
              <div className="foi-seatbox">
                <h3 className="foi-h">For {seatName}</h3>
                {!seatLinks.length ? <p className="small muted">Nothing in this geography is linked to the seat.</p> : (() => {
                  const withRow = seatLinks.filter((l) => rowByCode.has(l.code));
                  const without = seatLinks.filter((l) => !rowByCode.has(l.code));
                  return (
                    <>
                      {withRow.length > 0 && (
                        <ul>
                          {withRow.slice(0, 12).map((l) => {
                            const r = rankedByCode.get(l.code);
                            return (
                              <li key={l.code}>
                                <button className="link-btn" onClick={() => setSelected(l.code)}>{tByCode.get(l.code)?.name ?? l.code}</button>{" "}
                                <span className="tiny muted">({l.why})</span>:{" "}
                                {!r || r.suppressed ? <span className="small">withheld{r?.suppressed ? ` (${r.suppressed})` : ""}</span> : <strong>{fmtValue(r.value, col, ph)}{unit}</strong>}
                                {r?.rank && <span className="tiny muted"> · {r.rank} of {stats.n}{r.value !== null && vsMid(r.value) ? `; ${vsMid(r.value)}` : ""}</span>}
                                {r && outlier(r.value, stats) && <span className={`tag ${outlier(r.value, stats)}`}>unusually {outlier(r.value, stats)}</span>}
                              </li>
                            );
                          })}
                          {withRow.length > 12 && <li className="tiny muted">and {withRow.length - 12} more in the wider area</li>}
                        </ul>
                      )}
                      {without.length > 0 && (
                        <p className="tiny muted">
                          {withRow.length ? "Also serving the seat, but not in this response: " : "None of those serving the seat are in this response: "}
                          {without.slice(0, 6).map((l) => tByCode.get(l.code)?.name ?? l.code).join(", ")}{without.length > 6 ? ` and ${without.length - 6} more` : ""}.
                        </p>
                      )}
                    </>
                  );
                })()}
              </div>
            )}

            <LibDemPanel ref_={ref_} d={d} col={col} rows={rows} stats={stats} ph={ph} view={view} scope={scope} setScope={setScope}
              plural={GEO[d.geography].plural} names={tByCode} onPick={(seatCode, server) => { onPickSeat(seatCode); setSelected(server); }} />
          </>
        )}

        {tab === "all" && (
          <>
            <p className="foi-statline small">
              <strong>{stats.n}</strong> of {tByCode.size} with a figure
              {!ph && col?.unit !== "rate" && col?.unit !== "percent" && <> · total <strong>{fmtValue(stats.total, col)}</strong></>}
              {overall !== null && <> · overall <strong>{fmtValue(overall, col, true)}</strong> per 100,000</>}
              {" "}· average <strong>{fmtValue(stats.mean, col, ph || !!stats.mean && stats.mean % 1 !== 0)}</strong>
              {" "}· median <strong>{fmtValue(stats.median, col, ph)}</strong>
              {" "}· range <strong>{fmtValue(stats.min, col, ph)}</strong> to <strong>{fmtValue(stats.max, col, ph)}</strong>
              {stats.withheld > 0 && <> · {stats.withheld} withheld</>}
            </p>
            {unusual.top.length > 0 && (
              <div className="foi-unusual small">
                <span className="muted">Most unusual</span>
                <ul>
                  {unusual.top.map(({ r, o }) => (
                    <li key={r.target.code}>
                      <button className="link-btn" title={vsMid(r.value!) ?? ""} onClick={() => setSelected(r.target.code)}>{r.target.name}</button>
                      <span className={`tag ${o}`}>{o === "high" ? "▲" : "▼"} {fmtValue(r.value, col, ph)}</span>
                    </li>
                  ))}
                </ul>
                {unusual.all.length > 3 && <span className="tiny muted">and {unusual.all.length - 3} more, marked ▲ ▼ in the ranking</span>}
              </div>
            )}
            <div className="foi-table-head">
              <button className="foi-fold" aria-expanded={rankOpen === "open"} onClick={() => setRankOpen(rankOpen === "open" ? "closed" : "open")}>
                <span className="foi-fold-arrow" aria-hidden="true">{rankOpen === "open" ? "▾" : "▸"}</span>
                Ranking of {activeFilter ? `${shown.length} of ${rows.length}` : `all ${rows.length}`} {GEO[d.geography].plural}
                <span className="tiny muted"> · {col?.label}{unit}</span>
              </button>
              {rankOpen === "open" && <input type="search" placeholder="Find" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Find in the ranking" />}
            </div>
            {rankOpen === "open" && <table className="foi-rank">
              <thead><tr><th className="rk">#</th><th>{GEO[d.geography].label}</th><th className="num">{ph ? "Per 100,000" : "Figure"}</th></tr></thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.target.code} className={`${highlight.has(r.target.code) ? "mine" : ""} ${selected === r.target.code ? "sel" : ""}`} onClick={() => setSelected(r.target.code)}>
                    <td className="muted rk">{r.rank ?? ""}</td>
                    <td>{r.target.name}{ld.has(r.target.code) && <span className="tag ld" title={`Serves ${ld.get(r.target.code)!.join(", ")}`}>LD</span>}{flaggedSet.has(r.target.code) && <span className={`tag ${outlier(r.value, stats)}`}>{outlier(r.value, stats) === "high" ? "▲" : "▼"}</span>}</td>
                    <td className="num">{r.suppressed ? <span className="muted">withheld ({r.suppressed})</span> : fmtValue(r.value, col, ph)}</td>
                  </tr>
                ))}
              </tbody>
            </table>}
          </>
        )}

        {tab === "about" && (
          <div className="foi-about">
            <table className="foi-kv"><tbody>
              <tr><th>Each row is a</th><td>{GEO[d.geography].label}</td></tr>
              {d.authority && <tr><th>Answered by</th><td>{d.authority}</td></tr>}
              {d.foi_reference && <tr><th>FOI reference</th><td>{d.foi_reference}</td></tr>}
              {d.period && <tr><th>Period covered</th><td>{d.period}</td></tr>}
              {d.requested_on && <tr><th>Request sent</th><td>{d.requested_on}</td></tr>}
              {d.received_on && <tr><th>Response received</th><td>{d.received_on}</td></tr>}
              {d.builtin ? <tr><th>Source</th><td>{d.builtin}: public data, updated with the site's data (last {d.created_at.slice(0, 10)})</td></tr>
                : <tr><th>Added by</th><td>{d.created_by_email || "unknown"} on {d.created_at.slice(0, 10)}</td></tr>}
            </tbody></table>
            {d.notes && <p className="small foi-notes">{d.notes}</p>}
            {notIn.length > 0 && notIn.length < tByCode.size && (
              <details className="small foi-missing">
                <summary>{notIn.length} {notIn.length === 1 ? GEO[d.geography].plural.replace(/s$/, "") : GEO[d.geography].plural} not in this response</summary>
                <p className="tiny">{notIn.slice(0, 60).map((t) => t.name).join(", ")}{notIn.length > 60 ? ` and ${notIn.length - 60} more` : ""}</p>
              </details>
            )}
            {d.unmatched.length > 0 && (
              <details className="small foi-unmatched">
                <summary>{d.unmatched.length} {d.unmatched.length === 1 ? "row" : "rows"} in the file couldn't be matched (not mapped)</summary>
                <ul>{d.unmatched.map((u, i) => <li key={i}>{u.source_name}</li>)}</ul>
              </details>
            )}
            <p className="tiny muted">
              Unusual figures (▲ ▼, dashed on the map) are more than 1.5 times the middle half's spread beyond it (Tukey's rule), with at least 8 figures.
              {canPerHead(d, col) && " Per 100,000 figures use residents estimated from the seats each area covers."}
              {mapNote && ` ${mapNote}`}
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
