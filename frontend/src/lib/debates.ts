import type { DashboardData, Debate, Metric } from "../types";

export interface Hit {
  metric: Metric;
  value: number;
  /** Rank from the notable end: 1 = most extreme seat. */
  rank: number;
  of: number;
  /** Which end is notable: "high" (e.g. crime) or "low" (e.g. employment rate). */
  end: "high" | "low";
}


/** Metrics a debate points at, via its topics (in topic order, no duplicates, only ones in the data). */
export function debateMetrics(data: DashboardData, d: Debate): Metric[] {
  const byId = new Map(data.metrics.map((m) => [m.id, m]));
  const ids = d.topics.flatMap((t) => data.debate_topics?.find((x) => x.id === t)?.metrics ?? []);
  return [...new Set(ids)].map((id) => byId.get(id)).filter((m): m is Metric => !!m);
}

/** How one seat ranks on each metric, counted from the notable end, most notable first. */
export function standing(data: DashboardData, metrics: Metric[], seat: number): Hit[] {
  const hits: Hit[] = [];
  for (const m of metrics) {
    const vals = data.values[m.id];
    const v = vals?.[seat];
    if (v === null || v === undefined) continue;
    const end: Hit["end"] = m.polarity === "higher_better" ? "low" : "high";
    const valid = vals.filter((x): x is number => x !== null);
    const rank = 1 + valid.filter((x) => (end === "high" ? x > v : x < v)).length;
    hits.push({ metric: m, value: v, rank, of: valid.length, end });
  }
  return hits.sort((a, b) => a.rank / a.of - b.rank / b.of);
}

/** True when a hit is in the most extreme `share` of seats (the test for flagging a debate). */
export function standsOut(h: Hit, share = 0.1): boolean {
  return h.rank <= Math.max(1, Math.ceil(h.of * share));
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
