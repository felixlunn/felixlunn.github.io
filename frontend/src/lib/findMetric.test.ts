import { describe, expect, it } from "vitest";
import type { Metric } from "../types";
import { findMetrics } from "./findMetric";

const m = (id: string, label: string, description = ""): Metric =>
  ({ id, label, description, theme: "t", unit: "%", source: "s", polarity: "neutral", decimals: 1, tags: [], national: 1, coverage: 1 }) as Metric;
const all = [m("a", "Unclassified roads needing repair"), m("b", "Adults seen by an NHS dentist per 1,000 residents", "dental practices"),
  m("c", "Private rented"), m("d", "Average private rent"), m("e", "Claimant rate", "People claiming unemployment benefits")];

describe("figure search", () => {
  it("matches labels, best first", () => {
    expect(findMetrics(all, "rent").map((x) => x.id)).toEqual(["c", "d"]);
    expect(findMetrics(all, "private rent")[0].id).toBe("c");
  });
  it("understands everyday words", () => {
    expect(findMetrics(all, "potholes").map((x) => x.id)).toEqual(["a"]);
    expect(findMetrics(all, "dentists").map((x) => x.id)).toEqual(["b"]);
    expect(findMetrics(all, "unemployment")[0].id).toBe("e");
  });
  it("needs two characters", () => expect(findMetrics(all, "r")).toEqual([]));
});
