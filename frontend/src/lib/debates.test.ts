import { describe, expect, it } from "vitest";
import type { DashboardData, Metric } from "../types";
import { debateMetrics, flagSeats, leadSeat } from "./debates";

const metric = (id: string, polarity: Metric["polarity"]): Metric => ({
  id, label: id, theme: "t", unit: "%", description: "", source: "", polarity, decimals: 1, tags: [], national: null, coverage: 20,
});

function data(): DashboardData {
  const seats = Array.from({ length: 20 }, (_, i) => ({
    code: `S${i}`, name: `Seat ${i}`, country: "England", region: "", mp: `MP ${i}`,
    party: i % 2 ? "Liberal Democrat" : "Labour", party_colour: null,
    first_party_2024: null, second_party_2024: null, result_2024: null, peer_group: null,
  }));
  return {
    version: 1, generated_at: "", demo: true, themes: [], seats, peer_groups: [], sources: [],
    metrics: [metric("crime", "higher_worse"), metric("jobs", "higher_better")],
    values: { crime: seats.map((_, i) => i), jobs: seats.map((_, i) => (i === 3 ? null : i)) },
    debates: [], debate_topics: [{ id: "policing", label: "Policing", metrics: ["crime", "missing", "jobs"] }],
  };
}

describe("debate flags", () => {
  it("resolves topic metrics present in the data", () => {
    const d = data();
    const m = debateMetrics(d, { id: 1, date: "", time: null, venue: "", category: "", title: "", members: [], topics: ["policing"] });
    expect(m.map((x) => x.id)).toEqual(["crime", "jobs"]);
  });

  it("flags only the party's seats in the worst tenth, at the right end", () => {
    const d = data();
    const flags = flagSeats(d, d.metrics, "Lib Dem");
    // crime: top 2 of 20 are seats 19 (LD) and 18 (Lab) -> seat 19. jobs (higher better): bottom 2 of 19 are seats 0, 1 -> seat 1.
    expect(flags.map((f) => [f.seat, f.hits.map((h) => [h.metric.id, h.rank, h.of, h.end])])).toEqual([
      [19, [["crime", 1, 20, "high"]]],
      [1, [["jobs", 2, 19, "low"]]],
    ]);
  });

  it("matches the lead member's constituency to a seat", () => {
    const d = data();
    const debate = { id: 1, date: "", time: null, venue: "", category: "", title: "", topics: [],
      members: [{ name: "X", party: "Liberal Democrat", constituency: "seat 7" }] };
    expect(leadSeat(d, debate)).toBe(7);
  });
});

import { standing, standsOut } from "./debates";

describe("my seat standing", () => {
  it("ranks one seat from the notable end of every metric, most notable first", () => {
    const d = data();
    const s = standing(d, d.metrics, 2);
    // crime (higher worse): seat 2 has value 2, 17 seats higher -> 18th of 20. jobs (higher better): value 2, 2 lower -> 3rd of 19.
    expect(s.map((h) => [h.metric.id, h.rank, h.of])).toEqual([["jobs", 3, 19], ["crime", 18, 20]]);
    expect(standsOut(s[0])).toBe(false); // top 2 of 19 needed
    expect(standsOut({ ...s[0], rank: 2 })).toBe(true);
  });
});
