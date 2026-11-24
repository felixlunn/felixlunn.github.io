import { describe, expect, it } from "vitest";
import { priorityLines } from "./policing";

describe("policing priorities in a briefing", () => {
  it("shows each priority once, with the teams that set it, most widely set first", () => {
    const team = (name: string, ...issues: [string, string][]) => ({ force: "Hampshire Constabulary", team: name, priorities: issues.map(([issue, date]) => ({ issue, date })) });
    const lines = priorityLines([
      team("Aldershot South", ["Dangerous & antisocial driving", "2026-11-11"], ["Shop theft", "2026-10-01"]),
      team("Aldershot North", ["Dangerous & antisocial driving.", "2026-11-12"]),
      team("Hawley", ["Burglary", "2026-11-20"]),
    ]);
    expect(lines.map((l) => [l.issue, l.teams, l.date])).toEqual([
      ["Dangerous & antisocial driving", ["Aldershot South", "Aldershot North"], "2026-11-12"],
      ["Burglary", ["Hawley"], "2026-11-20"],
      ["Shop theft", ["Aldershot South"], "2026-10-01"],
    ]);
  });
});
