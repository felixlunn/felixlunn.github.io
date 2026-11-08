import { describe, expect, it } from "vitest";
import type { Metric } from "../types";
import { change, changes, quote, seriesFor, type History } from "./history";

const m = (unit: string, polarity: Metric["polarity"]): Metric =>
  ({ id: "x", label: "Bus journeys per person", theme: "transport", unit, description: "", source: "DfT bus statistics",
     polarity, decimals: 0, tags: [], national: 1, coverage: 1 }) as Metric;

const h: History = { metrics: { x: { periods: ["2015", "2020", "2025"], national: [80, 70, 63], values: [[40, null], [35, 1], [30, null]] } } };

describe("change over time", () => {
  it("builds a seat series and skips gaps", () => {
    expect(seriesFor(h, "x", 0)?.seat.map((p) => p.period)).toEqual(["2015", "2020", "2025"]);
    expect(seriesFor(h, "x", 1)).toBeNull(); // one point is not a trend
    expect(seriesFor(h, "missing", 0)).toBeNull();
  });
  it("describes direction, size and whether it's good", () => {
    const s = seriesFor(h, "x", 0)!;
    const { last, since } = changes(m("journeys", "higher_better"), s);
    expect(last).toMatchObject({ dir: "down", tone: "bad", text: "14%" });
    expect(since.text).toBe("25%");
    expect(change(m("%", "higher_worse"), { period: "a", value: 10 }, { period: "b", value: 12.5 })).toMatchObject({ text: "2.5 pts", tone: "bad" });
  });
  it("writes a quotable sentence with the national comparison", () => {
    expect(quote(m("journeys", "higher_better"), "Westmorland", seriesFor(h, "x", 0)!))
      .toBe("Bus journeys per person in Westmorland fell from 40 in 2015 to 30 in 2025; national figure 80 to 63 (DfT bus statistics).");
  });
});
