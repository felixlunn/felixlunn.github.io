/** Turning a matched FOI dataset into map values, rankings and a seat's view. */

import { targets } from "./match";
import { describe } from "./stats";
import { IS_AREA, type Column, type Dataset, type Geography, type Reference, type Target } from "./types";

export interface Point { code: string; name: string; lat: number; lon: number; area: string | null; seat: string | null; sub: string }

export function points(ref: Reference, g: Geography): Point[] {
  if (g === "court") return (ref.points.courts ?? []).map((c) => ({ code: c.id, name: c.name, lat: c.lat, lon: c.lon, area: c.area, seat: c.seat, sub: c.types.join(", ") }));
  if (g === "nhs_trust") return (ref.points.trusts ?? []).map((t) => ({ code: t.code, name: t.name, lat: t.lat, lon: t.lon, area: t.area, seat: t.seat, sub: t.kind }));
  return [];
}

export function canPerHead(d: Dataset, col: Column | undefined): boolean {
  return IS_AREA[d.geography] && col?.unit === "count";
}

export interface Ranked { target: Target; value: number | null; raw: number | null; suppressed?: string; rank: number | null }

/** Every matched row's value for one column (optionally per 100,000 residents), ranked highest first. */
export function ranked(ref: Reference, d: Dataset, colKey: string, perHead: boolean): Ranked[] {
  const byCode = new Map(targets(ref, d.geography).map((t) => [t.code, t]));
  const rows: Ranked[] = [];
  for (const r of d.rows) {
    const t = byCode.get(r.code);
    if (!t) continue;
    const raw = r.values[colKey] ?? null;
    const value = raw === null ? null : perHead ? (t.population ? (raw * 100_000) / t.population : null) : raw;
    rows.push({ target: t, value, raw, suppressed: r.suppressed?.[colKey], rank: null });
  }
  const order = rows.filter((r) => r.value !== null).sort((a, b) => b.value! - a.value!);
  order.forEach((r, i) => { r.rank = i > 0 && order[i - 1].value === r.value ? order[i - 1].rank : i + 1; });
  return [...order, ...rows.filter((r) => r.value === null)];
}

export function summary(rows: Ranked[]) {
  return { ...describe(rows.map((r) => r.value)), withheld: rows.filter((r) => r.suppressed).length };
}

/** For count columns on area geographies: all the areas' counts over all their residents, per 100,000. */
export function overallRate(rows: Ranked[]): number | null {
  let num = 0, pop = 0;
  for (const r of rows) {
    if (r.raw !== null && r.target.population) { num += r.raw; pop += r.target.population; }
  }
  return pop ? (num * 100_000) / pop : null;
}

/** The targets that serve a seat: the area(s) it lies in, or the courts / trusts in it and in its wider area. */
export function forSeat(ref: Reference, g: Geography, seat: string): { code: string; why: string }[] {
  if (g === "police_force" || g === "health_area") {
    const areas = g === "police_force" ? ref.layers.police.areas : ref.layers.health.areas;
    return areas.flatMap((a) => {
      const hit = a.seats.find(([s]) => s === seat);
      return hit ? [{ code: a.code, why: hit[1] >= 0.97 ? "covers the whole seat" : `covers ${Math.round(hit[1] * 100)}% of the seat` }] : [];
    });
  }
  const pts = points(ref, g);
  // Acute trusts: their official catchment says which seats they serve.
  const fromCatchment = g === "nhs_trust" ? (ref.points.trusts ?? []).flatMap((t) => {
    const hit = t.catchment?.find(([s]) => s === seat);
    return hit ? [{ code: t.code, why: hit[1] >= 0.97 ? "its catchment covers the whole seat" : `its catchment covers ${Math.round(hit[1] * 100)}% of the seat` }] : [];
  }) : [];
  const done = new Set(fromCatchment.map((x) => x.code));
  const areaLayer = g === "court" ? ref.layers.police.areas : ref.layers.health.areas;
  const seatAreas = new Set(areaLayer.filter((a) => a.seats.some(([s]) => s === seat)).map((a) => a.code));
  const areaName = new Map(areaLayer.map((a) => [a.code, a.name]));
  return [...fromCatchment, ...pts.filter((p) => !done.has(p.code) && (p.seat === seat || (p.area && seatAreas.has(p.area))))
    .sort((a, b) => Number(b.seat === seat) - Number(a.seat === seat))
    .map((p) => ({ code: p.code, why: p.seat === seat ? "head office in the seat" : `elsewhere in ${areaName.get(p.area!) ?? "the same area"}` }))];
}

