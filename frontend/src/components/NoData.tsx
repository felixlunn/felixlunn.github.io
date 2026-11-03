/** A visible "No data" flag, with the reason on hover. */
export default function NoData({ reason }: { reason: string }) {
  return <span className="nodata-flag" title={reason}>No data</span>;
}
