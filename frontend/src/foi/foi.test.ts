import { describe, expect, it } from "vitest";
import { Matcher, core, isTotal } from "./match";
import { numericShare, parseCsv, parseValue, toTable } from "./parse";
import type { Target } from "./types";

describe("parseCsv / toTable", () => {
  it("handles quotes, CRLF, BOM and a title block above the header", () => {
    const text = "﻿FOI 2026/123 response\r\n\r\nForce,\"Officers, FTE\",Note\r\n\"Avon & Somerset\",\"2,950\",\"said \"\"ok\"\"\"\r\nKent,3,\r\n";
    const t = toTable(parseCsv(text));
    expect(t.headers).toEqual(["Force", "Officers, FTE", "Note"]);
    expect(t.rows).toEqual([["Avon & Somerset", "2,950", 'said "ok"'], ["Kent", "3", ""]]);
  });
  it("detects semicolon separators", () => {
    expect(parseCsv("a;b\n1;2")).toEqual([["a", "b"], ["1", "2"]]);
  });
});

describe("parseValue", () => {
  it.each([
    ["1,234", 1234], ["£5.2m", 5_200_000], ["12%", 12], ["(3)", -3], ["0.5", 0.5], ["nil", 0], ["2k", 2000],
  ])("%s -> %s", (raw, v) => expect(parseValue(raw).value).toBe(v));
  it("keeps withheld values as withheld and blanks as blank", () => {
    expect(parseValue("<5")).toEqual({ value: null, suppressed: "<5" });
    expect(parseValue("*")).toEqual({ value: null, suppressed: "*" });
    expect(parseValue("n/a")).toEqual({ value: null });
    expect(parseValue("Not held")).toEqual({ value: null });
    expect(parseValue("see note")).toEqual({ value: null });
  });
  it("scores numeric columns", () => {
    expect(numericShare([["a", "1"], ["b", "<5"], ["c", ""]], 1)).toBe(1);
    expect(numericShare([["a", "1"], ["b", "x y"]], 0)).toBe(0);
  });
});

const forces: Target[] = [
  { code: "E23000036", name: "Avon and Somerset", keys: ["E23000036", "Avon and Somerset", "Avon and Somerset Constabulary"] },
  { code: "E23000001", name: "Metropolitan Police", keys: ["E23000001", "Metropolitan Police", "Metropolitan Police Service", "Met Police", "MPS"] },
  { code: "E23000034", name: "City of London", keys: ["E23000034", "City of London", "City of London Police"] },
  { code: "W15000002", name: "South Wales", keys: ["W15000002", "South Wales"] },
  { code: "W15000001", name: "North Wales", keys: ["W15000001", "North Wales"] },
];

describe("Matcher", () => {
  const m = new Matcher(forces, "police_force");
  it("matches codes, names and common variants", () => {
    expect(m.match("E23000036").code).toBe("E23000036");
    expect(m.match("Avon & Somerset Constabulary").code).toBe("E23000036");
    expect(m.match("avon and somerset police").code).toBe("E23000036");
    expect(m.match("Met Police").code).toBe("E23000001");
    expect(m.match("The Metropolitan Police Service").code).toBe("E23000001");
    expect(m.match("South Wales Police").code).toBe("W15000002");
  });
  it("never guesses between similar names", () => {
    expect(m.match("Wales").how).toBe("total");
    expect(m.match("Gwent").code).toBeNull();
  });
  it("skips total rows", () => {
    expect(isTotal("Grand Total")).toBe(true);
    expect(isTotal("England and Wales")).toBe(true);
    expect(m.match("Total").how).toBe("total");
  });
  it("strips NHS trust boilerplate", () => {
    expect(core("The Newcastle upon Tyne Hospitals NHS Foundation Trust", "nhs_trust")).toBe("newcastle upon tyne hospitals");
    const t = new Matcher([{ code: "RTD", name: "The Newcastle upon Tyne Hospitals NHS Foundation Trust", keys: ["RTD", "The Newcastle upon Tyne Hospitals NHS Foundation Trust"] },
      { code: "RX1", name: "Nottingham University Hospitals NHS Trust", keys: ["RX1", "Nottingham University Hospitals NHS Trust"] }], "nhs_trust");
    expect(t.match("Newcastle upon Tyne Hospitals NHS FT").code).toBe("RTD");
    expect(t.match("rx1").code).toBe("RX1");
    expect(t.match("Nottingham University Hospitals").code).toBe("RX1");
  });
});