export function fmtValue(v: number | null, col: Column | undefined, perHead = false): string {
  if (v === null) return "–";
  const abs = Math.abs(v);
  const dp = perHead ? 1 : abs >= 100 || Number.isInteger(v) ? 0 : abs >= 10 ? 1 : 2;
  const s = v.toLocaleString("en-GB", { maximumFractionDigits: dp, minimumFractionDigits: 0 }).replace(/^-/, "−");
  const sign = col?.change && v > 0 ? "+" : "";
  if (col?.unit === "money") return `${v < 0 ? "−" : sign}£${s.replace("−", "")}`;
  if (col?.unit === "percent") return `${sign}${s}%`;
  return `${sign}${s}`;
}

const LIB_DEM = /^(liberal democrats?|lib ?dems?|ld)$/i;
export const isLibDem = (party: string | null | undefined) => LIB_DEM.test((party ?? "").trim());

const jurisdiction = (code: string | null | undefined) => (code?.startsWith("S") ? "S" : code?.startsWith("N") ? "N" : "EW");

/**
 * The seats each force, NHS area, trust or court in a response serves:
 * - forces and NHS areas: the seats they overlap;
 * - acute trusts: the seats in their catchment (others: the seat their head office is in);
 * - courts: the seats nearer to them than to any other court in the response (as drawn on the map), and the seat
 *   they're in.
 */
export function seatsServed(ref: Reference, g: Geography, inResponse: Set<string>): Map<string, Set<string>> {
  const out = new Map<string, Set<string>>();
  const add = (code: string, seat: string | null | undefined) => {
    if (!seat) return;
    if (!out.has(code)) out.set(code, new Set());
    out.get(code)!.add(seat);
  };
  if (g === "police_force" || g === "health_area") {
    for (const a of (g === "police_force" ? ref.layers.police.areas : ref.layers.health.areas)) for (const [s] of a.seats) add(a.code, s);
  } else if (g === "nhs_trust") {
    for (const t of ref.points.trusts ?? []) {
      if (t.catchment?.length) for (const [s] of t.catchment) add(t.code, s);
      else add(t.code, t.seat);
    }
  } else {
    const courts = (ref.points.courts ?? []).filter((c) => inResponse.has(c.id));
    for (const c of courts) add(c.id, c.seat);
    const K = Math.cos((54 * Math.PI) / 180);
    for (const s of ref.seats) {
      if (s.lon === undefined || s.lat === undefined) continue;
      let best: string | null = null, bestD = Infinity;
      for (const c of courts) {
        if (jurisdiction(c.area) !== jurisdiction(s.code)) continue;
        const dd = ((c.lon - s.lon) * K) ** 2 + (c.lat - s.lat) ** 2;
        if (dd < bestD) { bestD = dd; best = c.id; }
      }
      if (best) add(best, s.code);
    }
  }
  return out;
}

export type LdScope = "held" | "target" | "both";

/** A seat's Lib Dem status: held, or a target (second in 2024). Older reference data: held from the MP's party. */
export function ldOf(s: Reference["seats"][number]): "held" | "target" | undefined {
  return s.ld ?? (isLibDem(s.party) ? "held" : undefined);
}

export function inScope(s: Reference["seats"][number], scope: LdScope): boolean {
  const st = ldOf(s);
  return scope === "both" ? !!st : st === scope;
}

/** Those serving at least one Lib Dem seat in scope (held, target or both), with those seats' names. */
export function libDemServed(ref: Reference, g: Geography, inResponse: Set<string>, scope: LdScope = "held"): Map<string, string[]> {
  const ld = new Map(ref.seats.filter((s) => inScope(s, scope)).map((s) => [s.code, s.name]));
  const out = new Map<string, string[]>();
  for (const [code, seats] of seatsServed(ref, g, inResponse)) {
    const names = [...seats].filter((s) => ld.has(s)).map((s) => ld.get(s)!);
    if (names.length) out.set(code, names.sort());
  }
  return out;
}

