import { useEffect, useState } from "react";
import { dataUrl } from "./dataUrl";

/** policing.json: each seat's neighbourhood policing teams and their current priorities (police.uk). */
export interface PolicingTeam {
  force: string;
  team: string;
  url?: string;
  priorities: { issue: string; date: string }[];
}
export interface PolicingFile { as_of: string; seats: Record<string, PolicingTeam[]> }

let cached: PolicingFile | null | undefined;
let pending: Promise<PolicingFile | null> | null = null;

function load(): Promise<PolicingFile | null> {
  pending ??= fetch(dataUrl("policing.json"))
    .then((r) => (r.ok ? (r.json() as Promise<PolicingFile>) : null))
    .catch(() => null)
    .then((p) => (cached = p && typeof p === "object" && p.seats ? p : null));
  return pending;
}

/** The priorities file, loaded once when a briefing first needs it (null until loaded, or if this deploy has none). */
export function usePolicing(): PolicingFile | null {
  const [p, setP] = useState<PolicingFile | null>(cached ?? null);
  useEffect(() => {
    if (cached !== undefined) { setP(cached); return; }
    let live = true;
    load().then((x) => live && setP(x));
    return () => { live = false; };
  }, []);
  return p;
}

/** One line per distinct priority in a seat (forces often set the same one for every team), with the teams that set
 * it; those set by most teams first, then the newest. */
export interface PriorityLine { issue: string; teams: string[]; force: string; date: string }

export function priorityLines(teams: PolicingTeam[]): PriorityLine[] {
  const by = new Map<string, PriorityLine>();
  for (const t of teams) {
    for (const p of t.priorities) {
      const k = p.issue.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
      const line = by.get(k);
      if (!line) by.set(k, { issue: p.issue, teams: [t.team], force: t.force, date: p.date });
      else {
        if (!line.teams.includes(t.team)) line.teams.push(t.team);
        if (p.date > line.date) line.date = p.date;
      }
    }
  }
  return [...by.values()].sort((a, b) => b.teams.length - a.teams.length || b.date.localeCompare(a.date));
}
