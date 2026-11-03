import { useEffect, useMemo, useState } from "react";
import type { DashboardData, Debate } from "../types";
import { debateMetrics, leadSeat, standing, standsOut, type Hit } from "../lib/debates";
import { partyStyle } from "../lib/parties";
import { textOn } from "../lib/colors";
import { fmt, ordinal } from "../lib/format";
import { missingFor } from "../lib/missing";
import NoData from "./NoData";
import SourceLink from "./SourceLink";

interface Props {
  data: DashboardData;
  /** The seat of the MP chosen in the toolbar, if any. Debates are flagged only for this seat. */
  mySeat: number | null;
  active: number | null;
  setActive: (id: number | null) => void;
  mapMetric: string | null;
  setMapMetric: (id: string) => void;
  onSelect: (i: number) => void;
}

const dayFmt = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long" });

function rankPhrase(h: Hit): string {
  // Count from whichever end is nearer, so a low-ranked seat reads "115th lowest", not "461st highest".
  const [hi, lo] = h.end === "high" ? ["highest", "lowest"] : ["lowest", "highest"];
  return h.rank <= h.of / 2 ? `${ordinal(h.rank)} ${hi} of ${h.of}` : `${ordinal(h.of - h.rank + 1)} ${lo} of ${h.of}`;
}

