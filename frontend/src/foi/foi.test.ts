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
  it("groups year columns and adds the average per year and % change", async () => {
    const { timeSeries, withYearViews, changeValue } = await import("./periods");
    expect(changeValue(100, 125, "percent")).toBe(25);
    expect(changeValue(0, 5, "percent")).toBeNull();
    expect(changeValue(80, 60, "absolute")).toBe(-20);
    const d = {
      id: "a", department: "policing", geography: "police_force", title: "t", foi_reference: null, authority: null, period: null,
      requested_on: null, received_on: null, notes: null, unmatched: [], file_path: null, created_by: null, created_by_email: "", created_at: "", updated_at: "",
      columns: [
        { key: "a", label: "2024", unit: "count", direction: "higher_worse", period: "2024", series: "" },
        { key: "m", label: "2023", unit: "count", direction: "higher_worse", period: "2023", series: "" },
        { key: "b", label: "2022", unit: "count", direction: "higher_worse", period: "2022", series: "" },
        { key: "n", label: "Notes count", unit: "count", direction: "neutral" },
      ],
      rows: [{ code: "X", source_name: "X", values: { a: 150, m: 110, b: 100, n: 1 } }, { code: "Y", source_name: "Y", values: { a: null, m: 20, b: 10, n: 2 } }],
    } as never;
    expect(timeSeries((d as { columns: never[] }).columns)[0].cols.map((c) => c.period)).toEqual(["2022", "2023", "2024"]);
    const { d: out, views } = withYearViews(d) as unknown as { d: { rows: { code: string; values: Record<string, number | null> }[] }; views: { average: { key: string; label: string }; change: { key: string; label: string } }[] };
    expect(views).toHaveLength(1);
    expect(views[0].change.label).toBe("% change 2022 to 2024");
    expect(views[0].average.label).toBe("average per year");
    const x = out.rows.find((r) => r.code === "X")!.values, y = out.rows.find((r) => r.code === "Y")!.values;
    expect(x[views[0].change.key]).toBe(50);
    expect(x[views[0].average.key]).toBeCloseTo(120);
    expect(y[views[0].change.key]).toBeNull(); // no 2024 figure
    expect(y[views[0].average.key]).toBe(15); // average of the years it has
    expect(withYearViews({ ...(d as object), columns: [(d as { columns: never[] }).columns[3]] } as never).views).toHaveLength(0);
    // Uploaded before years were tagged: recognised from the column names.
    const old = { ...(d as object), columns: (d as { columns: { period?: string; series?: string }[] }).columns.map(({ period: _p, series: _s, ...c }) => c) } as never;
    expect(withYearViews(old).views[0].years.map((y) => y.period)).toEqual(["2022", "2023", "2024"]);
  });
});

describe("Lib Dem seats served", () => {
  it("links forces, trusts and courts to Lib Dem seats", async () => {
    const { libDemServed, isLibDem } = await import("./analysis");
    expect(isLibDem("Liberal Democrat")).toBe(true);
    expect(isLibDem("Labour")).toBe(false);
    const ref = {
      version: 1, as_of: "", seats: [
        { code: "E1", name: "Bath", mp: null, party: "Liberal Democrat", lon: 0, lat: 0 },
        { code: "E2", name: "Leeds", mp: null, party: "Labour", lon: 2, lat: 0 },
        { code: "S1", name: "Fife", mp: null, party: "Liberal Democrat", lon: 2.2, lat: 2 },
      ],
      layers: { police: { label: "", areas: [{ code: "P1", name: "West", aliases: [], population: 1, seats: [["E1", 1]] }, { code: "P2", name: "East", aliases: [], population: 1, seats: [["E2", 1]] }] },
        health: { label: "", areas: [] } },
      points: {
        trusts: [{ code: "T1", name: "T1", kind: "", postcode: "", lat: 0, lon: 2, area: null, seat: "E2", catchment: [["E1", 0.6], ["E2", 1]] }],
        courts: [{ id: "c1", name: "West", types: [], lat: 0, lon: 0.2, codes: [], area: "E23", seat: "E1" },
          { id: "c2", name: "East", types: [], lat: 0, lon: 2, codes: [], area: "E23", seat: "E2" }],
      },
    } as never;
    expect([...libDemServed(ref, "police_force", new Set()).keys()]).toEqual(["P1"]);
    expect(libDemServed(ref, "nhs_trust", new Set()).get("T1")).toEqual(["Bath"]);
    const courts = libDemServed(ref, "court", new Set(["c1", "c2"]));
    expect(courts.get("c1")).toEqual(["Bath"]); // nearest court to Bath
    expect(courts.has("c2")).toBe(false); // Fife is in Scotland: no English court serves it
  });
});

