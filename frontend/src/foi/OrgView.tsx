import { useMemo, useState } from "react";
import { campaignLine, displayName, fmtValue, ldOf, libDemServed, seatsServed, type LdScope } from "./analysis";
import FoiMap, { type MapItem } from "./FoiMap";
import { targets } from "./match";
import { ordinal } from "../lib/format";
import { DEPARTMENT, GEO } from "./geographies";
import { orgList, parentOf, scores, worseHalf, type Headline } from "./orgs";
import { mapShapes } from "./shapes";
import { outlier } from "./stats";
import type { Department, Geography, Reference } from "./types";

/** Sidebar in Area view: the kind (e.g. trusts or ICBs), a search, and the list, worst first. */
export function OrgSidebar({ ref_, heads, dept, scope, kind, setKind, code, setCode }: {
  ref_: Reference; heads: Headline[]; dept: Department; scope: LdScope; kind: Geography; setKind: (g: Geography) => void; code: string | null; setCode: (c: string | null) => void;
}) {
  const [q, setQ] = useState("");
  const [ldOnly, setLdOnly] = useState(false);
  const list = useMemo(() => orgList(ref_, heads, kind), [ref_, heads, kind]);
  const sc = useMemo(() => scores(heads, kind), [heads, kind]);
  const ld = useMemo(() => libDemServed(ref_, kind, new Set(list.map((t) => t.code)), scope), [ref_, kind, list, scope]);
  const shown = list
    .filter((t) => (!ldOnly || ld.has(t.code)) && (!q || t.name.toLowerCase().includes(q.toLowerCase())))
    .sort((a, b) => {
      const sa = sc.get(a.code), sb = sc.get(b.code);
      const ra = sa?.of ? sa.worse / sa.of : -1, rb = sb?.of ? sb.worse / sb.of : -1;
      return rb - ra || (sb?.worse ?? 0) - (sa?.worse ?? 0) || a.name.localeCompare(b.name);
    });
  const kinds = DEPARTMENT[dept].geographies;
  return (
    <div className="foi-orgside">
      {kinds.length > 1 && (
        <div className="seg mini foi-kind" role="tablist">
          {kinds.map((k) => <button key={k} className={k === kind ? "on" : ""} onClick={() => { setKind(k); setCode(null); }}>{GEO[k].many}</button>)}
        </div>
      )}
      <div className="foi-orgside-tools">
        <input type="search" placeholder={GEO[kind].find} value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find" />
        <button className={`chip ld ${ldOnly ? "on" : ""}`} aria-pressed={ldOnly} onClick={() => setLdOnly(!ldOnly)} title="Only those serving Lib Dem seats">LD</button>
      </div>
      {!heads.some((h) => h.d.geography === kind) && <p className="small muted">No datasets by {GEO[kind].label.toLowerCase()} yet.</p>}
      <ul className="foi-orglist">
        {shown.map((t) => {
          const s = sc.get(t.code);
          return (
            <li key={t.code}>
              <button className={t.code === code ? "on" : ""} onClick={() => setCode(t.code)}>
                <span className="foi-orgname">{t.name}{ld.has(t.code) && <span className="tag ld">LD</span>}</span>
                {s?.of ? <span className="foi-orgscore" title={`In the worse half in ${s.worse} of ${s.of} datasets`}>
                  <span className="bar"><span style={{ width: `${(s.worse / s.of) * 100}%` }} /></span>{s.worse}/{s.of}
                </span> : <span className="tiny muted">–</span>}
              </button>
            </li>
          );
        })}
      </ul>
      <p className="tiny muted">Sorted by how often each is in the worse half of a dataset (worse than the median).</p>
    </div>
  );
}

