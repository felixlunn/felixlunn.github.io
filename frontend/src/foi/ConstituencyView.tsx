import { useEffect, useMemo, useState } from "react";
import { dataUrl } from "../lib/dataUrl";
import { forSeat, ldOf } from "./analysis";
import FoiMap, { type MapItem } from "./FoiMap";
import { targets } from "./match";
import { Card } from "./OrgView";
import { DEPARTMENT, GEO } from "./geographies";
import { outlier } from "./stats";
import { seatScores, servingBySeat, worseHalf, type Headline, type Score } from "./orgs";
import type { Department, Reference } from "./types";

/**
 * Constituency view: one seat at a time, with every dataset's figure for the organisations that serve it (its
 * force, trusts, ICB, mental health and ambulance trusts...). Seats are ranked by how many of those figures are in
 * the worse half.
 */

type Seat = Reference["seats"][number];

/** Which seats to show: all of them, or only those with a Lib Dem MP. */
export type SeatFilter = "all" | "held";
const held = (s: Seat) => ldOf(s) === "held";

function ratio(s: Score | undefined): number {
  return s?.of ? s.worse / s.of : -1;
}

function bySeatScore(sc: Map<string, Score>) {
  return (a: Seat, b: Seat) => {
    const sa = sc.get(a.code), sb = sc.get(b.code);
    return ratio(sb) - ratio(sa) || (sb?.worse ?? 0) - (sa?.worse ?? 0) || a.name.localeCompare(b.name);
  };
}

function LdTag({ s }: { s: Seat }) {
  return held(s) ? <span className="tag ld">LD</span> : null;
}

/** Sidebar in Constituency view: which Lib Dem seats, a search, and the seats, worst first. */
export function ConstituencySidebar({ ref_, heads, filter, setFilter, seat, setSeat }: {
  ref_: Reference; heads: Headline[]; filter: SeatFilter; setFilter: (f: SeatFilter) => void;
  seat: string; setSeat: (s: string) => void;
}) {
  const [q, setQ] = useState("");
  const sc = useMemo(() => seatScores(ref_, heads), [ref_, heads]);
  const nHeld = useMemo(() => ref_.seats.filter(held).length, [ref_]);
  const shown = useMemo(() => ref_.seats
    .filter((s) => (filter === "all" || held(s)) && (!q || s.name.toLowerCase().includes(q.toLowerCase()) || (s.mp ?? "").toLowerCase().includes(q.toLowerCase())))
    .sort(bySeatScore(sc)), [ref_, sc, filter, q]);
  return (
    <div className="foi-orgside">
      <div className="seg mini foi-kind" role="tablist" aria-label="Which seats">
        <button role="tab" aria-selected={filter === "all"} className={filter === "all" ? "on" : ""} onClick={() => setFilter("all")}>All ({ref_.seats.length})</button>
        <button role="tab" aria-selected={filter === "held"} className={filter === "held" ? "on" : ""} onClick={() => setFilter("held")}>LD held ({nHeld})</button>
      </div>
      <div className="foi-orgside-tools">
        <input type="search" placeholder="Find a constituency or MP" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find a constituency" />
      </div>
      {!heads.length && <p className="small muted">No datasets here yet.</p>}
      <ul className="foi-orglist">
        {shown.map((s) => {
          const x = sc.get(s.code);
          return (
            <li key={s.code}>
              <button className={s.code === seat ? "on" : ""} onClick={() => setSeat(s.code)}>
                <span className="foi-orgname">{s.name}<LdTag s={s} /></span>
                {x?.of ? <span className="foi-orgscore" title={`${x.worse} of ${x.of} figures for the organisations serving it are in the worse half`}>
                  <span className="bar"><span style={{ width: `${(x.worse / x.of) * 100}%` }} /></span>{x.worse}/{x.of}
                </span> : <span className="tiny muted">–</span>}
              </button>
            </li>
          );
        })}
      </ul>
      <p className="tiny muted">Sorted by how many of the figures for the organisations serving each seat are in the worse half (worse than the median).</p>
    </div>
  );
}

// Seat boundaries: the dashboard's own file, fetched once and only when this view is opened.
let boundaries: Promise<GeoJSON.FeatureCollection | null> | null = null;
function loadBoundaries() {
  boundaries ??= fetch(dataUrl("boundaries.geojson")).then((r) => (r.ok ? r.json() as Promise<GeoJSON.FeatureCollection> : null)).catch(() => null);
  return boundaries;
}

