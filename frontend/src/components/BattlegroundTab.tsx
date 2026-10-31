import { useMemo } from "react";
import type { DashboardData } from "../types";
import { partyOf } from "../lib/debates";
import { partyStyle } from "../lib/parties";
import { textOn } from "../lib/colors";
import { csv, download } from "../lib/format";

export interface BattleRow {
  i: number;
  majority: number; // % of valid votes, 2024
  other: string | null; // runner-up (defences) or current holder (targets)
}

/** A party's seats ordered by 2024 majority (defences) and seats where it came second (targets). */
export function battleground(data: DashboardData, party: string): { defences: BattleRow[]; targets: BattleRow[] } {
  const maj = data.values["majority_pct"];
  const label = (p: string | null | undefined) => (p ? partyStyle(p).label : null);
  const defences: BattleRow[] = [], targets: BattleRow[] = [];
  if (!maj) return { defences, targets };
  data.seats.forEach((s, i) => {
    const m = maj[i];
    if (m === null || m === undefined) return;
    const holder = partyOf(data, i);
    if (holder === party) {
      // Runner-up in 2024; if the seat changed hands since, the 2024 winner is the challenger.
      const won = label(s.first_party_2024);
      defences.push({ i, majority: m, other: won && won !== party ? won : label(s.second_party_2024) });
    } else if (label(s.second_party_2024) === party) {
      targets.push({ i, majority: m, other: holder });
    }
  });
  defences.sort((a, b) => a.majority - b.majority);
  targets.sort((a, b) => a.majority - b.majority);
  return { defences, targets };
}

interface Props {
  data: DashboardData;
  party: string;
  parties: string[];
  setParty: (p: string) => void;
  selected: number | null;
  onSelect: (i: number) => void;
}

function Chip({ label }: { label: string | null }) {
  if (!label) return <span className="tiny muted">–</span>;
  const c = partyStyle(label).colour;
  return <span className="party mini" style={{ background: c, color: textOn(c) }}>{label}</span>;
}

export default function BattlegroundTab({ data, party, parties, setParty, selected, onSelect }: Props) {
  const { defences, targets } = useMemo(() => battleground(data, party), [data, party]);
  const hasResults = !!data.values["majority_pct"];

  const exportCsv = () =>
    download(`${party.toLowerCase().replace(/\s+/g, "-")}-battleground.csv`, csv([
      ["list", "code", "constituency", "mp", "holder", "majority_pct_2024", "swing_needed_pts", "challenger_or_runner_up"],
      ...defences.map((r) => ["defence", data.seats[r.i].code, data.seats[r.i].name, data.seats[r.i].mp, party, r.majority, r.majority / 2, r.other]),
      ...targets.map((r) => ["target", data.seats[r.i].code, data.seats[r.i].name, data.seats[r.i].mp, r.other, r.majority, r.majority / 2, party]),
    ]));

  const list = (rows: BattleRow[], kind: "defence" | "target") => (
    <ol className="rank-list battle">
      {rows.map((r, k) => {
        const s = data.seats[r.i];
        return (
          <li key={s.code} className={r.i === selected ? "sel" : ""}>
            <span className="rk">{k + 1}</span>
            <span className="grow">
              <button className="link" onClick={() => onSelect(r.i)}>{s.name}</button>
              <span className="tiny muted"> {kind === "defence" ? s.mp ?? "" : `held by ${s.mp ?? "–"}`}</span>
            </span>
            <Chip label={r.other} />
            <span className="num" title={`Swing needed: ${(r.majority / 2).toFixed(1)} points`}>{r.majority.toFixed(1)}%</span>
          </li>
        );
      })}
    </ol>
  );

  return (
    <div className="tab-body">
      <label className="field">
        <span>Party</span>
        <select value={party} onChange={(e) => setParty(e.target.value)}>
          {parties.map((p) => <option key={p}>{p}</option>)}
        </select>
      </label>
      {!hasResults ? (
        <p className="small bad">2024 election results weren't available on the last data update, so majorities can't be shown.</p>
      ) : (
        <>
          <p className="muted small">
            Majorities are from the July 2024 general election, as a share of valid votes; hover a figure for the swing needed.
            The map shades these seats only, darkest where the majority is smallest.
          </p>
          <section className="card">
            <div className="rank-head">
              <h3>Defences: {party} seats ({defences.length})</h3>
              <button className="link small" onClick={exportCsv}>CSV</button>
            </div>
            <div className="tiny muted battle-cols"><span>Seat</span><span>Main challenger</span><span>Majority</span></div>
            {defences.length ? list(defences, "defence") : <p className="small muted">No seats.</p>}
          </section>
          <section className="card">
            <h3>Targets: {party} second in 2024 ({targets.length})</h3>
            <div className="tiny muted battle-cols"><span>Seat</span><span>Held by</span><span>Majority</span></div>
            {targets.length ? list(targets, "target") : <p className="small muted">No seats.</p>}
          </section>
        </>
      )}
    </div>
  );
}
