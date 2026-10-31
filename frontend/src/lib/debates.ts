import type { DashboardData, Debate, Metric } from "../types";
import { partyStyle } from "./parties";

export interface Hit {
  metric: Metric;
  value: number;
  /** Rank from the notable end: 1 = most extreme seat. */
  rank: number;
  of: number;
  /** Which end is notable: "high" (e.g. crime) or "low" (e.g. employment rate). */
  end: "high" | "low";
}

export interface Flag {
  seat: number;
  hits: Hit[];
}

/** Metrics a debate points at, via its topics (in topic order, no duplicates, only ones in the data). */
export function debateMetrics(data: DashboardData, d: Debate): Metric[] {
  const byId = new Map(data.metrics.map((m) => [m.id, m]));
  const ids = d.topics.flatMap((t) => data.debate_topics?.find((x) => x.id === t)?.metrics ?? []);
  return [...new Set(ids)].map((id) => byId.get(id)).filter((m): m is Metric => !!m);
}

export function partyOf(data: DashboardData, i: number): string | null {
  const s = data.seats[i];
  return s.party ? partyStyle(s.party, s.party_colour).label : null;
}

/**
 * Seats held by `party` that are among the most extreme `share` of all seats on any of `metrics`.
 * "Extreme" is the worse end where a metric has a polarity (low employment, high crime),
 * otherwise the high end (the topic lists metrics where a high value is the notable one).
 */
export function flagSeats(data: DashboardData, metrics: Metric[], party: string, share = 0.1): Flag[] {
  const members = data.seats.map((_, i) => i).filter((i) => partyOf(data, i) === party);
  const flags = new Map<number, Hit[]>();
  for (const m of metrics) {
    const vals = data.values[m.id];
    if (!vals) continue;
    const end: Hit["end"] = m.polarity === "higher_better" ? "low" : "high";
    const valid = vals.filter((v): v is number => v !== null);
    const cut = Math.max(1, Math.ceil(valid.length * share));
    for (const i of members) {
      const v = vals[i];
      if (v === null || v === undefined) continue;
      // Rank from the notable end; ties share the better rank.
      const rank = 1 + valid.filter((x) => (end === "high" ? x > v : x < v)).length;
      if (rank <= cut) {
        const hits = flags.get(i) ?? [];
        hits.push({ metric: m, value: v, rank, of: valid.length, end });
        flags.set(i, hits);
      }
    }
  }
  return [...flags.entries()]
    .map(([seat, hits]) => ({ seat, hits: hits.sort((a, b) => a.rank / a.of - b.rank / b.of) }))
    .sort((a, b) => b.hits.length - a.hits.length || a.hits[0].rank / a.hits[0].of - b.hits[0].rank / b.hits[0].of);
}

/** Seat index of a debate's lead member, matched on constituency name. */
export function leadSeat(data: DashboardData, d: Debate): number | null {
  const norm = (s: string) => s.toLowerCase().replace(/&/g, "and").replace(/[^a-z0-9]+/g, " ").trim();
  for (const m of d.members) {
    if (!m.constituency) continue;
    const i = data.seats.findIndex((s) => norm(s.name) === norm(m.constituency!));
    if (i >= 0) return i;
  }
  return null;
}
