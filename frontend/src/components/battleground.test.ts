import { describe, expect, it } from "vitest";
import type { DashboardData } from "../types";
import { battleground } from "./BattlegroundTab";

const seat = (i: number, party: string, first: string, second: string) => ({
  code: `S${i}`, name: `Seat ${i}`, country: "England", region: "", mp: `MP ${i}`, party, party_colour: null,
  first_party_2024: first, second_party_2024: second, result_2024: null, peer_group: null,
});

describe("battleground", () => {
  it("orders defences and targets by majority, using results abbreviations", () => {
    const seats = [
      seat(0, "Liberal Democrat", "LD", "Con", ),
      seat(1, "Liberal Democrat", "LD", "RUK"),
      seat(2, "Conservative", "Con", "LD"),
      seat(3, "Labour", "Lab", "Con"),
      seat(4, "Liberal Democrat", "Con", "LD"), // won at a by-election: the 2024 winner is the challenger
      seat(5, "Labour", "Lab", "LD"),
    ];
    const data = { seats, metrics: [], values: { majority_pct: [12, 3, 5, 1, 8, null] } } as unknown as DashboardData;
    const { defences, targets } = battleground(data, "Lib Dem");
    expect(defences.map((r) => [r.i, r.other])).toEqual([[1, "Reform UK"], [4, "Conservative"], [0, "Conservative"]]);
    expect(targets.map((r) => [r.i, r.other])).toEqual([[2, "Conservative"]]); // seat 5 has no majority figure
  });
});