/** Map and seat profile in Constituency view. */
export default function ConstituencyView({ ref_, heads, dept, filter, seat, setSeat, onOpenDataset }: {
  ref_: Reference; heads: Headline[]; dept: Department; filter: SeatFilter; seat: string; setSeat: (s: string) => void;
  onOpenDataset: (id: string) => void;
}) {
  const [shapes, setShapes] = useState<GeoJSON.FeatureCollection | null>(null);
  useEffect(() => { let live = true; loadBoundaries().then((b) => { if (live) setShapes(b); }); return () => { live = false; }; }, []);
  const sc = useMemo(() => seatScores(ref_, heads), [ref_, heads]);
  // Until the boundaries arrive (or if they can't), seats show as dots at their centres.
  const items: MapItem[] = useMemo(() => ref_.seats.map((s) => {
    const x = sc.get(s.code);
    return { code: s.code, name: s.name, sub: [s.mp, s.party].filter(Boolean).join(", "), lat: s.lat, lon: s.lon,
      value: x?.of ? (x.worse / x.of) * 100 : null, label: x?.of ? `${x.worse} of ${x.of} figures in the worse half` : "No comparable figures" };
  }), [ref_, sc]);
  const highlight = useMemo(() => new Set(ref_.seats.filter(held).map((s) => s.code)), [ref_]);
  const dimmed = useMemo(() => (filter === "held" ? new Set(ref_.seats.filter((s) => !held(s)).map((s) => s.code)) : undefined), [ref_, filter]);
  const chosen = ref_.seats.find((s) => s.code === seat);
  return (
    <div className="foi-main">
      <div className="foi-map-wrap">
        <FoiMap shapes={shapes} items={items} reverse={false} selected={chosen ? seat : null} highlight={highlight} dimmed={dimmed} onSelect={setSeat}
          title="Figures in the worse half" format={(v) => `${Math.round(v)}%`} />
      </div>
      <section className="foi-detail">
        {chosen
          ? <SeatProfile ref_={ref_} heads={heads} dept={dept} s={chosen} score={sc.get(chosen.code)} onOpenDataset={onOpenDataset} />
          : <SeatOverview ref_={ref_} heads={heads} filter={filter} sc={sc} setSeat={setSeat} />}
      </section>
    </div>
  );
}

function SeatOverview({ ref_, heads, filter, sc, setSeat }: {
  ref_: Reference; heads: Headline[]; filter: SeatFilter; sc: Map<string, Score>; setSeat: (s: string) => void;
}) {
  const worst = ref_.seats.filter((s) => (sc.get(s.code)?.of ?? 0) > 0 && (filter === "all" || held(s))).sort(bySeatScore(sc)).slice(0, 12);
  return (
    <>
      <h2>Constituencies: across all datasets</h2>
      <p className="small muted">
        {heads.length} {heads.length === 1 ? "dataset" : "datasets"}. Choose a seat on the map or in the list to see every figure for the
        organisations that serve it. Seats with a Lib Dem MP are outlined.
      </p>
      {worst.length > 0 && (
        <>
          <h3 className="foi-h">Most often served by the worse half{filter === "held" ? ": Lib Dem seats" : ""}</h3>
          <ol className="foi-worst">
            {worst.map((s) => (
              <li key={s.code}>
                <button className="link-btn" onClick={() => setSeat(s.code)}>{s.name}</button><LdTag s={s} />
                <span className="tiny muted"> {sc.get(s.code)!.worse} of {sc.get(s.code)!.of}</span>
              </li>
            ))}
          </ol>
        </>
      )}
    </>
  );
}

function SeatProfile({ ref_, heads, dept, s, score, onOpenDataset }: {
  ref_: Reference; heads: Headline[]; dept: Department; s: Seat; score?: Score; onOpenDataset: (id: string) => void;
}) {
  // Worst first: unusual, then worse half, then the rest.
  const order = (code: string) => (h: Headline) => {
    const v = h.byCode.get(code)?.value ?? null;
    return (outlier(v, h.stats) ? 0 : 2) + (worseHalf(h, v) ? 0 : 1);
  };
  const sections = DEPARTMENT[dept].geographies.map((g) => {
    const hs = heads.filter((h) => h.d.geography === g);
    const codes = new Set(hs.flatMap((h) => servingBySeat(ref_, h).get(s.code) ?? []));
    const why = forSeat(ref_, g, s.code);
    const rank = new Map(why.map((w, i) => [w.code, i]));
    const reason = new Map(why.map((w) => [w.code, w.why]));
    const names = new Map(targets(ref_, g).map((t) => [t.code, t.name]));
    const orgs = [...codes].sort((a, b) => (rank.get(a) ?? 1e9) - (rank.get(b) ?? 1e9) || (names.get(a) ?? a).localeCompare(names.get(b) ?? b))
      .map((code) => ({ code, name: names.get(code) ?? code, why: reason.get(code), hs: hs.filter((h) => h.byCode.has(code)).sort((a, b) => order(code)(a) - order(code)(b)) }));
    return { g, hs, orgs };
  }).filter((x) => x.hs.length);
  return (
    <>
      <header className="foi-dh">
        <div className="foi-dh-text">
          <h2>{s.name}<LdTag s={s} /></h2>
          <div className="tiny muted">{[s.mp, s.party].filter(Boolean).join(" · ") || "Constituency"}</div>
        </div>
      </header>
      {score?.of ? <p className="small">Of {score.of} {score.of === 1 ? "figure" : "figures"} for the organisations serving this seat, <strong>{score.worse} {score.worse === 1 ? "is" : "are"} in the worse half</strong>.</p> : null}
      {!sections.length && <p className="small muted">No datasets here yet.</p>}
      {sections.map(({ g, orgs }) => (
        <div key={g}>
          <h3 className="foi-h">{GEO[g].many}</h3>
          {!orgs.length && <p className="small muted">None of the {GEO[g].plural} in these datasets serve this seat.</p>}
          {orgs.map((o) => (
            <div key={o.code} className="foi-seat-org">
              <div className="small"><strong>{o.name}</strong>{o.why && <span className="tiny muted"> · {o.why}</span>}</div>
              <div className="foi-cards">
                {o.hs.map((h) => <Card key={h.d.id} h={h} code={o.code} name={o.name} seat={s.name} onOpen={() => onOpenDataset(h.d.id)} />)}
              </div>
            </div>
          ))}
        </div>
      ))}
    </>
  );
}
