import { useCallback, useEffect, useMemo, useState } from "react";
import { canPerHead, fmtValue, forSeat, points, ranked, summary } from "./analysis";
import type { Backend, User } from "./backend";
import FoiMap, { type MapItem } from "./FoiMap";
import { targets } from "./match";
import Upload from "./Upload";
import { csv, download, slug } from "../lib/format";
import { DEPARTMENTS, GEOGRAPHY_LABEL, IS_AREA, type Dataset, type Department, type NewDataset, type Reference } from "./types";

const PLURAL: Record<Dataset["geography"], string> = { police_force: "police force areas", court: "courts and tribunals", nhs_trust: "NHS trusts", health_area: "NHS areas" };

export default function FoiApp({ backend, ref_, shapes }: { backend: Backend; ref_: Reference; shapes: GeoJSON.FeatureCollection }) {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [recovery, setRecovery] = useState(false);
  const [membership, setMembership] = useState<{ member: boolean; admin: boolean } | null>(null);

  useEffect(() => {
    backend.user().then(setUser);
    return backend.onChange((u, ev) => { setUser(u); if (ev === "recovery") setRecovery(true); });
  }, [backend]);
  useEffect(() => {
    setMembership(null);
    if (user) backend.membership().then(setMembership).catch(() => setMembership({ member: false, admin: false }));
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
          <p className="small">You're signed in as <strong>{user.email}</strong>, but this address isn't on the FOI research team list. Ask the person who invited you to add it.</p>
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
          <DatasetView key={active.id} d={active} ref_={ref_} shapes={shapes} seat={seat || null} backend={backend}
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
  const hits = q.length >= 2 ? ref_.seats.filter((s) => `${s.name} ${s.mp ?? ""}`.toLowerCase().includes(q.toLowerCase())).slice(0, 8) : [];
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
              {hits.map((s) => <li key={s.code}><button onClick={() => { setSeat(s.code); setQ(""); }}>{s.name}{s.mp ? <span className="tiny muted"> · {s.mp}</span> : null}</button></li>)}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

function DatasetView({ d, ref_, shapes, seat, backend, canEdit, onDeleted }: {
  d: Dataset; ref_: Reference; shapes: GeoJSON.FeatureCollection; seat: string | null; backend: Backend; canEdit: boolean; onDeleted: () => void;
}) {
  const [colKey, setColKey] = useState(d.columns[0]?.key ?? "");
  const col = d.columns.find((c) => c.key === colKey);
  const [perHead, setPerHead] = useState(false);
  const ph = perHead && canPerHead(d, col);
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const rows = useMemo(() => ranked(ref_, d, colKey, ph), [ref_, d, colKey, ph]);
  const stats = useMemo(() => summary(rows), [rows]);
  const tByCode = useMemo(() => new Map(targets(ref_, d.geography).map((t) => [t.code, t])), [ref_, d.geography]);
  const rowByCode = useMemo(() => new Map(d.rows.map((r) => [r.code, r])), [d.rows]);
  const seatLinks = useMemo(() => (seat ? forSeat(ref_, d.geography, seat) : []), [ref_, d.geography, seat]);
  const highlight = useMemo(() => new Set(seatLinks.map((l) => l.code)), [seatLinks]);
  const layer = d.geography === "police_force" || d.geography === "court" ? "police" : "health";
  const layerShapes = useMemo(() => (IS_AREA[d.geography] ? { ...shapes, features: shapes.features.filter((f) => f.properties?.layer === layer) } : null), [shapes, d.geography, layer]);

  const unit = ph ? " per 100,000 residents" : "";
  const items: MapItem[] = useMemo(() => {
    const val = new Map(rows.map((r) => [r.target.code, r]));
    const base = IS_AREA[d.geography] ? [...tByCode.values()].map((t) => ({ code: t.code, name: t.name, sub: undefined as string | undefined, lat: undefined as number | undefined, lon: undefined as number | undefined }))
      : points(ref_, d.geography).map((p) => ({ code: p.code, name: p.name, sub: p.sub, lat: p.lat, lon: p.lon }));
    return base.map((b) => {
      const r = val.get(b.code);
      const label = !r ? "Not in this response" : r.suppressed ? `Withheld (${r.suppressed})` : `${fmtValue(r.value, col, ph)}${unit}${r.rank ? ` · ${r.rank} of ${stats.n}` : ""}`;
      return { ...b, value: r?.value ?? null, label };
    });
  }, [rows, tByCode, ref_, d.geography, col, ph, unit, stats.n]);

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

  const shown = rows.filter((r) => !filter || r.target.name.toLowerCase().includes(filter.toLowerCase()));
  return (
    <div className="foi-main">
      <div className="foi-map-wrap">
        <FoiMap shapes={layerShapes} items={items} reverse={col?.direction === "higher_better"} selected={selected} highlight={highlight} onSelect={setSelected} />
      </div>
      <section className="foi-detail">
        <div className="foi-detail-head">
          <div>
            <h2>{d.title}</h2>
            <div className="tiny muted">
              {[GEOGRAPHY_LABEL[d.geography], d.authority && `answered by ${d.authority}`, d.period, d.foi_reference && `ref. ${d.foi_reference}`,
                d.received_on && `received ${d.received_on}`, `added by ${d.created_by_email || "unknown"} on ${d.created_at.slice(0, 10)}`].filter(Boolean).join(" · ")}
            </div>
          </div>
          <div className="foi-actions">
            <button className="btn" onClick={exportCsv}>Download CSV</button>
            {d.file_path && <button className="btn" onClick={openFile}>Original file</button>}
            {canEdit && <button className="btn danger" onClick={remove}>Delete</button>}
          </div>
        </div>
        {d.notes && <p className="small foi-notes">{d.notes}</p>}

        <div className="chips">
          {d.columns.map((c) => <button key={c.key} className={`chip ${c.key === colKey ? "on" : ""}`} onClick={() => setColKey(c.key)}>{c.label}</button>)}
        </div>
        {canPerHead(d, col) && (
          <label className="small foi-toggle"><input type="checkbox" checked={perHead} onChange={(e) => setPerHead(e.target.checked)} /> Per 100,000 residents (estimated from each area's seats)</label>
        )}

        <div className="foi-stats">
          <div><strong>{stats.n}</strong><span className="tiny muted">{PLURAL[d.geography]} with a figure</span></div>
          {!ph && col?.unit !== "rate" && col?.unit !== "percent" && <div><strong>{fmtValue(stats.total, col)}</strong><span className="tiny muted">total</span></div>}
          <div><strong>{fmtValue(stats.median, col, ph)}</strong><span className="tiny muted">median{unit}</span></div>
          <div><strong>{fmtValue(stats.min, col, ph)} – {fmtValue(stats.max, col, ph)}</strong><span className="tiny muted">range</span></div>
          {stats.withheld > 0 && <div><strong>{stats.withheld}</strong><span className="tiny muted">withheld</span></div>}
        </div>

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
                            {r?.rank && <span className="tiny muted"> · {r.rank} of {stats.n}; median {fmtValue(stats.median, col, ph)}</span>}
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

        {sel && (
          <div className="foi-selected">
            <div className="foi-selected-head">
              <h3 className="foi-h">{sel.name}</h3>
              <button className="icon-btn" onClick={() => setSelected(null)} aria-label="Close">✕</button>
            </div>
            {sel.sub && <div className="tiny muted">{sel.sub}</div>}
            {!selRow ? <p className="small muted">Not in this response.</p> : (
              <table className="foi-kv"><tbody>
                {d.columns.map((c) => <tr key={c.key}><th>{c.label}</th><td>{selRow.suppressed?.[c.key] ? `Withheld (${selRow.suppressed[c.key]})` : fmtValue(selRow.values[c.key], c)}</td></tr>)}
                <tr><th>Name in the response</th><td>{selRow.source_name}</td></tr>
                {linkedSeats(sel.code) !== null && <tr><th>Seats it covers</th><td>{linkedSeats(sel.code)}</td></tr>}
                {sel.population ? <tr><th>Residents (est.)</th><td>{sel.population.toLocaleString("en-GB")}</td></tr> : null}
              </tbody></table>
            )}
          </div>
        )}

        <div className="foi-table-head">
          <h3 className="foi-h">Ranking: {col?.label}{unit}</h3>
          <input type="search" placeholder="Filter" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter the ranking" />
        </div>
        <table className="foi-rank">
          <thead><tr><th className="rk">#</th><th>{GEOGRAPHY_LABEL[d.geography]}</th><th className="num">{ph ? "Per 100,000" : "Figure"}</th></tr></thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.target.code} className={`${highlight.has(r.target.code) ? "mine" : ""} ${selected === r.target.code ? "sel" : ""}`} onClick={() => setSelected(r.target.code)}>
                <td className="muted rk">{r.rank ?? ""}</td>
                <td>{r.target.name}</td>
                <td className="num">{r.suppressed ? <span className="muted">withheld ({r.suppressed})</span> : fmtValue(r.value, col, ph)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {d.unmatched.length > 0 && (
          <details className="small foi-unmatched">
            <summary>{d.unmatched.length} {d.unmatched.length === 1 ? "row" : "rows"} in the file couldn't be matched (not mapped)</summary>
            <ul>{d.unmatched.map((u, i) => <li key={i}>{u.source_name}</li>)}</ul>
          </details>
        )}
      </section>
    </div>
  );
}
