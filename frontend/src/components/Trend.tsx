import { useState } from "react";
import type { Metric } from "../types";
import { changes, quote, type Change, type Series } from "../lib/history";
import { fmt } from "../lib/format";

const arrow = (c: Change) => (c.dir === "up" ? "▲" : c.dir === "down" ? "▼" : "■");

/** "▲ 1.2 pts since 2024", coloured by whether the move is good or bad for the figure. */
export function ChangeBadge({ metric, series, since = "last" }: { metric: Metric; series: Series; since?: "last" | "first" }) {
  const c = changes(metric, series)[since === "first" ? "since" : "last"];
  const word = c.dir === "up" ? "up" : c.dir === "down" ? "down" : "no change";
  return (
    <span className={`chg ${c.tone}`} title={`${fmt(metric, c.from.value)} in ${c.from.period} → ${fmt(metric, c.to.value)} in ${c.to.period}`}>
      <span aria-hidden="true">{arrow(c)}</span> {c.dir === "flat" ? word : `${c.text}`} <span className="muted">since {c.from.period}</span>
      <span className="sr-only">{` (${word})`}</span>
    </span>
  );
}

function path(points: { x: number; y: number }[]): string {
  return points.map((p, k) => `${k ? "L" : "M"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
}

function scale(series: Series, w: number, h: number, pad: number) {
  // Periods in time order: national has every period; add any seat-only ones in their own order.
  const periods = series.national.map((p) => p.period);
  for (const p of series.seat) if (!periods.includes(p.period)) periods.push(p.period);
  const shown = series.seat.concat(series.national.filter((p) => series.seat.some((q) => q.period === p.period)));
  const vals = shown.map((p) => p.value);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const span = hi - lo || Math.abs(hi) || 1;
  const first = periods.indexOf(series.seat[0].period), last = periods.indexOf(series.seat[series.seat.length - 1].period);
  const n = Math.max(last - first, 1);
  return {
    x: (p: string) => pad + ((periods.indexOf(p) - first) / n) * (w - 2 * pad),
    y: (v: number) => h - pad - ((v - lo) / span) * (h - 2 * pad),
  };
}

/** A tiny seat line (with the national line faint behind it). */
export function Sparkline({ series, width = 64, height = 18 }: { series: Series; width?: number; height?: number }) {
  const s = scale(series, width, height, 2);
  const seat = series.seat.map((p) => ({ x: s.x(p.period), y: s.y(p.value) }));
  const nat = series.national.filter((p) => series.seat.some((q) => q.period === p.period)).map((p) => ({ x: s.x(p.period), y: s.y(p.value) }));
  return (
    <svg className="spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      {nat.length > 1 && <path d={path(nat)} className="spark-nat" />}
      <path d={path(seat)} className="spark-seat" />
      <circle cx={seat[seat.length - 1].x} cy={seat[seat.length - 1].y} r={1.8} className="spark-dot" />
    </svg>
  );
}

/** Seat against the national figure over time, with the change written out and a quotable sentence. */
export function TrendChart({ metric, series, seatName }: { metric: Metric; series: Series; seatName: string }) {
  const [copied, setCopied] = useState(false);
  const w = 300, h = 110, pad = 14;
  const s = scale(series, w, h, pad);
  const seat = series.seat.map((p) => ({ ...p, x: s.x(p.period), y: s.y(p.value) }));
  const nat = series.national.filter((p) => series.seat.some((q) => q.period === p.period)).map((p) => ({ ...p, x: s.x(p.period), y: s.y(p.value) }));
  const { last, since } = changes(metric, series);
  const text = quote(metric, seatName, series);
  const copy = () => {
    navigator.clipboard?.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }).catch(() => {});
  };
  return (
    <figure className="trend">
      <figcaption className="small">
        <strong>Change over time</strong>{" "}
        <ChangeBadge metric={metric} series={series} since="first" /> · <ChangeBadge metric={metric} series={series} />
      </figcaption>
      <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`${metric.label} in ${seatName}: ${fmt(metric, since.from.value)} in ${since.from.period}, ${fmt(metric, last.to.value)} in ${last.to.period}`}>
        {nat.length > 1 && <path d={path(nat)} className="trend-nat" />}
        <path d={path(seat)} className="trend-seat" />
        {seat.map((p) => (
          <circle key={p.period} cx={p.x} cy={p.y} r={2.6} className="trend-dot"><title>{`${p.period}: ${fmt(metric, p.value)}`}</title></circle>
        ))}
        <text x={seat[0].x} y={h - 1} className="trend-axis" textAnchor="start">{seat[0].period}</text>
        <text x={seat[seat.length - 1].x} y={h - 1} className="trend-axis" textAnchor="end">{seat[seat.length - 1].period}</text>
      </svg>
      <div className="trend-key tiny muted"><span className="key-seat" /> {seatName} <span className="key-nat" /> National figure</div>
      <p className="small quote">{text} <button className="link small" onClick={copy}>{copied ? "Copied" : "Copy"}</button></p>
    </figure>
  );
}
