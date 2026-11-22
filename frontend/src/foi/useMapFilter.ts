import { useMemo, useState } from "react";
import type { Ranked } from "./analysis";
import type { Column } from "./types";

export type Direction = "all" | "up" | "down";

/**
 * The map filters in Dataset view, worked out once and used by everything (map, ranking, outliers, counts):
 * up / down (above / below the average, or increase / decrease, on the average and % change maps only) and
 * "serving Lib Dem seats" (any view). ``serving`` is the set of areas serving the Lib Dem seats in scope.
 */
export function useMapFilter(rows: Ranked[], col: Column | undefined, mean: number | null, serving: Map<string, unknown>) {
  const [dir, setDir] = useState<Direction>("all");
  const [ldOnly, setLdOnly] = useState(false);
  const directional = !!col?.derived;
  const isChange = col?.derived === "change";
  const pass = useMemo(() => {
    const mid = isChange ? 0 : mean ?? 0;
    return (r: Ranked) => {
      if (ldOnly && !serving.has(r.target.code)) return false;
      if (!directional || dir === "all") return true;
      if (r.value === null) return false;
      return dir === "up" ? r.value > mid : r.value < mid;
    };
  }, [ldOnly, serving, directional, dir, isChange, mean]);
  const visible = useMemo(() => new Set(rows.filter(pass).map((r) => r.target.code)), [rows, pass]);
  const active = (directional && dir !== "all") || ldOnly;
  const clear = () => { setDir("all"); setLdOnly(false); };
  return { dir, setDir, ldOnly, setLdOnly, directional, isChange, pass, visible, active, clear };
}
