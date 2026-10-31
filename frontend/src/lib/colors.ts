/**
 * Choropleth ramp: a temperature scale, cool blue (low) through pale yellow to hot red (high)
 * (ColorBrewer RdYlBu, reversed; colour-blind safe). The same in light and dark mode, so "hot = high" always holds.
 */
export const RAMP_LIGHT = ["#4575b4", "#91bfdb", "#e0f3f8", "#ffffbf", "#fee090", "#fc8d59", "#d73027"];
export const RAMP_DARK = RAMP_LIGHT;

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
