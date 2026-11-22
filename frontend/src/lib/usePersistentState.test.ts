import { describe, expect, it } from "vitest";
import { migrateStoredSettings } from "./usePersistentState";

function memory(init: Record<string, string>) {
  const m = new Map(Object.entries(init));
  return {
    get length() { return m.size; },
    key: (i: number) => [...m.keys()][i] ?? null,
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
    dump: () => Object.fromEntries(m),
  };
}

describe("settings saved under the old name", () => {
  it("move to the new keys once, without overwriting newer ones", () => {
    const s = memory({ "whips.mySeat": "E14001234", "whips.baseMap": "off", "dash.baseMap": "on", "foi.mode": "orgs" });
    migrateStoredSettings(s);
    expect(s.dump()).toEqual({ "dash.mySeat": "E14001234", "dash.baseMap": "on", "foi.mode": "orgs" });
  });
});