/** Map and profile in Area view. */
export default function OrgView({ ref_, shapes, heads, scope, kind, code, setCode, setKindAndCode, onOpenDataset }: {
  ref_: Reference; shapes: GeoJSON.FeatureCollection; heads: Headline[]; scope: LdScope; kind: Geography; code: string | null;
  setCode: (c: string | null) => void; setKindAndCode: (g: Geography, c: string) => void; onOpenDataset: (id: string) => void;
}) {
  const list = useMemo(() => orgList(ref_, heads, kind), [ref_, heads, kind]);
  const sc = useMemo(() => scores(heads, kind), [heads, kind]);
  const present = useMemo(() => new Set(heads.filter((h) => h.d.geography === kind).flatMap((h) => [...h.byCode.keys()])), [heads, kind]);
  const layer = useMemo(() => mapShapes(ref_, shapes, kind, present), [ref_, shapes, kind, present]);
  const ld = useMemo(() => libDemServed(ref_, kind, new Set(list.map((t) => t.code)), scope), [ref_, kind, list, scope]);
  const byCode = useMemo(() => new Map(targets(ref_, kind).map((t) => [t.code, t])), [ref_, kind]);
  const pts = useMemo(() => (GEO[kind].isArea ? null : new Map((kind === "court" ? ref_.points.courts ?? [] : ref_.points.trusts ?? []).map((p) => [("id" in p ? p.id : p.code), p]))), [ref_, kind]);

  const items: MapItem[] = list.map((t) => {
    const s = sc.get(t.code);
    const p = pts?.get(t.code);
    return {
      code: t.code, name: t.name, sub: t.sub, lat: p?.lat, lon: p?.lon,
      value: s?.of ? (s.worse / s.of) * 100 : null,
      label: s?.of ? `In the worse half in ${s.worse} of ${s.of} datasets` : "No comparable figures",
    };
  });

  return (
    <div className="foi-main">
      <div className="foi-map-wrap">
        {GEO[kind].mapNote && <div className="foi-map-note tiny">{GEO[kind].mapNote}</div>}
        <FoiMap shapes={layer} items={items} reverse={false} selected={code} highlight={new Set(ld.keys())} onSelect={setCode}
          title="Datasets where it's in the worse half" format={(v) => `${Math.round(v)}%`} />
      </div>
      <section className="foi-detail">
        {code && byCode.get(code)
          ? <Profile ref_={ref_} heads={heads} kind={kind} code={code} present={present} name={byCode.get(code)!.name} sub={byCode.get(code)!.sub}
              score={sc.get(code)} setKindAndCode={setKindAndCode} onOpenDataset={onOpenDataset} />
          : <Overview heads={heads} kind={kind} list={list} sc={sc} ld={ld} setCode={setCode} />}
      </section>
    </div>
  );
}

function Overview({ heads, kind, list, sc, ld, setCode }: {
  heads: Headline[]; kind: Geography; list: { code: string; name: string }[]; sc: ReturnType<typeof scores>; ld: Map<string, string[]>; setCode: (c: string) => void;
}) {
  const n = heads.filter((h) => h.d.geography === kind).length;
  const worst = list.filter((t) => (sc.get(t.code)?.of ?? 0) > 0)
    .sort((a, b) => sc.get(b.code)!.worse / sc.get(b.code)!.of - sc.get(a.code)!.worse / sc.get(a.code)!.of || sc.get(b.code)!.worse - sc.get(a.code)!.worse)
    .slice(0, 12);
  return (
    <>
      <h2>{GEO[kind].many}: across all datasets</h2>
      <p className="small muted">{n} {n === 1 ? "dataset" : "datasets"} by {GEO[kind].label.toLowerCase()}. Choose one on the map or in the list for everything known about it.</p>
      {worst.length > 0 && (
        <>
          <h3 className="foi-h">Most often in the worse half</h3>
          <ol className="foi-worst">
            {worst.map((t) => (
              <li key={t.code}>
                <button className="link-btn" onClick={() => setCode(t.code)}>{t.name}</button>{ld.has(t.code) && <span className="tag ld">LD</span>}
                <span className="tiny muted"> {sc.get(t.code)!.worse} of {sc.get(t.code)!.of}</span>
              </li>
            ))}
          </ol>
        </>
      )}
    </>
  );
}

