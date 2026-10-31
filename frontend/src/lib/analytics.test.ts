import { describe, expect, it } from "vitest";
import { compositeIndex, rankOf, similarity, topN } from "./analytics";
import type { DashboardData } from "../types";

// Same fixture as tests/test_engine.py::tiny so the two engines can be compared.
const data = {
  seats: ["A", "B", "C", "D", "E"].map((c, i) => ({ code: c, name: c, country: "England", region: i < 2 ? "North" : "South" })),
  metrics: ["x", "y"].map((id) => ({ id, label: id, unit: "%", tags: ["census"], theme: "people" })),
  values: { x: [10, 11, 30, 31, null], y: [50, 52, 20, 21, 40] },
} as unknown as DashboardData;

describe("analytics", () => {
  it("ranks with missing values", () => {
    expect(rankOf(data.values.x, 3)).toEqual({ value: 31, rank: 1, of: 4, percentile: 100 });
    expect(rankOf(data.values.x, 4).rank).toBeNull();
  });

  it.each(["euclidean", "cosine"] as const)("finds the nearest twin (%s)", (method) => {
    const s = similarity(data, 0, ["x", "y"], method);
    expect(s[4]).toBeNull();
    expect(topN(data, s, 2, { exclude: 0 })[0].code).toBe("B");
    expect(topN(data, s, 5, { exclude: 0, filter: { region: "South" } }).map((r) => r.code).sort()).toEqual(["C", "D"]);
  });

  it("builds a signed composite index", () => {
    expect(topN(data, compositeIndex(data, { x: 1 }), 1)[0].code).toBe("D");
    expect(topN(data, compositeIndex(data, { x: -1 }), 1)[0].code).toBe("A");
  });
});
