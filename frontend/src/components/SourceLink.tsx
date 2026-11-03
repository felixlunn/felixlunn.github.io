import type { Metric } from "../types";

/** A small (i) next to a figure that opens its data source, so offices can check and cite it. */
export default function SourceLink({ metric }: { metric: Pick<Metric, "label" | "source"> & { source_url?: string | null } }) {
  if (!metric.source_url) return null;
  return (
    <a className="src-link no-print" href={metric.source_url} target="_blank" rel="noopener noreferrer"
      title={`Source: ${metric.source} (opens in a new tab)`} aria-label={`Source for ${metric.label}: ${metric.source}`}
      onClick={(e) => e.stopPropagation()}>
      i
    </a>
  );
}