describe("campaign lines and the body serving each seat", () => {
  it("writes level and change lines", async () => {
    const { campaignLine } = await import("./analysis");
    const lvl = campaignLine({ seat: "Bath", server: "Avon and Somerset", measure: "Officers in 2024", col: { key: "a", label: "2024", unit: "count", direction: "higher_better" },
      value: 3000, values: [1000, 2000, 3000, 4000, 5000], median: 3000, plural: "police force areas" });
    expect(lvl).toBe("In Bath, Avon and Somerset's officers in 2024 was 3,000: the 3rd highest of 5 police force areas (median 3,000).");
    const chg = campaignLine({ seat: "Bath", server: "Avon and Somerset", measure: "Stop and search",
      col: { key: "c", label: "", unit: "percent", direction: "higher_worse", change: { from: "2021/22", to: "2024/25", mode: "percent" } },
      value: 12.5, values: [-5, 2, 12.5, 30], median: 7.25, plural: "police force areas" });
    expect(chg).toBe("In Bath, Avon and Somerset's stop and search rose 12.5% from 2021/22 to 2024/25: a bigger rise than 2 of 4 police force areas (median +7.25%).");
    expect(campaignLine({ seat: "Bath", server: "X", measure: "M", col: { key: "a", label: "", unit: "count", direction: "neutral" }, value: null, suppressed: "<5", values: [], median: null, plural: "" }))
      .toBe("In Bath, X withheld its figure for m (<5).");
  });
  it("matches each seat to the area covering most of it", async () => {
    const { mainServer, ldOf } = await import("./analysis");
    const ref = { seats: [{ code: "E1", name: "Bath", mp: null, party: "Labour", ld: "target" }], points: {},
      layers: { police: { label: "", areas: [{ code: "P1", name: "", aliases: [], population: 1, seats: [["E1", 0.3]] }, { code: "P2", name: "", aliases: [], population: 1, seats: [["E1", 0.7]] }] }, health: { label: "", areas: [] } } } as never;
    expect(mainServer(ref, "police_force", new Set(["P1", "P2"])).get("E1")).toEqual({ code: "P2", share: 0.7 });
    expect(mainServer(ref, "police_force", new Set(["P1"])).get("E1")?.code).toBe("P1");
    expect(ldOf({ code: "E1", name: "", mp: null, party: "Liberal Democrat" })).toBe("held");
  });
});

describe("by organisation", () => {
  it("takes each dataset's headline, scores the worse half, and links trusts to their ICB", async () => {
    const { headline, scores, worseHalf, parentOf, orgList } = await import("./orgs");
    const ref = {
      version: 1, as_of: "", seats: [],
      layers: { police: { label: "", areas: [] }, health: { label: "", areas: [{ code: "ICB1", name: "ICB One", aliases: [], population: 1, seats: [] }] } },
      points: { trusts: ["T1", "T2", "T3"].map((c) => ({ code: c, name: c, kind: "", postcode: "", lat: 0, lon: 0, area: "ICB1", seat: null })) },
    } as never;
    const base = { department: "health", geography: "nhs_trust", foi_reference: null, authority: null, period: null, requested_on: null, received_on: null,
      notes: null, unmatched: [], file_path: null, created_by: null, created_by_email: "", created_at: "", updated_at: "" };
    const waits = { ...base, id: "w", title: "Waits", columns: [
      { key: "a", label: "2023", unit: "count", direction: "higher_worse", period: "2023", series: "" },
      { key: "b", label: "2024", unit: "count", direction: "higher_worse", period: "2024", series: "" }],
      rows: [{ code: "T1", source_name: "", values: { a: 100, b: 200 } }, { code: "T2", source_name: "", values: { a: 100, b: 110 } }, { code: "T3", source_name: "", values: { a: 100, b: 90 } }] } as never;
    const staff = { ...base, id: "s", title: "Staff", columns: [{ key: "n", label: "Nurses", unit: "count", direction: "higher_better" }],
      rows: [{ code: "T1", source_name: "", values: { n: 10 } }, { code: "T2", source_name: "", values: { n: 50 } }, { code: "T3", source_name: "", values: { n: 30 } }] } as never;
    const h1 = headline(ref, waits)!, h2 = headline(ref, staff)!;
    expect(h1.col.label).toBe("% change 2023 to 2024"); // multi-year: the change is the headline
    expect(h1.byCode.get("T1")!.value).toBe(100);
    expect(worseHalf(h1, 100)).toBe(true); // rising waits, above the median (+10%)
    expect(worseHalf(h2, 10)).toBe(true); // fewer nurses than the median (30)
    const sc = scores([h1, h2], "nhs_trust");
    expect(sc.get("T1")).toEqual({ worse: 2, of: 2 });
    expect(sc.get("T2")).toEqual({ worse: 0, of: 2 });
    expect(parentOf(ref, "nhs_trust", "T1")).toBe("ICB1");
    expect(orgList(ref, [h1], "nhs_trust").map((t) => t.code)).toEqual(["T1", "T2", "T3"]);

    // Saved at upload: the size and the headline's median, so the list needn't load rows.
    const { summarise, headlineText } = await import("./orgs");
    const s1 = summarise(ref, { ...(waits as object), unmatched: [{ source_name: "X", values: {} }], summary: null } as never);
    expect(s1).toMatchObject({ rows: 3, unmatched: 1, headline: { median: 10, n: 3 } });
    expect(headlineText(s1)).toBe("Median +10% · % change 2023 → 2024");
    expect(headlineText(summarise(ref, { ...(staff as object), summary: null } as never))).toBe("Median 30 · Nurses");
    expect(headlineText({ rows: 3, unmatched: 0, headline: null })).toBeNull();
  });
});

describe("listing datasets without their rows", () => {
  it("drops rows but keeps (or works out) the summary", async () => {
    const { withoutRows } = await import("./backend");
    const d = { id: "a", rows: [{ code: "x", source_name: "", values: {} }], unmatched: [], summary: null } as never;
    expect(withoutRows(d)).toEqual({ id: "a", summary: { rows: 1, unmatched: 0, headline: null } });
    const { noSummaryColumn } = await import("./backend");
    expect(noSummaryColumn({ code: "42703", message: "column foi_datasets.summary does not exist" })).toBe(true);
    expect(noSummaryColumn({ code: "PGRST204", message: "Could not find the 'summary' column of 'foi_datasets' in the schema cache" })).toBe(true);
    expect(noSummaryColumn({ code: "42501", message: "permission denied for table foi_datasets" })).toBe(false);
    expect(noSummaryColumn(null)).toBe(false);
  });
});
