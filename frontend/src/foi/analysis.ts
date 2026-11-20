/** Turning a matched FOI dataset into map values, rankings and a seat's view. */

import { targets } from "./match";
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
  const v = rows.map((r) => r.value).filter((x): x is number => x !== null).sort((a, b) => a - b);
  const total = v.reduce((a, b) => a + b, 0);
  const median = v.length ? (v.length % 2 ? v[(v.length - 1) / 2] : (v[v.length / 2 - 1] + v[v.length / 2]) / 2) : null;
  return { n: v.length, total, median, min: v[0] ?? null, max: v[v.length - 1] ?? null, withheld: rows.filter((r) => r.suppressed).length };
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
  const areaLayer = g === "court" ? ref.layers.police.areas : ref.layers.health.areas;
  const seatAreas = new Set(areaLayer.filter((a) => a.seats.some(([s]) => s === seat)).map((a) => a.code));
  const areaName = new Map(areaLayer.map((a) => [a.code, a.name]));
  return pts.filter((p) => p.seat === seat || (p.area && seatAreas.has(p.area)))
    .sort((a, b) => Number(b.seat === seat) - Number(a.seat === seat))
    .map((p) => ({ code: p.code, why: p.seat === seat ? "in the seat" : `elsewhere in ${areaName.get(p.area!) ?? "the same area"}` }));
}

export function fmtValue(v: number | null, col: Column | undefined, perHead = false): string {
  if (v === null) return "–";
  const abs = Math.abs(v);
  const dp = perHead ? 1 : abs >= 100 || Number.isInteger(v) ? 0 : abs >= 10 ? 1 : 2;
  const s = v.toLocaleString("en-GB", { maximumFractionDigits: dp, minimumFractionDigits: 0 });
  if (col?.unit === "money") return `£${s}`;
  if (col?.unit === "percent") return `${s}%`;
  return s;
}
