import type { SeatCouncil } from "../types";
import { partyStyle } from "../lib/parties";
import { textOn } from "../lib/colors";

const NOC = "#8a8984";
const when = new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric" });

/** Who runs the councils covering the seat, with seat counts and the next election. */
export default function LocalCouncils({ councils, year }: { councils: SeatCouncil[]; year: number }) {
  return (
    <section>
      <h3>Local councils</h3>
      <ul className="councils">
        {councils.map((c) => {
          const noc = c.control === "No overall control" || c.control === "Independents";
          const st = noc ? { label: c.control, colour: NOC } : partyStyle(c.control);
          const parties = Object.entries(c.parties).map(([p, n]) => `${partyStyle(p).label} ${n}`).join(" · ");
          return (
            <li key={c.code}>
              <div className="council-head">
                <span className="council-name">
                  {c.name}
                  {c.tier === "county" && <span className="tiny muted"> (county council)</span>}
                  {c.share < 0.95 && c.tier !== "county" && <span className="tiny muted"> · {Math.round(c.share * 100)}% of the seat</span>}
                </span>
                <span className="party" style={{ background: st.colour, color: textOn(st.colour) }}>{noc ? c.control : `${st.label} control`}</span>
              </div>
              <div className="tiny muted">
                {parties} (of {c.seats} seats)
                {c.next_election ? ` · Next election ${when.format(new Date(c.next_election))}` : ""}
              </div>
            </li>
          );
        })}
      </ul>
      <p className="tiny muted">Councillors after the May {year} elections, from Open Council Data UK (<a href="https://opencouncildata.co.uk/" target="_blank" rel="noopener noreferrer">source</a>). By-elections and defections since may not be included.</p>
    </section>
  );
}
