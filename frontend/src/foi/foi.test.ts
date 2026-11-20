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

describe("projectUrl", () => {
  it("keeps only the project address", async () => {
    const { projectUrl } = await import("./backend");
    expect(projectUrl("https://abc.supabase.co/rest/v1/")).toBe("https://abc.supabase.co");
    expect(projectUrl(" https://abc.supabase.co ")).toBe("https://abc.supabase.co");
    expect(projectUrl("")).toBeUndefined();
  });
});

describe("stats", () => {
  it("describes a column and finds outliers", async () => {
    const { describe: d, outlier, vsMedian, quantile } = await import("./stats");
    expect(quantile([1, 2, 3, 4], 0.25)).toBe(1.75);
    const s = d([10, 11, 12, 12, 13, 14, 15, 16, 60, null, 1]);
    expect(s.n).toBe(10);
    expect(s.median).toBe(12.5);
    expect(outlier(60, s)).toBe("high");
    expect(outlier(1, s)).toBe("low");
    expect(outlier(14, s)).toBeNull();
    expect(vsMedian(60, s.median)).toBe("4.8× the median");
    expect(vsMedian(10, 12.5)).toBe("20% below the median");
  });
  it("doesn't flag outliers in very small sets", async () => {
    const { describe: d } = await import("./stats");
    expect(d([1, 2, 100]).high).toBeNull();
  });
});

describe("periods", () => {
  it("recognises years and periods, not ordinary numbers", async () => {
    const { parsePeriod: p, seriesName } = await import("./periods");
    expect(p("2023")?.label).toBe("2023");
    expect(p("2023/24")?.label).toBe("2023/24");
    expect(p("FY 2023-2024")?.label).toBe("2023/24");
    expect(p("Officers 2022/23")?.label).toBe("2022/23");
    expect(p("Q2 2024")?.label).toBe("2024 Q2");
    expect(p("March 2024")?.label).toBe("Mar 2024");
    expect(p("1,234")).toBeNull();
    expect(p("3000")).toBeNull();
    expect(p("2023/25")).toBeNull();
    expect(p("2023/24")!.key).toBeGreaterThan(p("2023")!.key);
    expect(seriesName("Officers (2022/23)")).toBe("Officers");
    expect(seriesName("2024")).toBe("");
  });
  it("groups year columns and calculates change, within and across datasets", async () => {
    const { timeSeries, autoChanges, addChange, changeValue } = await import("./periods");
    expect(changeValue(100, 125, "percent")).toBe(25);
    expect(changeValue(0, 5, "percent")).toBeNull();
    expect(changeValue(80, 60, "absolute")).toBe(-20);
    const base = { id: "a", department: "policing", geography: "police_force", title: "t", foi_reference: null, authority: null, period: null,
      requested_on: null, received_on: null, notes: null, unmatched: [], file_path: null, created_by: null, created_by_email: "", created_at: "", updated_at: "" } as const;
    const d = { ...base, columns: [
      { key: "a", label: "2024", unit: "count", direction: "higher_worse", period: "2024", series: "" },
      { key: "b", label: "2022", unit: "count", direction: "higher_worse", period: "2022", series: "" },
    ], rows: [{ code: "X", source_name: "X", values: { a: 150, b: 100 } }, { code: "Y", source_name: "Y", values: { a: null, b: 10 } }] } as never;
    expect(timeSeries((d as { columns: never[] }).columns)[0].cols.map((c) => c.period)).toEqual(["2022", "2024"]);
    const out = autoChanges(d) as { columns: { label: string; key: string }[]; rows: { code: string; values: Record<string, number | null> }[] };
    const chg = out.columns[2];
    expect(chg.label).toBe("% change 2022 to 2024");
    expect(out.rows.find((r) => r.code === "X")!.values[chg.key]).toBe(50);
    expect(out.rows.find((r) => r.code === "Y")!.values[chg.key]).toBeNull();
    const later = { ...base, id: "b", period: "2025", columns: [{ key: "z", label: "Count", unit: "count", direction: "higher_worse" }],
      rows: [{ code: "X", source_name: "X", values: { z: 300 } }, { code: "Z", source_name: "Z", values: { z: 5 } }] } as never;
    const cross = addChange(d, { d, col: (d as { columns: never[] }).columns[0] }, { d: later, col: (later as { columns: never[] }).columns[0] }, "percent") as typeof out;
    const k = cross.columns[cross.columns.length - 1].key;
    expect(cross.rows.find((r) => r.code === "X")!.values[k]).toBe(100);
    expect(cross.rows.some((r) => r.code === "Z")).toBe(true);
  });
});
