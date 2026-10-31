import { useMemo, useState } from "react";
import type { DashboardData, NeighbourhoodFile } from "../types";
import { profileMetrics, rankOf, similarity, stats, topN } from "../lib/analytics";
import { debateMetrics, leadSeat, standing, standsOut } from "../lib/debates";
import { partyStyle } from "../lib/parties";
import { textOn } from "../lib/colors";
import { fmt, ordinal, rankText } from "../lib/format";
import { officeLink } from "./OfficePicker";

interface Props {
  data: DashboardData;
  office: number | null;
  nbFile: NeighbourhoodFile | null;
  onBriefing: (i: number) => void;
  onDebate: (id: number) => void;
  onMetric: (id: string) => void;
  onNeighbourhoods: () => void;
  onBrowse: () => void;
  onSelect: (i: number) => void;
}

const dayFmt = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short" });

/** The landing tab: everything for the user's own MP in one place, or a prompt to choose them. */
export default function HomeTab({ data, office, nbFile, onBriefing, onDebate, onMetric, onNeighbourhoods, onBrowse, onSelect }: Props) {
  if (office === null) {
    return (
      <div className="tab-body home">
        <section className="welcome">
          <h2>Which MP's office are you in?</h2>
          <p className="small muted">
            Choose your MP and the dashboard opens on their seat: the debates coming up where it stands out, what is unusual about it,
            its neighbourhoods and the seats most like it. Saved in this browser.
          </p>
          <button className="btn primary" onClick={() => (document.querySelector(".office-search-bar input") as HTMLInputElement | null)?.focus()}>
            ↑ Choose your MP in the bar at the top
          </button>
          <button className="link small" onClick={onBrowse}>Or browse every seat without choosing</button>
        </section>
      </div>
    );
  }
  return <SeatHome {...{ data, office, nbFile, onBriefing, onDebate, onMetric, onNeighbourhoods, onSelect }} />;
}