function Spark({ h, code }: { h: Headline; code: string }) {
  if (!h.view) return null;
  const rows = h.d.rows.find((r) => r.code === code);
  const vals = h.view.years.map((y) => rows?.values[y.key] ?? null);
  const known = vals.filter((v): v is number => v !== null);
  if (known.length < 2) return null;
  const lo = Math.min(...known), hi = Math.max(...known), W = 90, H = 24;
  const xy = vals.map((v, i) => (v === null ? null : [(i / (vals.length - 1)) * W, H - 2 - ((v - lo) / (hi - lo || 1)) * (H - 4)] as const));
  const path = xy.filter(Boolean).map((p, i) => `${i ? "L" : "M"}${p![0].toFixed(1)},${p![1].toFixed(1)}`).join("");
  return (
    <svg className="foi-spark" viewBox={`0 0 ${W} ${H}`} width={W} height={H} aria-label={`${h.view.years.map((y, i) => `${y.period}: ${vals[i] ?? "–"}`).join(", ")}`}>
      <path d={path} />
      {xy.map((p, i) => p && <circle key={i} cx={p[0]} cy={p[1]} r={i === xy.length - 1 ? 2.6 : 1.6} />)}
    </svg>
  );
}

function Card({ h, code, name, via, onOpen }: { h: Headline; code: string; name: string; via?: string; onOpen: () => void }) {
  const [copied, setCopied] = useState(false);
  const r = h.byCode.get(code);
  const v = r?.value ?? null;
  const w = worseHalf(h, v);
  const o = r ? outlier(v, h.stats) : null;
  const measure = h.view?.series || h.d.title;
  const line = campaignLine({ server: displayName(h.d.geography, name), measure: h.col.change ? measure : h.col.period ? `${measure} in ${h.col.period}` : h.col.label,
    col: h.col, value: v, suppressed: r?.suppressed, values: h.values, median: h.stats.median, plural: GEO[h.d.geography].plural });
  return (
    <article className={`foi-card ${w ? "worse" : ""}`}>
      <div className="foi-card-top">
        <button className="link-btn foi-card-title" onClick={onOpen} title="Open this dataset">{h.d.title}</button>
        <button className="icon-btn" title={line} aria-label="Copy a line" onClick={async () => { try { await navigator.clipboard.writeText(line); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* blocked */ } }}>{copied ? "✓" : "⧉"}</button>
      </div>
      <div className="foi-card-body">
        <div>
          <div className="foi-card-value">{r?.suppressed ? <span className="muted">withheld</span> : fmtValue(v, h.col)}</div>
          <div className="tiny muted">{h.col.change ? `% change ${h.col.change.from} → ${h.col.change.to}` : h.col.label}{via ? ` · ${via}` : ""}</div>
        </div>
        <Spark h={h} code={code} />
      </div>
      <div className="foi-card-meta tiny">
        {r?.rank ? <span>{ordinal(r.rank)} highest of {h.stats.n}</span> : <span className="muted">no figure</span>}
        {h.stats.median !== null && v !== null && <span className="muted"> · median {fmtValue(h.stats.median, h.col)}</span>}
        {w === true && <span className="tag high">worse half</span>}
        {w === false && <span className="tag low">better half</span>}
        {o && <span className={`tag ${o}`}>{o === "high" ? "▲ unusually high" : "▼ unusually low"}</span>}
      </div>
    </article>
  );
}

