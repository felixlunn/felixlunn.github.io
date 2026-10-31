import { useMemo, useState } from "react";
import type { Seat } from "../types";

const POSTCODE = /^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$/i;

function norm(s: string) {
  return s.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/&/g, "and").replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
}

export default function SearchBox({ seats, onPick }: { seats: Seat[]; onPick: (i: number) => void }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const index = useMemo(() => seats.map((s, i) => ({ i, n: norm(s.name), mp: norm(s.mp ?? "") })), [seats]);

  const hits = useMemo(() => {
    const n = norm(q);
    if (n.length < 2) return [];
    return index
      .filter((x) => x.n.includes(n) || x.mp.includes(n))
      .sort((a, b) => Number(!a.n.startsWith(n)) - Number(!b.n.startsWith(n)))
      .slice(0, 8);
  }, [q, index]);

  const pick = (i: number) => {
    onPick(i);
    setQ("");
    setOpen(false);
    setMsg(null);
  };

  const lookupPostcode = async () => {
    setMsg("Looking up postcode…");
    try {
      const r = await fetch(`https://api.postcodes.io/postcodes/${encodeURIComponent(q.trim())}`);
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "Postcode not found");
      const code = j.result?.codes?.parliamentary_constituency_2024 ?? j.result?.codes?.parliamentary_constituency;
      const name = j.result?.parliamentary_constituency_2024 ?? j.result?.parliamentary_constituency;
      const i = seats.findIndex((s) => s.code === code || norm(s.name) === norm(name ?? ""));
      if (i < 0) throw new Error("Constituency not found in dataset");
      pick(i);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Lookup failed");
    }
  };

  const submit = () => {
    if (hits[active]) pick(hits[active].i);
    else if (POSTCODE.test(q.trim())) void lookupPostcode();
  };

  return (
    <div className="search" role="search">
      <input
        type="search"
        placeholder="Constituency, MP or postcode"
        aria-label="Search by constituency, MP or postcode"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
          setActive(0);
          setMsg(null);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === "Enter") submit();
          if (e.key === "ArrowDown") setActive((a) => Math.min(a + 1, hits.length - 1));
          if (e.key === "ArrowUp") setActive((a) => Math.max(a - 1, 0));
          if (e.key === "Escape") setOpen(false);
        }}
      />
      {open && (hits.length > 0 || msg || POSTCODE.test(q.trim())) && (
        <ul className="search-results" role="listbox">
          {hits.map((h, k) => (
            <li key={h.i} role="option" aria-selected={k === active} className={k === active ? "on" : ""} onMouseDown={() => pick(h.i)}>
              <span>{seats[h.i].name}</span>
              <span className="tiny muted">{seats[h.i].mp ?? seats[h.i].country}</span>
            </li>
          ))}
          {!hits.length && POSTCODE.test(q.trim()) && !msg && (
            <li className="on" onMouseDown={() => void lookupPostcode()}>Find constituency for postcode {q.toUpperCase()}</li>
          )}
          {msg && <li className="muted">{msg}</li>}
        </ul>
      )}
    </div>
  );
}
