import { useEffect, useState } from "react";
import { dataUrl } from "./dataUrl";

/** policing.json: each seat's neighbourhood policing teams and their current priorities (police.uk). */
export interface PolicingTeam {
  force: string;
  team: string;
  url?: string;
  priorities: { issue: string; action?: string; date: string }[];
}
export interface PolicingFile { as_of: string; seats: Record<string, PolicingTeam[]> }

let cached: PolicingFile | null | undefined;
let pending: Promise<PolicingFile | null> | null = null;

function load(): Promise<PolicingFile | null> {
  pending ??= fetch(dataUrl("policing.json"))
    .then((r) => (r.ok ? (r.json() as Promise<PolicingFile>) : null))
    .catch(() => null)
    .then((p) => (cached = p && typeof p === "object" && p.seats ? p : null));
  return pending;
}

/** The priorities file, loaded once when a briefing first needs it (null until loaded, or if this deploy has none). */
export function usePolicing(): PolicingFile | null {
  const [p, setP] = useState<PolicingFile | null>(cached ?? null);
  useEffect(() => {
    if (cached !== undefined) { setP(cached); return; }
    let live = true;
    load().then((x) => live && setP(x));
    return () => { live = false; };
  }, []);
  return p;
}