/**
 * For each seat, the one force / NHS area / trust / court in a response that mainly serves it: the area covering
 * most of it, the trust whose catchment covers most of it, or the nearest court (as drawn on the map).
 */
export function mainServer(ref: Reference, g: Geography, inResponse: Set<string>): Map<string, { code: string; share?: number }> {
  const out = new Map<string, { code: string; share?: number }>();
  const offer = (seat: string, code: string, share?: number) => {
    const cur = out.get(seat);
    if (!cur || (share ?? 0) > (cur.share ?? 0)) out.set(seat, { code, share });
  };
  if (g === "police_force" || g === "health_area") {
    for (const a of (g === "police_force" ? ref.layers.police.areas : ref.layers.health.areas)) {
      if (inResponse.has(a.code)) for (const [s, share] of a.seats) offer(s, a.code, share);
    }
  } else if (g === "nhs_trust") {
    const trusts = (ref.points.trusts ?? []).filter((t) => inResponse.has(t.code));
    for (const t of trusts) for (const [s, share] of t.catchment ?? []) offer(s, t.code, share);
    for (const t of trusts) if (t.seat && !out.has(t.seat)) out.set(t.seat, { code: t.code });
  } else {
    // Courts: nearest in the response, the same rule as the shaded areas and seatsServed.
    for (const [code, seats] of seatsServed(ref, g, inResponse)) {
      for (const s of seats) if (!out.has(s)) out.set(s, { code });
    }
    const K = Math.cos((54 * Math.PI) / 180);
    const courts = (ref.points.courts ?? []).filter((c) => inResponse.has(c.id));
    for (const s of ref.seats) {
      if (s.lon === undefined || s.lat === undefined) continue;
      let best: string | null = null, bestD = Infinity;
      for (const c of courts) {
        if (jurisdiction(c.area) !== jurisdiction(s.code)) continue;
        const dd = ((c.lon - s.lon) * K) ** 2 + (c.lat - s.lat) ** 2;
        if (dd < bestD) { bestD = dd; best = c.id; }
      }
      if (best) out.set(s.code, { code: best });
    }
  }
  return out;
}

const ORD = (n: number) => `${n}${n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] ?? "th"}`;

/** A sentence a campaign can use, e.g. "In Bath, Avon and Somerset's stop and search rose 12% from 2021/22 to 2024/25: a bigger rise than 30 of 43 police force areas (median +4%)." */
export function campaignLine(o: {
  seat: string; server: string; measure: string; col: Column; value: number | null; suppressed?: string;
  values: number[]; median: number | null; plural: string; perHead?: boolean;
}): string {
  const { seat, server, col, value, values, plural } = o;
  const measure = o.measure.charAt(0).toLowerCase() + o.measure.slice(1);
  const f = (v: number) => fmtValue(v, col, o.perHead);
  if (value === null) return o.suppressed ? `In ${seat}, ${server} withheld its figure for ${measure} (${o.suppressed}).` : `In ${seat}, ${server} gave no figure for ${measure}.`;
  if (col.change) {
    const lower = values.filter((v) => v < value).length, higher = values.filter((v) => v > value).length;
    const moved = value > 0 ? `rose ${f(value).replace(/^\+/, "")}` : value < 0 ? `fell ${f(-value).replace(/^\+/, "")}` : "was unchanged";
    const cmp = value > 0 ? `a bigger rise than ${lower} of ${values.length} ${plural}` : value < 0 ? `a bigger fall than ${higher} of ${values.length} ${plural}` : `while the median moved ${f(o.median ?? 0)}`;
    return `In ${seat}, ${server}'s ${measure} ${moved} from ${col.change.from} to ${col.change.to}: ${cmp}${o.median !== null && value !== 0 ? ` (median ${f(o.median)})` : ""}.`;
  }
  const rank = values.filter((v) => v > value).length + 1;
  const pos = rank <= Math.ceil(values.length / 2) ? `the ${ORD(rank)} highest of ${values.length} ${plural}` : `the ${ORD(values.length - rank + 1)} lowest of ${values.length} ${plural}`;
  const unit = o.perHead ? " per 100,000 residents" : "";
  return `In ${seat}, ${server}'s ${measure} was ${f(value)}${unit}: ${pos}${o.median !== null ? ` (median ${f(o.median)}${unit})` : ""}.`;
}
