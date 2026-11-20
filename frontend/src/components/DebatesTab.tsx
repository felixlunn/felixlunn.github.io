import { useEffect, useMemo, useState } from "react";
import type { DashboardData, Debate } from "../types";
import { debateMetrics, leadSeat, standing, standsOut, type Hit } from "../lib/debates";
import { partyStyle } from "../lib/parties";
import { textOn } from "../lib/colors";
import { fmt, ordinal } from "../lib/format";
import { missingFor } from "../lib/missing";
import NoData from "./NoData";
import SourceLink from "./SourceLink";
import { ChangeBadge } from "./Trend";
import { seriesFor, type History } from "../lib/history";

interface Props {
  data: DashboardData;
  /** The seat whose local figures lead every debate card: the office's seat, or else the seat being viewed. */
  mySeat: number | null;
  history: History | null;
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

export default function DebatesTab({ data, mySeat, history, active, setActive, mapMetric, setMapMetric, onSelect }: Props) {
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
          Choose your MP in the bar at the top (or open a seat on the map) to see that seat's figures on every debate, and which
          debates it stands out on.
        </p>
      ) : (
        <>
          <p className="small">
            Each debate shows <strong>{seat.name}</strong>'s figures on its topic, most notable first.{" "}
            <strong>{flaggedCount}</strong> {flaggedCount === 1 ? "debate is" : "debates are"} highlighted, where the seat is in the most extreme
            tenth of seats or {seat.mp ?? "its MP"} is leading.
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
            <DebateCard key={r.d.id} {...r} data={data} mySeat={mySeat} history={history}
              open={active === r.d.id} onToggle={() => setActive(active === r.d.id ? null : r.d.id)}
              mapMetric={mapMetric} setMapMetric={setMapMetric} onSelect={onSelect} />
          ))}
        </section>
      ))}
      {status?.as_of && <p className="tiny muted">Calendar checked {status.as_of}. Source: UK Parliament What's On.</p>}
    </div>
  );
}

const LOCAL_FIGURES = 3; // figures shown on each card before it is opened

function DebateCard({ d, metrics, mine, leading, flagged, data, mySeat, history, open, onToggle, mapMetric, setMapMetric, onSelect }: {
  d: Debate; metrics: ReturnType<typeof debateMetrics>; mine: Hit[]; standouts: Hit[]; leading: boolean; flagged: boolean;
  data: DashboardData; mySeat: number | null; history: History | null;
  open: boolean; onToggle: () => void; mapMetric: string | null; setMapMetric: (id: string) => void; onSelect: (i: number) => void;
}) {
  const topicLabels = d.topics.map((t) => data.debate_topics?.find((x) => x.id === t)?.label ?? t);
  const lead = leadSeat(data, d);
  const missing = mySeat !== null ? missingFor(data, mySeat, metrics) : [];
  return (
    <article id={`debate-${d.id}`} className={`debate ${open ? "open" : ""} ${flagged ? "is-mine" : ""}`}>
      <button className="debate-head" onClick={onToggle} aria-expanded={open} disabled={!metrics.length && !d.members.length}>
        <div className="tiny muted">{[d.time, d.venue, d.category].filter(Boolean).join(" · ")}</div>
        <div className="debate-title">{d.title}</div>

        {/* Local figures first, always: the seat's numbers on this debate's topic. */}
        <div className="local-figs">
          {mySeat === null ? (
            <div className="tiny muted">Choose your MP at the top to see local figures for this debate.</div>
          ) : !metrics.length ? (
            <div className="tiny muted">No local figures match this debate's topic.</div>
          ) : !mine.length ? (
            <div className="small"><NoData reason="No data for this seat on these figures" /> <span className="tiny muted">for {data.seats[mySeat].name} on this topic</span></div>
          ) : (
            <>
              <div className="local-seat tiny">
                {data.seats[mySeat].name}
                {leading && <span className="lead-flag"> · your MP is leading this debate</span>}
              </div>
              <ul>
                {mine.slice(0, LOCAL_FIGURES).map((h) => {
                  const s = seriesFor(history, h.metric.id, mySeat);
                  return (
                    <li key={h.metric.id} className={standsOut(h) ? "stand" : ""}>
                      <span className="lf-value">{fmt(h.metric, h.value)}</span>
                      <span className="lf-label">{h.metric.label}<SourceLink metric={h.metric} /></span>
                      <span className="lf-rank">{rankPhrase(h)} · national {fmt(h.metric, h.metric.national)}{s && <> · <ChangeBadge metric={h.metric} series={s} /></>}</span>
                    </li>
                  );
                })}
              </ul>
              {mine.length + missing.length > LOCAL_FIGURES && (
                <div className="tiny muted">{open ? "" : `+${mine.length + missing.length - LOCAL_FIGURES} more figures: open the debate`}</div>
              )}
            </>
          )}
        </div>

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
      </button>

      {open && (
        <div className="debate-body">
          {mySeat !== null && (mine.length > LOCAL_FIGURES || missing.length > 0) && (
            <div className="local-figs more-figs">
              <div className="local-seat tiny">More figures for {data.seats[mySeat].name}</div>
              <ul>
                {mine.slice(LOCAL_FIGURES).map((h) => (
                  <li key={h.metric.id} className={standsOut(h) ? "stand" : ""}>
                    <span className="lf-value">{fmt(h.metric, h.value)}</span>
                    <span className="lf-label">{h.metric.label}<SourceLink metric={h.metric} /></span>
                    <span className="lf-rank">{rankPhrase(h)} · national {fmt(h.metric, h.metric.national)}</span>
                  </li>
                ))}
                {missing.map(({ metric, reason }) => (
                  <li key={metric.id}>
                    <span className="lf-value"><NoData reason={reason} /></span>
                    <span className="lf-label">{metric.label}<SourceLink metric={metric} /></span>
                    <span className="lf-rank">{reason}</span>
                  </li>
                ))}
              </ul>
              <div className="tiny muted">Coloured: in the most extreme tenth of seats.</div>
            </div>
          )}
          {metrics.length > 0 && (
            <label className="debate-shade">
              <span className="tiny muted">Shade the map by</span>
              <select value={metrics.some((m) => m.id === mapMetric) ? mapMetric ?? "" : metrics[0].id} onChange={(e) => setMapMetric(e.target.value)}>
                {metrics.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
              </select>
            </label>
          )}
          {lead !== null && (
            <p className="small">Lead member's seat: <button className="link" onClick={() => onSelect(lead)}>{data.seats[lead].name}</button></p>
          )}
          {!metrics.length && <p className="small muted">This debate's title doesn't match a topic with figures.</p>}
        </div>
      )}
    </article>
  );
}