export default function DebatesTab({ data, mySeat, active, setActive, mapMetric, setMapMetric, onSelect }: Props) {
  const [onlyMine, setOnlyMine] = useState(false);
  // Bring an opened debate into view (e.g. when arriving from the seat briefing).
  useEffect(() => {
    if (active !== null) document.getElementById(`debate-${active}`)?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [active]);
  const debates = data.debates ?? [];

  const rows = useMemo(() => debates.map((d) => {
    const metrics = debateMetrics(data, d);
    const leading = mySeat !== null && leadSeat(data, d) === mySeat;
    const mine = mySeat !== null && metrics.length ? standing(data, metrics, mySeat) : [];
    // Flagged only when the chosen MP is leading, or their seat is in the most extreme tenth on one of the debate's figures.
    const standouts = mine.filter((h) => standsOut(h));
    return { d, metrics, mine, standouts, leading, flagged: leading || standouts.length > 0 };
  }), [debates, data, mySeat]);
  const flaggedCount = rows.filter((r) => r.flagged).length;
  const shown = onlyMine && mySeat !== null ? rows.filter((r) => r.flagged) : rows;

  const byDay = useMemo(() => {
    const g = new Map<string, typeof rows>();
    for (const r of shown) g.set(r.d.date, [...(g.get(r.d.date) ?? []), r]);
    return [...g.entries()];
  }, [shown]);

  const status = data.sources.find((s) => s.id === "debates");
  const seat = mySeat !== null ? data.seats[mySeat] : null;

  return (
    <div className="tab-body">
      <p className="muted small">Upcoming Commons debates (not questions, statements or Private Members' Bills).</p>
      {seat === null ? (
        <p className="small">
          Choose your MP in the bar at the top to flag the debates where their seat stands out: in the most extreme tenth of seats
          on a figure the debate touches, or where they're leading the debate.
        </p>
      ) : (
        <>
          <p className="small">
            <strong>{flaggedCount}</strong> {flaggedCount === 1 ? "debate stands" : "debates stand"} out for {seat.mp ?? seat.name} ({seat.name}).
          </p>
          <label className="check small">
            <input type="checkbox" checked={onlyMine} onChange={(e) => setOnlyMine(e.target.checked)} />
            Only show these
          </label>
        </>
      )}

      {status?.status === "failed" && <p className="small bad">The parliamentary calendar couldn't be loaded on the last data update.</p>}
      {data.debates === undefined && <p className="small muted">This copy of the data predates the debates calendar. Refresh the page to load the latest data.</p>}
      {data.debates !== undefined && !debates.length && status?.status !== "failed" && <p className="small muted">No debates are scheduled in the next three weeks.</p>}
      {debates.length > 0 && !shown.length && <p className="small muted">None of the upcoming debates touch figures where your seat stands out.</p>}

      {byDay.map(([day, items]) => (
        <section key={day} className="debate-day">
          <h3>{dayFmt.format(new Date(`${day}T12:00:00`))}</h3>
          {items.map((r) => (
            <DebateCard key={r.d.id} {...r} data={data} mySeat={mySeat}
              open={active === r.d.id} onToggle={() => setActive(active === r.d.id ? null : r.d.id)}
              mapMetric={mapMetric} setMapMetric={setMapMetric} onSelect={onSelect} />
          ))}
        </section>
      ))}
      {status?.as_of && <p className="tiny muted">Calendar checked {status.as_of}. Source: UK Parliament What's On.</p>}
    </div>
  );
}

function DebateCard({ d, metrics, mine, standouts, leading, flagged, data, mySeat, open, onToggle, mapMetric, setMapMetric, onSelect }: {
  d: Debate; metrics: ReturnType<typeof debateMetrics>; mine: Hit[]; standouts: Hit[]; leading: boolean; flagged: boolean;
  data: DashboardData; mySeat: number | null;
  open: boolean; onToggle: () => void; mapMetric: string | null; setMapMetric: (id: string) => void; onSelect: (i: number) => void;
}) {
  const topicLabels = d.topics.map((t) => data.debate_topics?.find((x) => x.id === t)?.label ?? t);
  const lead = leadSeat(data, d);
  const top = standouts[0];
  return (
    <article id={`debate-${d.id}`} className={`debate ${open ? "open" : ""} ${flagged ? "is-mine" : ""}`}>
      <button className="debate-head" onClick={onToggle} aria-expanded={open} disabled={!metrics.length && !d.members.length}>
        <div className="tiny muted">{[d.time, d.venue, d.category].filter(Boolean).join(" · ")}</div>
        <div className="debate-title">{d.title}</div>
        <div className="debate-meta">
          {d.members.slice(0, 1).map((m) => {
            const st = m.party ? partyStyle(m.party) : null;
            return (
              <span key={m.name} className="party" style={st ? { background: st.colour, color: textOn(st.colour) } : undefined}>
                {m.name}{st ? ` · ${st.label}` : ""}
              </span>
            );
          })}
          {topicLabels.map((t) => <span key={t} className="topic">{t}</span>)}
        </div>
        {!flagged && mySeat !== null && metrics.length > 0 && mine.length === 0 && (
          <div className="debate-mine"><NoData reason="Your seat has no data on any figure this debate touches" /> <span className="tiny muted">for your seat on these figures</span></div>
        )}
        {flagged && (
          <div className="debate-mine on">
            {leading ? "Your MP is leading this debate" : "Your seat stands out"}
            {top && <>{leading ? " · " : ": "}{top.metric.label} {fmt(top.metric, top.value)}, {rankPhrase(top)}<SourceLink metric={top.metric} /></>}
            {standouts.length > 1 && <span className="muted"> (+{standouts.length - 1} more)</span>}
          </div>
        )}
      </button>

      {open && (
        <div className="debate-body">
          {lead !== null && (
            <p className="small">Lead member's seat: <button className="link" onClick={() => onSelect(lead)}>{data.seats[lead].name}</button></p>
          )}
          {metrics.length > 0 && (
            <>
              <div className="tiny muted">Shade the map by</div>
              <div className="chips">
                {metrics.map((m) => (
                  <button key={m.id} className={`chip ${mapMetric === m.id ? "on" : ""}`} onClick={() => setMapMetric(m.id)}>{m.label}</button>
                ))}
              </div>
            </>
          )}
          {mySeat !== null && (mine.length > 0 || missingFor(data, mySeat, metrics).length > 0) && (
            <div className="my-standing">
              <div className="tiny muted">{data.seats[mySeat].name} on these figures (bold: in the most extreme tenth of seats)</div>
              <ul>
                {mine.map((h) => (
                  <li key={h.metric.id} className={`small ${standsOut(h) ? "strong" : ""}`}>
                    {h.metric.label}: {fmt(h.metric, h.value)}<SourceLink metric={h.metric} /> <span className="muted">({rankPhrase(h)}; national {fmt(h.metric, h.metric.national)})</span>
                  </li>
                ))}
                {missingFor(data, mySeat, metrics).map(({ metric, reason }) => (
                  <li key={metric.id} className="small">
                    {metric.label}: <NoData reason={reason} /><SourceLink metric={metric} /> <span className="muted">({reason}; not counted)</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {!metrics.length && <p className="small muted">This debate's title doesn't match a topic with figures.</p>}
        </div>
      )}
    </article>
  );
}
