/**
 * Sequential choropleth ramp: the ONS Census Maps scale, light green (low) to deep indigo (high).
 * Party-neutral, unlike a single blue. Dark mode runs it the other way so high values stay prominent.
 */
export const RAMP_LIGHT = ["#cde594", "#80c6a3", "#1f9eb7", "#186290", "#080c54"];
export const RAMP_DARK = ["#1b2a6b", "#186290", "#1f9eb7", "#80c6a3", "#cde594"];

export function isDark(): boolean {
  const t = document.documentElement.dataset.theme;
  if (t === "dark") return true;
  if (t === "light") return false;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

export function ramp(): string[] {
  return isDark() ? RAMP_DARK : RAMP_LIGHT;
}

/** Quantile class breaks (n-1 thresholds) so each colour holds ~equal numbers of seats. */
export function quantileBreaks(values: (number | null)[], classes: number): number[] {
  const v = values.filter((x): x is number => x !== null).sort((a, b) => a - b);
  if (!v.length) return [];
  const out: number[] = [];
  for (let k = 1; k < classes; k++) {
    const q = v[Math.min(v.length - 1, Math.floor((k / classes) * v.length))];
    if (!out.length || q > out[out.length - 1]) out.push(q);
  }
  return out;
}

export function classify(v: number, breaks: number[]): number {
  let k = 0;
  while (k < breaks.length && v >= breaks[k]) k++;
  return k;
}

/** Readable text colour on a party colour chip. */
export function textOn(hex: string | null | undefined): string {
  if (!hex) return "inherit";
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return lum > 0.6 ? "#111" : "#fff";
}
