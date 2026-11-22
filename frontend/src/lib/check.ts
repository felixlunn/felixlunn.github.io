/**
 * Small structural checks for the JSON files the pipeline writes (data.json, foi/reference.json). The pipeline is
 * Python and the site TypeScript, so nothing else keeps them in step: these checks run in the tests (against the
 * demo build) and when the site loads the files, so a mismatch is caught early and reported clearly.
 */

export type Problems = string[];

const kind = (v: unknown) => (Array.isArray(v) ? "array" : v === null ? "null" : typeof v);

/** Record a problem unless ``obj[key]`` has one of the expected kinds ("string", "number", "array", "object", "null", "boolean"). */
export function field(p: Problems, obj: unknown, key: string, kinds: string[], where: string): void {
  const v = obj && typeof obj === "object" ? (obj as Record<string, unknown>)[key] : undefined;
  if (v === undefined && kinds.includes("undefined")) return;
  if (!kinds.includes(kind(v))) p.push(`${where}.${key}: expected ${kinds.join(" or ")}, got ${kind(v)}`);
}

/** Check every item of an array (only the first few problems are kept). */
export function each(p: Problems, arr: unknown, where: string, check: (item: unknown, at: string) => void): void {
  if (!Array.isArray(arr)) return;
  arr.forEach((item, i) => { if (p.length < 20) check(item, `${where}[${i}]`); });
}
