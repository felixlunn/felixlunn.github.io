import { useEffect, useRef, useState } from "react";
import type { Seat } from "../types";
import SearchBox from "./SearchBox";
import { partyStyle } from "../lib/parties";

interface Props {
  seats: Seat[];
  office: number | null;
  setOffice: (i: number | null) => void;
  onOpen: (i: number) => void;
}

/** Link that opens the dashboard set up for one MP's office. */
export function officeLink(seat: Seat): string {
  return `${location.origin}${location.pathname}#office=${encodeURIComponent(seat.code)}`;
}

/** Header control: which MP's office is using the dashboard. Used across every tool. */
export default function OfficePicker({ seats, office, setOffice, onOpen }: Props) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);

  const seat = office !== null ? seats[office] : null;
  const colour = seat?.party ? partyStyle(seat.party, seat.party_colour).colour : "var(--accent)";

  const copy = async () => {
    if (!seat) return;
    try {
      await navigator.clipboard.writeText(officeLink(seat));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      window.prompt("Copy this link", officeLink(seat));
    }
  };

  // Not chosen yet: the bar itself is the search, front and centre in the header.
  if (!seat) {
    return (
      <div className="office office-bar" ref={ref}>
        <SearchBox seats={seats} onPick={setOffice} placeholder="Which MP's office are you in?"
          className="office-search-bar" />
      </div>
    );
  }

  return (
    <div className="office office-bar" ref={ref}>
      <div className="office-set">
        <button className="office-btn" onClick={() => onOpen(office!)} title="Open your seat's briefing">
          <span className="office-dot" style={{ background: colour }} aria-hidden="true" />
          <span className="office-text">
            <span className="office-name">Office of {seat.mp ?? seat.name}</span>
            <span className="tiny muted office-seat">{seat.name}</span>
          </span>
        </button>
        <button className="icon office-change" aria-label="Change office" aria-expanded={open} onClick={() => setOpen((o) => !o)}>▾</button>
      </div>

      {open && (
        <div className="office-pop" role="dialog" aria-label="Change your office">
          <p className="small"><strong>Change office</strong></p>
          <SearchBox seats={seats} onPick={(i) => { setOffice(i); setOpen(false); }} placeholder="MP, constituency or postcode" autoFocus className="office-search" />
          <div className="office-actions">
            <button className="link small" onClick={copy}>{copied ? "Link copied" : "Copy link for this office"}</button>
            <button className="link small" onClick={() => { setOffice(null); setOpen(false); }}>Clear</button>
          </div>
          <p className="tiny muted">Share the link with colleagues: it opens the dashboard set up for {seat.mp ?? seat.name}. Saved in this browser only.</p>
        </div>
      )}
    </div>
  );
}
