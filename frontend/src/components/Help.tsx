const FEEDBACK = "https://github.com/felixlunn/felixlunn.github.io/issues/new?title=Dashboard%20feedback";

/** A short "how to use this" guide for MPs' offices, with a feedback link. */
export default function Help({ onClose }: { onClose: () => void }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal help" role="dialog" aria-modal="true" aria-labelledby="help-title" onClick={(e) => e.stopPropagation()}>
        <div className="rank-head">
          <h2 id="help-title">How to use this dashboard</h2>
          <button className="icon" onClick={onClose} aria-label="Close">×</button>
        </div>
        <ol className="small help-steps">
          <li><strong>Choose your MP</strong> in the bar at the top. The dashboard remembers it and opens on your seat.</li>
          <li><strong>Read the seat briefing</strong> (the panel that opens for your seat): where the seat stands out, what has changed against the national trend, and what data is missing.</li>
          <li><strong>Debates</strong> lists upcoming Commons debates and flags those where your seat is in the most extreme tenth on a relevant figure, or your MP is leading.</li>
          <li><strong>Themes</strong> holds every figure. Use <em>Find a figure</em> to search in everyday words (potholes, dentist, rent), then click a figure to map it and see its trend.</li>
          <li><strong>Neighbourhoods</strong> breaks census figures and deprivation down within the seat (Lib Dem seats).</li>
          <li><strong>Twins</strong> finds seats most like yours; <strong>Index</strong> ranks seats on a mix of figures you choose.</li>
        </ol>
        <h3>Quoting a figure</h3>
        <ul className="small">
          <li>The small <span className="src-link" aria-hidden="true">i</span> next to a figure opens its official source. Check the date there before quoting.</li>
          <li>Where a figure has earlier years, the Themes tab gives a ready-made sentence with a Copy button.</li>
          <li><strong>Copy link</strong> (in the briefing and under each figure) copies a link that opens the same seat and figure for a colleague.</li>
          <li>Many figures are published by council, police force or fire authority, so neighbouring seats can share a value. The figure's description says when this applies.</li>
          <li><span className="nodata-flag">No data</span> means the source doesn't cover the seat. It never means zero.</li>
        </ul>
        <p className="small">
          Something wrong or missing? <a href={FEEDBACK} target="_blank" rel="noopener noreferrer">Send feedback</a> (opens GitHub; needs a free account).
        </p>
      </div>
    </div>
  );
}
