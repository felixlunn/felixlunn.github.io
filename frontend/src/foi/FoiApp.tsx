import { useCallback, useEffect, useMemo, useState } from "react";
import { campaignLine, canPerHead, fmtValue, forSeat, inScope, ldOf, libDemServed, mainServer, overallRate, points, ranked, summary, type LdScope, type Ranked } from "./analysis";
import { outlier, vsMedian } from "./stats";
import { jurisdictionOf, nearestAreas } from "./cells";
import { withYearViews, type YearView } from "./periods";
import type { Backend, User } from "./backend";
import FoiMap, { type MapItem } from "./FoiMap";
import { targets } from "./match";
import Upload from "./Upload";
import { csv, download, slug } from "../lib/format";
import { DEPARTMENTS, GEOGRAPHY_LABEL, IS_AREA, type Column, type Dataset, type Department, type NewDataset, type Reference, type Target } from "./types";

const PLURAL: Record<Dataset["geography"], string> = { police_force: "police force areas", court: "courts and tribunals", nhs_trust: "NHS trusts", health_area: "NHS areas" };

export default function FoiApp({ backend, ref_, shapes }: { backend: Backend; ref_: Reference; shapes: GeoJSON.FeatureCollection }) {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [recovery, setRecovery] = useState(false);
  const [membership, setMembership] = useState<{ member: boolean; admin: boolean; error?: string } | null>(null);

  useEffect(() => {
    backend.user().then(setUser);
    return backend.onChange((u, ev) => { setUser(u); if (ev === "recovery") setRecovery(true); });
  }, [backend]);
  useEffect(() => {
    setMembership(null);
    if (user) backend.membership().then(setMembership).catch((e: Error) => setMembership({ member: false, admin: false, error: e.message }));
  }, [backend, user]);

  if (user === undefined) return <div className="boot">Checking your login…</div>;
  if (recovery && user) return <SetPassword backend={backend} onDone={() => setRecovery(false)} />;
  if (!user) return <Login backend={backend} />;
  if (!membership) return <div className="boot">Checking your access…</div>;
  if (!membership.member) {
    return (
      <div className="foi-gate">
        <div className="foi-gate-box">
          <h1>No access yet</h1>
          {membership.error ? (
            <p className="small">You're signed in as <strong>{user.email}</strong>, but the team list couldn't be checked: <span className="bad">{membership.error}</span>.
              If it mentions permission, re-run <code>supabase/schema.sql</code> in the Supabase SQL Editor.</p>
          ) : (
            <p className="small">You're signed in as <strong>{user.email}</strong>, but this address isn't on the FOI research team list. Ask the person who invited you to add it.</p>
          )}
          <button className="btn" onClick={() => backend.signOut()}>Sign out</button>
        </div>
      </div>
    );
  }
  return <Workspace backend={backend} user={user} admin={membership.admin} ref_={ref_} shapes={shapes} />;
}

function Login({ backend }: { backend: Backend }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try { await backend.signIn(email, password); } catch (err) { setMsg({ text: (err as Error).message, bad: true }); } finally { setBusy(false); }
  };
  const reset = async () => {
    if (!email.includes("@")) { setMsg({ text: "Enter your email address first, then choose “Forgotten password”.", bad: true }); return; }
    try { await backend.sendReset(email); setMsg({ text: "If that address is on the team, a link to set a new password is on its way." }); }
    catch (err) { setMsg({ text: (err as Error).message, bad: true }); }
  };
  return (
    <div className="foi-gate">
      <form className="foi-gate-box" onSubmit={submit}>
        <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden="true"><rect width="32" height="32" rx="6" fill="var(--accent)" /><path d="M9 8h14M9 14h10M9 20h12M9 26h7" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" /></svg>
        <h1>FOI research</h1>
        <p className="small muted">For the research team only. Accounts are by invitation.</p>
        {backend.kind === "demo" && <p className="tiny warn">Demo mode: no database is set up, so anything uploaded stays in this browser. Any email and password will do.</p>}
        <label className="foi-field"><span>Email</span><input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
        <label className="foi-field"><span>Password</span><input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
        {msg && <p className={`small ${msg.bad ? "bad" : ""}`} role="status">{msg.text}</p>}
        <button className="btn primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        <button type="button" className="link-btn tiny" onClick={reset}>Forgotten password</button>
        <a className="tiny" href="./">Back to the dashboard</a>
      </form>
    </div>
  );
}

