import { useMemo } from "react";
import type { Choropleth } from "../types";
import { quantileBreaks, ramp } from "./colors";

/** The colour classes for a choropleth: shared by the map and its key (kept out of MapView so the map loads lazily). */
export function useColours(ch: Choropleth) {
  return useMemo(() => {
    const colours = ramp();
    const breaks = quantileBreaks(ch.values, colours.length);
    const palette = colours;
    // With fewer distinct breaks than classes, use the darker end of the ramp evenly.
    const used = palette.slice(0, breaks.length + 1);
    const step = (palette.length - 1) / Math.max(used.length - 1, 1);
    const pick = (k: number) => palette[Math.round(k * step)];
    return { breaks, pick, classes: breaks.length + 1 };
  }, [ch]);
}