function SeatHome({ data, office, nbFile, onBriefing, onDebate, onMetric, onNeighbourhoods, onSelect }: Omit<Props, "office" | "setOffice" | "onBrowse"> & { office: number }) {
  const seat = data.seats[office];
  const party = seat.party ? partyStyle(seat.party, seat.party_colour) : null;
  const [copied, setCopied] = useState(false);
  const val = (id: string) => data.values[id]?.[office] ?? null;

  // Upcoming debates that matter to this seat: led by its MP, or touching figures where it is in the most extreme tenth.
  const debates = useMemo(() => (data.debates ?? []).map((d) => {
    const metrics = debateMetrics(data, d);
    const hits = metrics.length ? standing(data, metrics, office) : [];
    const leading = leadSeat(data, d) === office;
    return { d, top: hits[0], leading, relevant: leading || (hits.length > 0 && standsOut(hits[0])) };
  }).filter((x) => x.relevant), [data, office]);

  const standouts = useMemo(() => data.metrics
    .filter((m) => m.theme !== "politics" && m.unit !== "people" && m.coverage > 100)
    .map((m) => {
      const v = data.values[m.id][office];
      if (v === null) return null;
      const s = stats(data.values[m.id]);
      return { m, v, z: s.sd ? (v - s.mean) / s.sd : 0, r: rankOf(data.values[m.id], office) };
    })
    .filter((x): x is NonNullable<typeof x> => x !== null)
    .sort((a, b) => Math.abs(b.z) - Math.abs(a.z))
    .slice(0, 6), [data, office]);

  const twins = useMemo(() => {
    const ids = profileMetrics(data.metrics);
    return ids.length ? topN(data, similarity(data, office, ids, "euclidean"), 5, { exclude: office }) : [];
  }, [data, office]);

  const deprived = useMemo(() => {
    if (!nbFile?.imd_decile || nbFile.seat !== seat.code) return null;
    const rows = nbFile.lsoas.map((l, k) => ({ l, d: nbFile.imd_decile![k] })).filter((r) => r.d !== null) as { l: NeighbourhoodFile["lsoas"][number]; d: number }[];
    if (!rows.length) return null;
    const worst = rows.filter((r) => r.d <= 2).sort((a, b) => a.d - b.d);
    const wards = [...new Set(worst.map((r) => r.l.ward ?? r.l.name))];
    return { total: rows.length, count: worst.length, wards };
  }, [nbFile, seat.code]);
  const hasNeighbourhoods = data.neighbourhoods?.seats.includes(seat.code);

  const copy = async () => {
    try { await navigator.clipboard.writeText(officeLink(seat)); setCopied(true); setTimeout(() => setCopied(false), 2000); }
    catch { window.prompt("Copy this link", officeLink(seat)); }
  };

  const majority = val("majority_pct"), turnout = val("turnout");
  return (
    <div className="tab-body home">
      <section className="home-head">
        <div className="eyebrow">{[seat.region, seat.country].filter((x, i, a) => x && a.indexOf(x) === i).join(" · ")}</div>
        <h2>{seat.name}</h2>
        <div className="home-mp">
          {party && <span className="party" style={{ background: party.colour, color: textOn(party.colour) }}>{party.label}</span>}
          <strong>{seat.mp ?? "Vacant"}</strong>
        </div>
        {(majority !== null || turnout !== null) && (
          <div className="home-stats">
            {majority !== null && <div><span className="tiny muted">2024 majority</span><strong>{majority.toFixed(1)}%</strong></div>}
            {turnout !== null && <div><span className="tiny muted">Turnout</span><strong>{turnout.toFixed(1)}%</strong></div>}
            {seat.second_party_2024 && <div><span className="tiny muted">Runner-up</span><strong>{partyStyle(seat.second_party_2024).label}</strong></div>}
          </div>
        )}
        <div className="home-actions">
          <button className="btn" onClick={() => onBriefing(office)}>Full briefing</button>
          <button className="link small" onClick={copy}>{copied ? "Link copied" : "Copy link for this office"}</button>
        </div>
      </section>

      <section className="card">
        <h3>Coming up in Parliament for {seat.mp ?? seat.name}</h3>
        {debates.length ? (
          <ul className="home-list">
            {debates.slice(0, 6).map(({ d, top, leading }) => (
              <li key={d.id}>
                <button className="home-item" onClick={() => onDebate(d.id)}>
                  <span className="tiny muted">{dayFmt.format(new Date(`${d.date}T12:00:00`))}{d.time ? ` · ${d.time}` : ""} · {d.venue}</span>
                  <span className="home-item-title">{d.title}</span>
                  <span className="small accent">
                    {leading ? "Your MP is leading this debate" : null}
                    {leading && top ? " · " : null}
                    {top ? `${top.metric.label} ${fmt(top.metric, top.value)}, ${ordinal(top.rank)} ${top.end === "high" ? "highest" : "lowest"} of ${top.of}` : null}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="small muted">None of the debates in the next three weeks touch figures where {seat.name} stands out.</p>
        )}
        <button className="link small" onClick={() => onDebate(-1)}>All upcoming debates</button>
      </section>

      <section className="card">
        <h3>What stands out about {seat.name}</h3>
        <ul className="home-list">
          {standouts.map(({ m, v, r }) => (
            <li key={m.id}>
              <button className="home-row" onClick={() => onMetric(m.id)}>
                <span className="grow">{m.label}</span>
                <strong>{fmt(m, v)}</strong>
                <span className="tiny muted">{rankText(r.rank, r.of)} · national {fmt(m, m.national)}</span>
              </button>
            </li>
          ))}
        </ul>
        <button className="link small" onClick={() => onBriefing(office)}>Every figure for this seat</button>
      </section>

      {hasNeighbourhoods && (
        <section className="card">
          <h3>Neighbourhoods</h3>
          {deprived ? (
            <p className="small">
              <strong>{deprived.count} of {deprived.total}</strong> neighbourhoods are among the 20% most deprived in England
              {deprived.wards.length > 0 && <>, in {deprived.wards.slice(0, 4).join(", ")}{deprived.wards.length > 4 ? ` and ${deprived.wards.length - 4} more wards` : ""}</>}.
            </p>
          ) : (
            <p className="small muted">Census figures for every neighbourhood (LSOA) in the seat, ward by ward.</p>
          )}
          <button className="btn" onClick={onNeighbourhoods}>Explore neighbourhoods</button>
        </section>
      )}

      {twins.length > 0 && (
        <section className="card">
          <h3>Seats most like {seat.name}</h3>
          <ol className="rank-list">
            {twins.map((t, k) => (
              <li key={t.code}>
                <span className="rk">{k + 1}</span>
                <button className="link grow" onClick={() => onSelect(t.index)}>{t.name}</button>
                <span className="tiny muted">{data.seats[t.index].party ? partyStyle(data.seats[t.index].party!).label : ""}</span>
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}
