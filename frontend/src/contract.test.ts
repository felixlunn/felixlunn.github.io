/**
 * The pipeline (Python) writes data.json and foi/reference.json; the site (TypeScript) reads them. CI builds the demo
 * data first (python -m whips.build --demo), so these check that the two sides still agree.
 */
import { describe, expect, it } from "vitest";
import { normaliseDataset, checkReference } from "./foi/contract";
import { checkDashboardData, DATA_VERSION } from "./lib/contract";

// Vite loads the files if they've been built (they're not committed); without them the first block is skipped.
const files = import.meta.glob<unknown>(["../public/data/data.json", "../public/data/foi/reference.json"], { eager: true, import: "default" });
const read = (path: string) => files[`../public/data/${path}`];
const built = "../public/data/data.json" in files;

describe.skipIf(!built)("the pipeline's output matches what the site reads", () => {
  it("data.json", () => expect(checkDashboardData(read("data.json"))).toEqual([]));
  it("foi/reference.json", () => expect(checkReference(read("foi/reference.json"))).toEqual([]));
});

describe("the checks catch mismatches", () => {
  it("data.json", () => {
    const p = checkDashboardData({ version: DATA_VERSION + 1, themes: [], metrics: [{ id: "x", label: "X" }], seats: [{ code: "E1" }], values: {}, peer_groups: [], sources: [] });
    expect(p.some((x) => x.startsWith("data.version"))).toBe(true);
    expect(p.some((x) => x.includes("metrics[0].theme"))).toBe(true);
    expect(p.some((x) => x.includes('values["x"]'))).toBe(true);
    expect(p.some((x) => x.includes("seats[0].name"))).toBe(true);
  });
  it("reference.json", () => {
    const p = checkReference({ version: 1, layers: { police: { areas: [{ code: "P1" }] }, health: { areas: [] } }, points: {}, seats: [] });
    expect(p).toEqual(expect.arrayContaining([expect.stringContaining("layers.police.areas[0].name")]));
  });
});

describe("datasets are cleaned up on load", () => {
  it("drops what can't be used and fills defaults", () => {
    const problems: string[] = [];
    const d = normaliseDataset({
      id: "a", title: "T", department: "health", geography: "nhs_trust",
      columns: [{ key: "c", label: "C", unit: "furlongs", direction: "up" }, { label: "no key" }],
      rows: [{ code: "RTD", values: { c: 5, bad: "x", inf: Infinity }, suppressed: { c: "<5", n: 3 } }, { values: { c: 1 } }],
    }, problems)!;
    expect(d.columns).toEqual([{ key: "c", label: "C", unit: "other", direction: "neutral" }]);
    expect(d.rows).toEqual([{ code: "RTD", source_name: "", values: { c: 5, bad: null, inf: null }, suppressed: { c: "<5" } }]);
    expect(d.unmatched).toEqual([]);
    expect(problems).toHaveLength(2);
    expect(normaliseDataset({ id: "b", title: "T", department: "nope", geography: "nhs_trust" })).toBeNull();
    expect(d.summary).toBeNull(); // saved before summaries existed
    const col = { key: "c", label: "C", unit: "count", direction: "neutral" };
    const ok = { rows: 4, unmatched: 0, headline: { col, median: 2, n: 4 } };
    const withSummary = (summary: unknown) => normaliseDataset({ id: "c", title: "T", department: "health", geography: "nhs_trust", summary })!.summary;
    expect(withSummary(ok)).toEqual(ok);
    expect(withSummary({ rows: 4, unmatched: 0, headline: { col: {}, median: 2 } })).toEqual({ rows: 4, unmatched: 0, headline: null });
    expect(withSummary({ rows: "4" })).toBeNull();
  });
});