function Profile({ ref_, heads, kind, code, present, name, sub, score, setKindAndCode, onOpenDataset }: {
  ref_: Reference; heads: Headline[]; kind: Geography; code: string; present: Set<string>; name: string; sub?: string; score?: { worse: number; of: number };
  setKindAndCode: (g: Geography, c: string) => void; onOpenDataset: (id: string) => void;
}) {
  const direct = heads.filter((h) => h.d.geography === kind && h.byCode.has(code));
  const missing = heads.filter((h) => h.d.geography === kind && !h.byCode.has(code));
  const parentKind = GEO[kind].parent;
  const parentCode = parentKind ? parentOf(ref_, kind, code) : null;
  const parentName = parentKind && parentCode ? targets(ref_, parentKind).find((t) => t.code === parentCode)?.name : null;
  const viaParent = parentKind && parentCode ? heads.filter((h) => h.d.geography === parentKind && h.byCode.has(parentCode)) : [];
  const childKind = GEO[kind].child;
  const childHeads = childKind ? heads.filter((h) => h.d.geography === childKind) : [];
  const children = childKind ? targets(ref_, childKind).filter((t) => parentOf(ref_, childKind, t.code) === code) : [];

  // The Lib Dem seats it serves (held and targets).
  // Courts are matched to seats among all the courts with figures (nearest court), so pass them all.
  const served = seatsServed(ref_, kind, new Set([...present, code])).get(code) ?? new Set<string>();
  const seats = ref_.seats.filter((s) => served.has(s.code) && ldOf(s));
  // Worst first: unusual, then worse half, then the rest.
  const order = (h: Headline) => {
    const v = h.byCode.get(code)?.value ?? null;
    return (outlier(v, h.stats) ? 0 : 2) + (worseHalf(h, v) ? 0 : 1);
  };
  return (
    <>
      <header className="foi-dh">
        <div className="foi-dh-text">
          <h2>{name}</h2>
          <div className="tiny muted">
            {[GEO[kind].one, sub].filter(Boolean).join(" · ")}
            {parentKind && parentCode && parentName && <> · in <button className="link-btn" onClick={() => setKindAndCode(parentKind, parentCode)}>{parentName}</button></>}
          </div>
        </div>
      </header>
      {score?.of ? <p className="small">In the <strong>worse half in {score.worse} of {score.of}</strong> datasets.</p> : null}
      {seats.length > 0 && (
        <p className="small foi-ldline">
          <span className="muted">Serves</span>{" "}
          {seats.map((s, i) => <span key={s.code}>{i > 0 && ", "}<strong>{s.name}</strong>{ldOf(s) === "target" ? <span className="tag tgt">target</span> : <span className="tag ld">LD</span>}</span>)}
        </p>
      )}

      {direct.length > 0 ? (
        <div className="foi-cards">
          {[...direct].sort((a, b) => order(a) - order(b)).map((h) => (
            <Card key={h.d.id} h={h} code={code} name={name} onOpen={() => onOpenDataset(h.d.id)} />
          ))}
        </div>
      ) : <p className="small muted">Not in any {GEO[kind].one.toLowerCase()} dataset yet.</p>}

      {viaParent.length > 0 && parentName && parentCode && (
        <>
          <h3 className="foi-h">Via {parentName}</h3>
          <div className="foi-cards">
            {viaParent.map((h) => <Card key={h.d.id} h={h} code={parentCode} name={parentName} via={`for ${parentName}`} onOpen={() => onOpenDataset(h.d.id)} />)}
          </div>
        </>
      )}

      {childKind && childHeads.length > 0 && children.length > 0 && (
        <>
          <h3 className="foi-h">Its {GEO[childKind].many.toLowerCase()}</h3>
          {childHeads.map((h) => {
            const kids = children.filter((c) => h.byCode.has(c.code)).map((c) => ({ c, r: h.byCode.get(c.code)! }))
              .sort((a, b) => (b.r.value ?? -Infinity) - (a.r.value ?? -Infinity));
            if (!kids.length) return null;
            return (
              <div key={h.d.id} className="foi-kids">
                <button className="link-btn small" onClick={() => onOpenDataset(h.d.id)}>{h.d.title}</button>
                <ul>
                  {kids.map(({ c, r }) => (
                    <li key={c.code}>
                      <button className="link-btn" onClick={() => setKindAndCode(childKind, c.code)}>{c.name}</button>{" "}
                      <strong>{r.suppressed ? "withheld" : fmtValue(r.value, h.col)}</strong>
                      {r.rank && <span className="tiny muted"> · {ordinal(r.rank)} of {h.stats.n}</span>}
                      {worseHalf(h, r.value) && <span className="tag high">worse half</span>}
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </>
      )}

      {missing.length > 0 && <p className="tiny muted">Not in: {missing.map((h) => h.d.title).join(", ")}.</p>}
    </>
  );
}