function SetPassword({ backend, onDone }: { backend: Backend; onDone: () => void }) {
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (pw.length < 10) return setErr("Use at least 10 characters.");
    if (pw !== pw2) return setErr("The two passwords don't match.");
    try { await backend.setPassword(pw); onDone(); } catch (x) { setErr((x as Error).message); }
  };
  return (
    <div className="foi-gate">
      <form className="foi-gate-box" onSubmit={submit}>
        <h1>Choose a password</h1>
        <label className="foi-field"><span>New password</span><input type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} /></label>
        <label className="foi-field"><span>Again</span><input type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} /></label>
        {err && <p className="small bad">{err}</p>}
        <button className="btn primary">Save password</button>
      </form>
    </div>
  );
}

function Workspace({ backend, user, admin, ref_, shapes }: { backend: Backend; user: User; admin: boolean; ref_: Reference; shapes: GeoJSON.FeatureCollection }) {
  const [dept, setDept] = useState<Department>(() => (["policing", "justice", "health"].includes(location.hash.slice(1)) ? location.hash.slice(1) as Department : "policing"));
  const [datasets, setDatasets] = useState<Dataset[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [seat, setSeat] = useState<string>(() => { try { return localStorage.getItem("foi.seat") ?? ""; } catch { return ""; } });

  const reload = useCallback(() => {
    setDatasets(null);
    backend.list(dept).then((ds) => { setDatasets(ds); setError(null); setActiveId((id) => (ds.some((d) => d.id === id) ? id : ds[0]?.id ?? null)); })
      .catch((e: Error) => { setError(e.message); setDatasets([]); });
  }, [backend, dept]);
  useEffect(reload, [reload]);
  useEffect(() => { history.replaceState(null, "", `#${dept}`); }, [dept]);
  useEffect(() => { try { localStorage.setItem("foi.seat", seat); } catch { /* per visit only */ } }, [seat]);

  const active = datasets?.find((d) => d.id === activeId) ?? null;
  const info = DEPARTMENTS.find((d) => d.id === dept)!;

  const save = async (d: NewDataset, file: File | null) => {
    const created = await backend.create(d, file);
    setUploading(false);
    reload();
    setActiveId(created.id);
  };

  return (
    <div className="app foi">
      <header className="topbar">
        <a className="brand" href="./" title="Back to the constituency dashboard">
          <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden="true"><rect width="32" height="32" rx="6" fill="var(--accent)" /><path d="M9 8h14M9 14h10M9 20h12M9 26h7" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" /></svg>
          <div>
            <h1>FOI research</h1>
            <div className="tiny muted">Data Dashboard · team only</div>
          </div>
        </a>
        <SeatPicker ref_={ref_} seat={seat} setSeat={setSeat} />
        <div className="foi-user tiny">
          <span className="muted">{user.email}{backend.kind === "demo" ? " (demo)" : ""}</span>
          <button className="link-btn" onClick={() => backend.signOut()}>Sign out</button>
        </div>
      </header>
      {backend.kind === "demo" && <div className="demo-banner">Demo mode: uploads stay in this browser only. Set up Supabase (see the README) to share them with the team.</div>}
      <div className="foi-body">
        <aside className="sidebar foi-side">
          <nav className="tabs" role="tablist">
            {DEPARTMENTS.map((d) => (
              <button key={d.id} role="tab" aria-selected={d.id === dept} className={d.id === dept ? "on" : ""} onClick={() => { setDept(d.id); setActiveId(null); }}>{d.label}</button>
            ))}
          </nav>
          <div className="foi-side-body">
            <p className="small muted">{info.blurb}</p>
            <button className="btn primary block" onClick={() => setUploading(true)}>Upload an FOI response</button>
            {error && <p className="small bad">Couldn't load datasets: {error}</p>}
            <h3 className="foi-h">{info.label} datasets</h3>
            {datasets === null ? <p className="small muted">Loading…</p> : !datasets.length ? (
              <p className="small muted">None yet. Upload the first FOI response for {info.label.toLowerCase()}.</p>
            ) : (
              <ul className="foi-list">
                {datasets.map((d) => (
                  <li key={d.id}>
                    <button className={d.id === activeId ? "on" : ""} onClick={() => setActiveId(d.id)}>
                      <span className="foi-list-title">{d.title}</span>
                      <span className="tiny muted">{GEOGRAPHY_LABEL[d.geography]} · {d.rows.length} rows · {d.period || d.received_on || d.created_at.slice(0, 10)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>
        {active ? (
          <DatasetView key={active.id} d={active} ref_={ref_} shapes={shapes} seat={seat || null} backend={backend} onPickSeat={setSeat}
            canEdit={admin || active.created_by === user.id} onDeleted={reload} />
        ) : (
          <div className="foi-main foi-empty">
            <FoiMap shapes={null} items={[]} reverse={false} selected={null} highlight={new Set()} onSelect={() => {}} />
          </div>
        )}
      </div>
      {uploading && <Upload ref_={ref_} department={dept} onCancel={() => setUploading(false)} onSave={save} />}
    </div>
  );
}

function SeatPicker({ ref_, seat, setSeat }: { ref_: Reference; seat: string; setSeat: (s: string) => void }) {
  const [q, setQ] = useState("");
  const current = ref_.seats.find((s) => s.code === seat);
  const hits = q.length >= 2 ? ref_.seats.filter((s) => `${s.name} ${s.mp ?? ""}`.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => Number(!ldOf(a)) - Number(!ldOf(b))).slice(0, 8) : [];
  return (
    <div className="foi-seat">
      {current ? (
        <div className="foi-seat-on small">
          <span className="tiny muted">Seat</span> <strong>{current.name}</strong>{current.mp ? ` · ${current.mp}` : ""}
          <button className="link-btn tiny" onClick={() => setSeat("")}>change</button>
        </div>
      ) : (
        <>
          <input type="search" placeholder="Your seat or MP, to see what serves it" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Choose a seat" />
          {hits.length > 0 && (
            <ul className="foi-seat-hits">
              {hits.map((s) => (
                <li key={s.code}><button onClick={() => { setSeat(s.code); setQ(""); }}>
                  {s.name}{ldOf(s) && <span className={`tag ${ldOf(s) === "held" ? "ld" : "tgt"}`}>{ldOf(s) === "held" ? "LD" : "LD target"}</span>}
                  {s.mp ? <span className="tiny muted"> · {s.mp}</span> : null}
                </button></li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

function DatasetView({ d: saved, ref_, shapes, seat, backend, canEdit, onDeleted, onPickSeat }: {
  d: Dataset; ref_: Reference; shapes: GeoJSON.FeatureCollection; seat: string | null; backend: Backend; canEdit: boolean; onDeleted: () => void;
  onPickSeat: (code: string) => void;
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

  // Filters on the average and % change maps: above / below average (or increase / decrease), and Lib Dem seats.
  const [dir, setDir] = useState<"all" | "up" | "down">("all");
  const [ldOnly, setLdOnly] = useState(false);
  const [tab, setTab] = useState<"ld" | "all" | "about">(() => { try { return (localStorage.getItem("foi.tab") as "ld" | "all" | "about") || "ld"; } catch { return "ld"; } });
  useEffect(() => { try { localStorage.setItem("foi.tab", tab); } catch { /* per visit */ } }, [tab]);
  const [scope, setScope] = useState<LdScope>(() => { try { return (localStorage.getItem("foi.ldScope") as LdScope) || "held"; } catch { return "held"; } });
  useEffect(() => { try { localStorage.setItem("foi.ldScope", scope); } catch { /* per visit */ } }, [scope]);
  const filtering = !!col?.derived;
  const ld = useMemo(() => libDemServed(ref_, d.geography, new Set(d.rows.map((r) => r.code)), scope), [ref_, d.geography, d.rows, scope]);
  const isChange = col?.derived === "change";
  const pass = (r: Ranked) => {
    if (ldOnly && !ld.has(r.target.code)) return false;
    if (!filtering) return true;
    if (dir === "all") return true;
    if (r.value === null) return false;
    const mid = isChange ? 0 : stats.mean ?? 0;
    return dir === "up" ? r.value > mid : r.value < mid;
  };
  const visible = new Set(rows.filter(pass).map((r) => r.target.code));
  const activeFilter = (filtering && dir !== "all") || ldOnly;
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
  const layer = d.geography === "police_force" || d.geography === "court" ? "police" : "health";
  // What to shade: official boundaries (forces, NHS areas), official trust catchments, or approximate court areas.
  const layerShapes = useMemo((): GeoJSON.FeatureCollection | null => {
    const of = (l: string) => ({ ...shapes, features: shapes.features.filter((f) => f.properties?.layer === l) });
    if (IS_AREA[d.geography]) return of(layer);
    if (d.geography === "nhs_trust") return of("trust");
    const lands = Object.fromEntries(of("land").features.map((f) => [String(f.properties?.code), f.geometry]));
    const inResponse = (ref_.points.courts ?? []).filter((c) => rowByCode.has(c.id))
      .map((c) => ({ code: c.id, lon: c.lon, lat: c.lat, jurisdiction: jurisdictionOf(c.area) }));
    return nearestAreas(inResponse, lands);
  }, [shapes, d.geography, layer, ref_, rowByCode]);
  const mapNote = d.geography === "court"
    ? "Court areas are approximate: HMCTS doesn't publish catchments, so each court covers the land nearest to it among the courts in this response."
    : d.geography === "nhs_trust"
      ? "Shaded areas are each acute trust's catchment (OHID: where most local residents are admitted). Trusts without one (mental health, community, ambulance) are dots."
      : null;

  const unit = ph ? " per 100,000 residents" : "";
  const items: MapItem[] = useMemo(() => {
    const val = new Map(rows.map((r) => [r.target.code, r]));
    const base = IS_AREA[d.geography] ? [...tByCode.values()].map((t) => ({ code: t.code, name: t.name, sub: undefined as string | undefined, lat: undefined as number | undefined, lon: undefined as number | undefined }))
      // Courts and trusts: only those in the response (others would clutter the shaded areas as empty dots).
      : points(ref_, d.geography).filter((p) => rowByCode.has(p.code) || d.geography === "nhs_trust" && !!ref_.points.trusts?.find((t) => t.code === p.code)?.catchment)
        .map((p) => ({ code: p.code, name: p.name, sub: p.sub, lat: p.lat, lon: p.lon }));
    return base.map((b) => {
      const r = val.get(b.code);
      const o = r ? outlier(r.value, stats) : null;
      const label = !r ? "Not in this response" : r.suppressed ? `Withheld (${r.suppressed})`
        : `${fmtValue(r.value, col, ph)}${unit}${r.rank ? ` · ${r.rank} of ${stats.n}` : ""}${o ? ` · unusually ${o}` : ""}`;
      return { ...b, value: r?.value ?? null, label };
    });
  }, [rows, tByCode, ref_, d.geography, col, ph, unit, stats, rowByCode]);
  const notIn = useMemo(() => [...tByCode.values()].filter((t) => !rowByCode.has(t.code)), [tByCode, rowByCode]);

  const seatName = seat ? ref_.seats.find((s) => s.code === seat)?.name : null;
  const sel = selected ? tByCode.get(selected) : null;
  const selRow = selected ? rowByCode.get(selected) : null;
  const linkedSeats = (code: string) => {
    if (IS_AREA[d.geography]) {
      const a = (layer === "police" ? ref_.layers.police.areas : ref_.layers.health.areas).find((x) => x.code === code);
      return a?.seats.length ?? 0;
    }
    return null;
  };

  const exportCsv = () => {
    const head = [GEOGRAPHY_LABEL[d.geography], "Code", "Name in response", ...d.columns.map((c) => c.label)];
    const body = d.rows.map((r) => [tByCode.get(r.code)?.name ?? r.code, r.code, r.source_name, ...d.columns.map((c) => r.suppressed?.[c.key] ?? r.values[c.key])]);
    download(`${slug(d.title)}.csv`, csv([head, ...body]));
  };
  const openFile = async () => { try { window.open(await backend.fileUrl(d.file_path!), "_blank", "noopener"); } catch (e) { alert((e as Error).message); } };
  const remove = async () => {
    if (!confirm(`Delete “${d.title}” for everyone on the team? This can't be undone.`)) return;
    try { await backend.remove(d); onDeleted(); } catch (e) { alert((e as Error).message); }
  };

  const shown = rows.filter((r) => pass(r) && (!filter || r.target.name.toLowerCase().includes(filter.toLowerCase())));
  const dimmed = activeFilter ? new Set(items.map((i) => i.code).filter((c) => !visible.has(c))) : undefined;
  return (
    <div className="foi-main">
      <div className="foi-map-wrap">
        {mapNote && <div className="foi-map-note tiny">{mapNote}</div>}
        <FoiMap shapes={layerShapes} items={items} reverse={col?.direction === "higher_better"} selected={selected} highlight={highlight} flagged={flaggedSet} dimmed={dimmed} onSelect={setSelected}
          title={`${col?.label ?? ""}${unit}`} format={(v) => fmtValue(v, col, ph)} />
      </div>
      <section className="foi-detail">
        <header className="foi-dh">
          <div className="foi-dh-text">
            <h2>{d.title}</h2>
            <div className="tiny muted">{[GEOGRAPHY_LABEL[d.geography], d.authority, d.period || d.received_on].filter(Boolean).join(" · ")}</div>
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
            title="Only those serving at least one of these seats">{scope === "held" ? "Lib Dem seats" : scope === "target" ? "Lib Dem targets" : "Lib Dem seats & targets"}{ld.size ? ` (${ld.size})` : ""}</button>
          {canPerHead(d, col) && (
            <button className={`chip ${perHead ? "on" : ""}`} aria-pressed={perHead} onClick={() => setPerHead(!perHead)}
              title="Estimated from the residents of the seats each area covers">Per 100,000</button>
          )}
        </div>
        {activeFilter && (
          <p className="foi-showing">
            Showing <strong>{visible.size}</strong> of {rows.length}
            {filtering && dir !== "all" && <> · {isChange ? (dir === "up" ? "increased" : "decreased") : `${dir === "up" ? "above" : "below"} the average (${fmtValue(stats.mean, col, ph)})`}</>}
            {ldOnly && <> · serving {scope === "held" ? "a Lib Dem seat" : scope === "target" ? "a Lib Dem target" : "a Lib Dem seat or target"}</>}
            {" "}<button className="link-btn" onClick={() => { setDir("all"); setLdOnly(false); }}>clear</button>
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
                    {(() => { const r = rows.find((x) => x.target.code === sel.code); return r?.rank ? <span className="tiny muted"> · {r.rank} of {stats.n}</span> : null; })()}</td></tr>}
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
          {([["ld", "Lib Dem seats"], ["all", `All ${PLURAL[d.geography]}`], ["about", "About"]] as const).map(([k, label]) => (
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
                            const r = rows.find((x) => x.target.code === l.code);
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
              plural={PLURAL[d.geography]} names={tByCode} onPick={(seatCode, server) => { onPickSeat(seatCode); setSelected(server); }} />
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
            {flagged.some(({ r }) => pass(r)) && (
              <p className="foi-unusual small">
                <span className="muted">Unusual:</span>{" "}
                {flagged.filter(({ r }) => pass(r)).map(({ r, o }, i) => (
                  <span key={r.target.code}>{i > 0 && ", "}
                    <button className="link-btn" title={vsMid(r.value!) ?? ""} onClick={() => setSelected(r.target.code)}>{r.target.name}</button>{" "}
                    <span className={`tag ${o}`}>{o === "high" ? "▲" : "▼"} {fmtValue(r.value, col, ph)}</span>
                  </span>
                ))}
              </p>
            )}
            <div className="foi-table-head">
              <span className="tiny muted">{col?.label}{unit}</span>
              <input type="search" placeholder="Find" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Find in the ranking" />
            </div>
            <table className="foi-rank">
              <thead><tr><th className="rk">#</th><th>{GEOGRAPHY_LABEL[d.geography]}</th><th className="num">{ph ? "Per 100,000" : "Figure"}</th></tr></thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.target.code} className={`${highlight.has(r.target.code) ? "mine" : ""} ${selected === r.target.code ? "sel" : ""}`} onClick={() => setSelected(r.target.code)}>
                    <td className="muted rk">{r.rank ?? ""}</td>
                    <td>{r.target.name}{ld.has(r.target.code) && <span className="tag ld" title={`Serves ${ld.get(r.target.code)!.join(", ")}`}>LD</span>}{flaggedSet.has(r.target.code) && <span className={`tag ${outlier(r.value, stats)}`}>{outlier(r.value, stats) === "high" ? "▲" : "▼"}</span>}</td>
                    <td className="num">{r.suppressed ? <span className="muted">withheld ({r.suppressed})</span> : fmtValue(r.value, col, ph)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}

        {tab === "about" && (
          <div className="foi-about">
            <table className="foi-kv"><tbody>
              <tr><th>Each row is a</th><td>{GEOGRAPHY_LABEL[d.geography]}</td></tr>
              {d.authority && <tr><th>Answered by</th><td>{d.authority}</td></tr>}
              {d.foi_reference && <tr><th>FOI reference</th><td>{d.foi_reference}</td></tr>}
              {d.period && <tr><th>Period covered</th><td>{d.period}</td></tr>}
              {d.requested_on && <tr><th>Request sent</th><td>{d.requested_on}</td></tr>}
              {d.received_on && <tr><th>Response received</th><td>{d.received_on}</td></tr>}
              <tr><th>Added by</th><td>{d.created_by_email || "unknown"} on {d.created_at.slice(0, 10)}</td></tr>
            </tbody></table>
            {d.notes && <p className="small foi-notes">{d.notes}</p>}
            {notIn.length > 0 && notIn.length < tByCode.size && (
              <details className="small foi-missing">
                <summary>{notIn.length} {notIn.length === 1 ? PLURAL[d.geography].replace(/s$/, "") : PLURAL[d.geography]} not in this response</summary>
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

/**
 * What to map. Multi-year responses get the standard views (average per year, % change, or one year) for each
 * measure; any other figures are listed after them.
 */
function ViewPicker({ d, views, colKey, setColKey }: { d: Dataset; views: YearView[]; colKey: string; setColKey: (k: string) => void }) {
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
function YearBars({ view, values }: { view: YearView; values: Record<string, number | null> }) {
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

/** The figure as it reads in a sentence: "stop and search (average per year, 2021/22–2024/25)". */
function measureName(d: Dataset, col: Column, view: YearView | null): string {
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
function LibDemPanel({ ref_, d, col, rows, stats, ph, view, scope, setScope, plural, names, onPick }: {
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
    // Forces read better with "Police": "Kent Police", not "Kent" (Police Scotland, PSNI and the Met already have it).
    const server = raw && d.geography === "police_force" && !/police/i.test(raw) ? `${raw} Police` : raw;
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
