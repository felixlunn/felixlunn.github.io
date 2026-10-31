import { useMemo } from "react";
import type { DashboardData, Debate } from "../types";
import { debateMetrics, flagSeats, leadSeat, partyOf, type Flag } from "../lib/debates";
import { partyStyle } from "../lib/parties";
import { textOn } from "../lib/colors";
import { fmt, ordinal } from "../lib/format";

interface Props {
  data: DashboardData;
  party: string;
  setParty: (p: string) => void;
  active: number | null;
  setActive: (id: number | null) => void;
  mapMetric: string | null;
  setMapMetric: (id: string) => void;
  selected: number | null;
  onSelect: (i: number) => void;
}

const dayFmt = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long" });

function rankPhrase(h: Flag["hits"][number]): string {
  return `${ordinal(h.rank)} ${h.end === "high" ? "highest" : "lowest"} of ${h.of}`;
}

export default function DebatesTab({ data, party, setParty, active, setActive, mapMetric, setMapMetric, selected, onSelect }: Props) {
  const debates = data.debates ?? [];
  const parties = useMemo(() => {
    const n = new Map<string, number>();
    data.seats.forEach((_, i) => { const p = partyOf(data, i); if (p) n.set(p, (n.get(p) ?? 0) + 1); });
    return [...n.entries()].sort((a, b) => b[1] - a[1]).map(([p]) => p);
  }, [data]);

  const rows = useMemo(() => debates.map((d) => {
    const metrics = debateMetrics(data, d);
    return { d, metrics, flags: metrics.length ? flagSeats(data, metrics, party) : [], lead: leadSeat(data, d) };
  }), [debates, data, party]);

  const byDay = useMemo(() => {
    const g = new Map<string, typeof rows>();
    for (const r of rows) g.set(r.d.date, [...(g.get(r.d.date) ?? []), r]);
    return [...g.entries()];
  }, [rows]);

  const status = data.sources.find((s) => s.id === "debates");

  return (
    <div className="tab-body">
      <p className="muted small">
        Upcoming Commons debates (not questions or statements), with the {party} MPs whose seats are in the most extreme tenth of seats on the
        figures each debate touches.
      </p>
      <label className="field">
        <span>Flag MPs from</span>
        <select value={party} onChange={(e) => setParty(e.target.value)}>
          {parties.map((p) => <option key={p}>{p}</option>)}
        </select>
      </label>

      {status?.status === "failed" && <p className="small bad">The parliamentary calendar couldn't be loaded on the last data update.</p>}
      {!debates.length && status?.status !== "failed" && <p className="small muted">No debates are scheduled in the next three weeks.</p>}

      {byDay.map(([day, items]) => (
        <section key={day} className="debate-day">
          <h3>{dayFmt.format(new Date(`${day}T12:00:00`))}</h3>
          {items.map(({ d, metrics, flags, lead }) => (
            <DebateCard key={d.id} d={d} metrics={metrics} flags={flags} lead={lead} data={data} party={party}
              open={active === d.id} onToggle={() => setActive(active === d.id ? null : d.id)}
              mapMetric={mapMetric} setMapMetric={setMapMetric} selected={selected} onSelect={onSelect} />
          ))}
        </section>
      ))}
      {status?.as_of && <p className="tiny muted">Calendar checked {status.as_of}. Source: UK Parliament What's On.</p>}
    </div>
  );
}

function DebateCard({ d, metrics, flags, lead, data, party, open, onToggle, mapMetric, setMapMetric, selected, onSelect }: {
  d: Debate; metrics: ReturnType<typeof debateMetrics>; flags: Flag[]; lead: number | null; data: DashboardData; party: string;
  open: boolean; onToggle: () => void; mapMetric: string | null; setMapMetric: (id: string) => void; selected: number | null; onSelect: (i: number) => void;
}) {
  const topicLabels = d.topics.map((t) => data.debate_topics?.find((x) => x.id === t)?.label ?? t);
  const leadIsParty = lead !== null && partyOf(data, lead) === party;
  const summary = !metrics.length ? "No matching data" : flags.length ? `${flags.length} ${party} MP${flags.length > 1 ? "s" : ""} to brief` : `No ${party} seats stand out`;
  return (
    <article className={`debate ${open ? "open" : ""} ${flags.length ? "has-flags" : ""}`}>
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
        <div className={`debate-flags ${flags.length ? "on" : ""}`}>{leadIsParty ? `Led by a ${party} MP · ` : ""}{summary}</div>
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
          {flags.length > 0 && (
            <ol className="flag-list">
              {flags.map((f) => {
                const s = data.seats[f.seat];
                return (
                  <li key={s.code} className={f.seat === selected ? "sel" : ""}>
                    <button className="link strong" onClick={() => onSelect(f.seat)}>{s.mp ?? s.name}</button>
                    <span className="tiny muted"> {s.name}</span>
                    <ul>
                      {f.hits.slice(0, 3).map((h) => (
                        <li key={h.metric.id} className="small">
                          {h.metric.label}: <strong>{fmt(h.metric, h.value)}</strong> <span className="muted">({rankPhrase(h)}; national {fmt(h.metric, h.metric.national)})</span>
                        </li>
                      ))}
                      {f.hits.length > 3 && <li className="tiny muted">+{f.hits.length - 3} more</li>}
                    </ul>
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      )}
    </article>
  );
}
