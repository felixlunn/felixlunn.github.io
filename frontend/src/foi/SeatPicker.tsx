import { useState } from "react";
import { ldOf } from "./analysis";
import { type Reference } from "./types";
/** Choose the office's seat (or any seat): Lib Dem seats first. */

export function SeatPicker({ ref_, seat, setSeat }: { ref_: Reference; seat: string; setSeat: (s: string) => void }) {
  const [q, setQ] = useState("");
  const current = ref_.seats.find((s) => s.code === seat);
  const hits = q.length >= 2 ? ref_.seats.filter((s) => `${s.name} ${s.mp ?? ""}`.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => Number(!ldOf(a)) - Number(!ldOf(b))).slice(0, 8) : [];
  return (
    <div className="foi-seat">
      {current ? (
        <div className="foi-seat-on small">
          <span className="tiny muted">Seat</span> <strong>{current.name}</strong>{current.mp ? ` · ${current.mp}` : ""}
          <button className="link-btn tiny" onClick={() => setSeat("")}>change</button>
        </div>
      ) : (
        <>
          <input type="search" placeholder="Your seat or MP, to see what serves it" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Choose a seat" />
          {hits.length > 0 && (
            <ul className="foi-seat-hits">
              {hits.map((s) => (
                <li key={s.code}><button onClick={() => { setSeat(s.code); setQ(""); }}>
                  {s.name}{ldOf(s) && <span className={`tag ${ldOf(s) === "held" ? "ld" : "tgt"}`}>{ldOf(s) === "held" ? "LD" : "LD target"}</span>}
                  {s.mp ? <span className="tiny muted"> · {s.mp}</span> : null}
                </button></li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
