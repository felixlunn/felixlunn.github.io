/** Matching the area or organisation names in an FOI response to known police forces, courts and NHS bodies. */

import type { Geography, Reference, Target } from "./types";

const STOP: Record<Geography, RegExp> = {
  police_force: /\b(the|police|constabulary|service|force|of|area|pfa)\b/g,
  court: /\b(the|hmcts)\b/g,
  nhs_trust: /\b(the|nhs|foundation|trust|ft)\b/g,
  health_area: /\b(the|nhs|integrated care board|icb|university|local health board|health board|lhb|board)\b/g,
};

export function norm(s: string): string {
  return s.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "")
    .replace(/&/g, " and ").replace(/['’`]/g, "").replace(/[^a-z0-9]+/g, " ").trim().replace(/\s+/g, " ");
}

export function core(s: string, g: Geography): string {
  return norm(s).replace(STOP[g], " ").replace(/\band\b/g, " ").replace(/\s+/g, " ").trim();
}

/** Rows that are totals, not an area: skipped rather than reported as unmatched. */
export function isTotal(name: string): boolean {
  return /^(grand )?total|^all (forces|areas|trusts|courts)|^england( and wales)?$|^wales$|^united kingdom$|^uk$|^national$/.test(norm(name));
}

export function targets(ref: Reference, g: Geography): Target[] {
  if (g === "police_force") return ref.layers.police.areas.map((a) => ({ code: a.code, name: a.name, keys: [a.code, ...a.aliases], population: a.population }));
  if (g === "health_area") return ref.layers.health.areas.map((a) => ({ code: a.code, name: a.name, keys: [a.code, ...a.aliases], population: a.population }));
  if (g === "court") return (ref.points.courts ?? []).map((c) => ({ code: c.id, name: c.name, keys: [c.id, c.name, ...c.codes], sub: c.types.join(", ") }));
  return (ref.points.trusts ?? []).map((t) => ({ code: t.code, name: t.name, keys: [t.code, t.name, ...(t.aliases ?? [])], sub: t.kind }));
}

export interface Match { code: string | null; how: "exact" | "close" | "none" | "total" }

export class Matcher {
  private exact = new Map<string, string | null>();
  private cores = new Map<string, string | null>();
  constructor(private ts: Target[], private g: Geography) {
    const put = (m: Map<string, string | null>, k: string, code: string) => {
      if (!k) return;
      m.set(k, m.has(k) && m.get(k) !== code ? null : code); // null: ambiguous
    };
    for (const t of ts) for (const k of t.keys) { put(this.exact, norm(k), t.code); put(this.cores, core(k, g), t.code); }
  }

  match(name: string): Match {
    if (!name.trim()) return { code: null, how: "none" };
    if (isTotal(name)) return { code: null, how: "total" };
    const e = this.exact.get(norm(name));
    if (e) return { code: e, how: "exact" };
    const c = this.cores.get(core(name, this.g));
    if (c) return { code: c, how: "exact" };
    // Close: the best word overlap, if clearly ahead of the runner-up.
    const words = new Set(core(name, this.g).split(" ").filter(Boolean));
    if (!words.size) return { code: null, how: "none" };
    let best: [number, string | null] = [0, null], second = 0;
    for (const t of this.ts) {
      const tw = new Set(core(t.name, this.g).split(" ").filter(Boolean));
      const inter = [...words].filter((w) => tw.has(w)).length;
      const score = inter / (words.size + tw.size - inter || 1);
      if (score > best[0]) { second = best[0]; best = [score, t.code]; } else if (score > second) second = score;
    }
    return best[0] >= 0.5 && best[0] - second >= 0.15 ? { code: best[1], how: "close" } : { code: null, how: "none" };
  }
}
