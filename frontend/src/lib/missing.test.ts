import { describe, expect, it } from "vitest";
import type { DashboardData, Metric } from "../types";
import { missingFor, missingReason } from "./missing";

const m = (id: string): Metric => ({ id, label: id, theme: "health", unit: "%", description: "", source: "", polarity: "neutral", decimals: 1, tags: [], national: 1, coverage: 2 }) as Metric;
const data = {
  seats: [{ code: "E14000001" }, { code: "E14000002" }, { code: "S14000001" }],
  metrics: [m("eng"), m("all")],
  values: { eng: [1, null, null], all: [1, 2, 3] },
} as unknown as DashboardData;

describe("missing data", () => {
  it("explains why a value is missing", () => {
    expect(missingReason(data, data.metrics[0], 0)).toBeNull();
    expect(missingReason(data, data.metrics[0], 1)).toBe("No data for this seat");
    expect(missingReason(data, data.metrics[0], 2)).toBe("Not published for Scotland (covers England)");
  });
  it("lists every gap for a seat", () => {
    expect(missingFor(data, 1).map((x) => x.metric.id)).toEqual(["eng"]);
    expect(missingFor(data, 0)).toEqual([]);
  });
});
