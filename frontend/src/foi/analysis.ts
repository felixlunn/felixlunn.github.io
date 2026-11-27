/** Turning a matched FOI dataset into map values, rankings and a seat's view. */

import { targets } from "./match";
import { describe } from "./stats";
import { ordinal } from "../lib/format";
import { areasOf, GEO, hospitalTrusts } from "./geographies";
import { nearestCourtBySeat } from "./nearest";
import { type Column, type Dataset, type Geography, type Reference, type Target } from "./types";

export interface Point { code: string; name: string; lat: number; lon: number; area: string | null; seat: string | null; sub: string }

export function points(ref: Reference, g: Geography): Point[] {
  if (g === "court") return (ref.points.courts ?? []).map((c) => ({ code: c.id, name: c.name, lat: c.lat, lon: c.lon, area: c.area, seat: c.seat, sub: c.types.join(", ") }));
  if (g === "nhs_trust") return hospitalTrusts(ref).map((t) => ({ code: t.code, name: t.name, lat: t.lat, lon: t.lon, area: t.area, seat: t.seat, sub: t.kind }));
  return [];
}

export function canPerHead(d: Dataset, col: Column | undefined): boolean {
  return GEO[d.geography].isArea && col?.unit === "count";
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
  if (GEO[g].isArea) {
    return areasOf(ref, g).flatMap((a) => {
      const hit = a.seats.find(([s]) => s === seat);
      return hit ? [{ code: a.code, why: hit[1] >= 0.97 ? "covers the whole seat" : `covers ${Math.round(hit[1] * 100)}% of the seat` }] : [];
    });
  }
  const pts = points(ref, g);
  // Acute trusts: their official catchment says which seats they serve.
  const fromCatchment = g === "nhs_trust" ? hospitalTrusts(ref).flatMap((t) => {
    const hit = t.catchment?.find(([s]) => s === seat);
    return hit ? [{ code: t.code, why: hit[1] >= 0.97 ? "its catchment covers the whole seat" : `its catchment covers ${Math.round(hit[1] * 100)}% of the seat` }] : [];
  }) : [];
  const done = new Set(fromCatchment.map((x) => x.code));
  const areaLayer = areasOf(ref, GEO[g].parent ?? "health_area");
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
  if (GEO[g].isArea) {
    for (const a of areasOf(ref, g)) for (const [s] of a.seats) add(a.code, s);
  } else if (g === "nhs_trust") {
    for (const t of hospitalTrusts(ref)) {
      if (t.catchment?.length) for (const [s] of t.catchment) add(t.code, s);
      else add(t.code, t.seat);
    }
  } else {
    for (const c of ref.points.courts ?? []) if (inResponse.has(c.id)) add(c.id, c.seat);
    for (const [seat, court] of nearestCourtBySeat(ref, inResponse)) add(court, seat);
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
  if (GEO[g].isArea) {
    for (const a of areasOf(ref, g)) {
      if (inResponse.has(a.code)) for (const [s, share] of a.seats) offer(s, a.code, share);
    }
  } else if (g === "nhs_trust") {
    const trusts = hospitalTrusts(ref).filter((t) => inResponse.has(t.code));
    for (const t of trusts) for (const [s, share] of t.catchment ?? []) offer(s, t.code, share);
    for (const t of trusts) if (t.seat && !out.has(t.seat)) out.set(t.seat, { code: t.code });
  } else {
    // Courts: the nearest in the response (the same rule as the shaded areas); seats without a location fall back to
    // the court that sits in them.
    for (const c of ref.points.courts ?? []) if (inResponse.has(c.id) && c.seat && !out.has(c.seat)) out.set(c.seat, { code: c.id });
    for (const [seat, court] of nearestCourtBySeat(ref, inResponse)) out.set(seat, { code: court });
  }
  return out;
}


/** A sentence a campaign can use, e.g. "In Bath, Avon and Somerset's stop and search rose 12% from 2021/22 to 2024/25: a bigger rise than 30 of 43 police force areas (median +4%)." */
export function campaignLine(o: {
  /** Leave out for a line about the organisation itself ("Kent Police's stop and search rose…"). */
  seat?: string; server: string; measure: string; col: Column; value: number | null; suppressed?: string;
  values: number[]; median: number | null; plural: string; perHead?: boolean;
}): string {
  const { seat, server, col, value, values, plural } = o;
  const lead = seat ? `In ${seat}, ${server}` : server;
  const measure = o.measure.charAt(0).toLowerCase() + o.measure.slice(1);
  const f = (v: number) => fmtValue(v, col, o.perHead);
  if (value === null) return o.suppressed ? `${lead} withheld its figure for ${measure} (${o.suppressed}).` : `${lead} gave no figure for ${measure}.`;
  if (col.change) {
    const lower = values.filter((v) => v < value).length, higher = values.filter((v) => v > value).length;
    const moved = value > 0 ? `rose ${f(value).replace(/^\+/, "")}` : value < 0 ? `fell ${f(-value).replace(/^\+/, "")}` : "was unchanged";
    const cmp = value > 0 ? `a bigger rise than ${lower} of ${values.length} ${plural}` : value < 0 ? `a bigger fall than ${higher} of ${values.length} ${plural}` : `while the median moved ${f(o.median ?? 0)}`;
    return `${lead}'s ${measure} ${moved} from ${col.change.from} to ${col.change.to}: ${cmp}${o.median !== null && value !== 0 ? ` (median ${f(o.median)})` : ""}.`;
  }
  const rank = values.filter((v) => v > value).length + 1;
  const pos = rank <= Math.ceil(values.length / 2) ? `the ${ordinal(rank)} highest of ${values.length} ${plural}` : `the ${ordinal(values.length - rank + 1)} lowest of ${values.length} ${plural}`;
  const unit = o.perHead ? " per 100,000 residents" : "";
  return `${lead}'s ${measure} was ${f(value)}${unit}: ${pos}${o.median !== null ? ` (median ${f(o.median)}${unit})` : ""}.`;
}

/** How an organisation reads in a sentence: forces get "Police" ("Kent Police"), others are as named. */
export function displayName(g: Geography, name: string): string {
  return g === "police_force" && !/police/i.test(name) ? `${name} Police` : name;
}
