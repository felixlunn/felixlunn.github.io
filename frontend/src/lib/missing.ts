import type { DashboardData, Metric } from "../types";

const NATIONS: Record<string, string> = { E: "England", W: "Wales", S: "Scotland", N: "Northern Ireland" };

/** Nations (code prefix letters) where a metric has at least one value. */
function nationsWithData(data: DashboardData, m: Metric): Set<string> {
  const vals = data.values[m.id] ?? [];
  const out = new Set<string>();
  vals.forEach((v, i) => { if (v !== null && v !== undefined) out.add(data.seats[i].code[0]); });
  return out;
}

const cache = new WeakMap<DashboardData, Map<string, Set<string>>>();

/** Why a seat has no value for a metric, or null when it has one. */
export function missingReason(data: DashboardData, m: Metric, seat: number): string | null {
  const v = data.values[m.id]?.[seat];
  if (v !== null && v !== undefined && !Number.isNaN(v)) return null;
  let byMetric = cache.get(data);
  if (!byMetric) cache.set(data, (byMetric = new Map()));
  let nations = byMetric.get(m.id);
  if (!nations) byMetric.set(m.id, (nations = nationsWithData(data, m)));
  const nation = data.seats[seat].code[0];
  if (!nations.has(nation)) {
    const covered = [...nations].map((n) => NATIONS[n] ?? n).join(", ");
    return `Not published for ${NATIONS[nation] ?? "this nation"}${covered ? ` (covers ${covered})` : ""}`;
  }
  return "No data for this seat";
}

export interface Missing { metric: Metric; reason: string }

/** Every metric the seat has no value for, seat-specific gaps first. */
export function missingFor(data: DashboardData, seat: number, metrics: Metric[] = data.metrics): Missing[] {
  return metrics
    .map((metric) => ({ metric, reason: missingReason(data, metric, seat) }))
    .filter((x): x is Missing => x.reason !== null)
    .sort((a, b) => Number(a.reason.startsWith("Not published")) - Number(b.reason.startsWith("Not published")));
}
