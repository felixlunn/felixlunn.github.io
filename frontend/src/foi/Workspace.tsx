import { useCallback, useEffect, useMemo, useState } from "react";
import { usePersistentState } from "../lib/usePersistentState";
import { type LdScope } from "./analysis";
import OrgView, { OrgSidebar } from "./OrgView";
import { headline, headlineText, type Headline } from "./orgs";
import type { Backend, User } from "./backend";
import FoiMap from "./FoiMap";
import Upload from "./Upload";
import { DEPARTMENT, DEPARTMENTS, GEO } from "./geographies";
import { type Dataset, type DatasetInfo, type Department, type Geography, type NewDataset, type Reference } from "./types";
import { SeatPicker } from "./SeatPicker";
import { DatasetView } from "./DatasetView";
/** The FOI workspace: departments, the two views (Dataset view / Area view), uploads and the seat picker. */

export function Workspace({ backend, user, admin, ref_, shapes }: { backend: Backend; user: User; admin: boolean; ref_: Reference; shapes: GeoJSON.FeatureCollection }) {
  const [dept, setDept] = useState<Department>(() => (["policing", "justice", "health"].includes(location.hash.slice(1)) ? location.hash.slice(1) as Department : "policing"));
  // The list: every dataset without its rows. Rows load when a dataset is opened, or all at once for Area view.
  const [datasets, setDatasets] = useState<DatasetInfo[] | null>(null);
  const [loaded, setLoaded] = useState<Map<string, Dataset>>(() => new Map());
  const [allLoaded, setAllLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [seat, setSeat] = usePersistentState<string>("foi.seat", "");
  // Two ways in: one dataset at a time, or one organisation (trust / ICB / force / court) across every dataset.
  const [mode, setMode] = usePersistentState("foi.mode", "datasets", ["datasets", "orgs"] as const);
  // Which Lib Dem seats to focus on (held, targets or both): shared by both views and remembered.
  const [scope, setScope] = usePersistentState<LdScope>("foi.ldScope", "held", ["held", "target", "both"]);
  const [orgKind, setOrgKind] = useState<Geography>(DEPARTMENT[dept].geographies[0]);
  const [orgCode, setOrgCode] = useState<string | null>(null);
  useEffect(() => { setOrgKind(DEPARTMENT[dept].geographies[0]); setOrgCode(null); }, [dept]);
  const heads = useMemo(() => (allLoaded ? (datasets ?? []) : []).map((d) => loaded.get(d.id)).filter((d): d is Dataset => !!d)
    .map((d) => headline(ref_, d)).filter((h): h is Headline => h !== null), [allLoaded, datasets, loaded, ref_]);
  const keep = useCallback((ds: Dataset[]) => setLoaded((m) => new Map([...m, ...ds.map((d) => [d.id, d] as const)])), []);

  const reload = useCallback(() => {
    setDatasets(null);
    setLoaded(new Map());
    setAllLoaded(false);
    backend.list(dept).then((ds) => { setDatasets(ds); setError(null); setActiveId((id) => (ds.some((d) => d.id === id) ? id : ds[0]?.id ?? null)); })
      .catch((e: Error) => { setError(e.message); setDatasets([]); });
  }, [backend, dept]);
  useEffect(reload, [reload]);

  // Dataset view: load the open dataset's rows.
  useEffect(() => {
    if (mode !== "datasets" || !activeId || loaded.has(activeId)) return;
    let live = true;
    backend.get(activeId).then((d) => { if (live) keep([d]); }).catch((e: Error) => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [mode, activeId, loaded, backend, keep]);

  // Area view compares every dataset, so it loads them all (once per department).
  useEffect(() => {
    if (mode !== "orgs" || allLoaded || datasets === null) return;
    let live = true;
    backend.all(dept).then((ds) => { if (live) { keep(ds); setAllLoaded(true); } }).catch((e: Error) => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [mode, allLoaded, datasets, backend, dept, keep]);
  const areaReady = allLoaded || datasets?.length === 0;
  useEffect(() => { history.replaceState(null, "", `#${dept}`); }, [dept]);

  const activeInfo = datasets?.find((d) => d.id === activeId) ?? null;
  const active = activeId ? loaded.get(activeId) ?? null : null;
  const info = DEPARTMENTS.find((d) => d.id === dept)!;

  const save = async (d: NewDataset, file: File | null) => {
    const created = await backend.create(d, file);
    setUploading(false);
    reload();
    keep([created]);
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
            <div className="seg foi-mode" role="tablist" aria-label="View by">
              <button role="tab" aria-selected={mode === "datasets"} className={mode === "datasets" ? "on" : ""} onClick={() => setMode("datasets")} title="One FOI response at a time"><strong>Dataset view</strong></button>
              <button role="tab" aria-selected={mode === "orgs"} className={mode === "orgs" ? "on" : ""} onClick={() => setMode("orgs")} title={DEPARTMENT[dept].areaViewHint}>
                <strong>Area view</strong>
              </button>
            </div>
            {mode === "orgs" && !areaReady ? <p className="small muted">Loading every dataset…</p> : mode === "orgs" ? (
              <OrgSidebar ref_={ref_} heads={heads} dept={dept} scope={scope} kind={orgKind} setKind={setOrgKind} code={orgCode} setCode={setOrgCode} />
            ) : datasets === null ? <p className="small muted">Loading…</p> : !datasets.length ? (
              <p className="small muted">None yet. Upload the first FOI response for {info.label.toLowerCase()}.</p>
            ) : (
              <ul className="foi-list">
                {datasets.map((d) => (
                  <li key={d.id}>
                    <button className={d.id === activeId ? "on" : ""} onClick={() => setActiveId(d.id)}>
                      <span className="foi-list-title">{d.title}{d.builtin && <span className="tag builtin" title="Public data, rebuilt with the site's data: nothing to upload">{d.builtin}</span>}</span>
                      <span className="tiny muted">{GEO[d.geography].label} · {d.summary?.rows ?? "?"} rows · {d.period || d.received_on || d.created_at.slice(0, 10)}</span>
                      {headlineText(d.summary) && <span className="tiny muted foi-list-head">{headlineText(d.summary)}</span>}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>
        {(mode === "orgs" && !areaReady) || (mode === "datasets" && activeInfo && !active) ? (
          <div className="foi-main foi-empty">
            <FoiMap shapes={null} items={[]} reverse={false} selected={null} highlight={new Set()} onSelect={() => {}} />
            <p className="foi-loading small">{mode === "orgs" ? "Loading every dataset for Area view…" : `Loading ${activeInfo!.title}…`}</p>
          </div>
        ) : mode === "orgs" ? (
          <OrgView ref_={ref_} shapes={shapes} heads={heads} scope={scope} kind={orgKind} code={orgCode} setCode={setOrgCode}
            setKindAndCode={(g, c) => { setOrgKind(g); setOrgCode(c); }} onOpenDataset={(id) => { setActiveId(id); setMode("datasets"); }} />
        ) : active ? (
          <DatasetView key={active.id} d={active} ref_={ref_} shapes={shapes} seat={seat || null} backend={backend} onPickSeat={setSeat}
            scope={scope} setScope={setScope}
            canEdit={!active.builtin && (admin || active.created_by === user.id)} onDeleted={reload} />
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
