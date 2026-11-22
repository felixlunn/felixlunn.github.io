import { describe, expect, it } from "vitest";
import { rankOf } from "./analytics";
import type { DashboardData } from "../types";

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
});
