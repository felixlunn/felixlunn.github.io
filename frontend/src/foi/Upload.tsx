import { useMemo, useState } from "react";
import { Matcher, targets, type Match } from "./match";
import { numericShare, parseValue, readFile, type Table } from "./parse";
import { DEPARTMENTS, GEOGRAPHY_LABEL, type Cell, type Column, type DataRow, type Department, type Direction, type Geography, type NewDataset, type Reference } from "./types";

interface Props {
  ref_: Reference;
  department: Department;
  onCancel: () => void;
  onSave: (d: NewDataset, file: File | null) => Promise<void>;
}

type Step = "file" | "columns" | "review";
const UNITS: [Column["unit"], string][] = [["count", "Count (number of…)"], ["rate", "Rate (per 1,000, per 100,000…)"], ["percent", "Percentage"], ["money", "Money (£)"], ["other", "Other"]];
const DIRECTIONS: [Direction, string][] = [["higher_worse", "Higher is worse"], ["higher_better", "Higher is better"], ["neutral", "Neither"]];

function guessUnit(header: string, cells: string[]): Column["unit"] {
  const h = header.toLowerCase();
  if (/%|percent|proportion|share/.test(h) || cells.some((c) => /%$/.test(c))) return "percent";
  if (/£|cost|spend|budget|paid|amount|value/.test(h) || cells.some((c) => /^£/.test(c))) return "money";
  if (/rate|per\s*(1,?000|100,?000|head|capita)|average|mean|median|ratio/.test(h)) return "rate";
  return "count";
}

export default function Upload({ ref_, department, onCancel, onSave }: Props) {
  const dept = DEPARTMENTS.find((d) => d.id === department)!;
  const [step, setStep] = useState<Step>("file");
  const [file, setFile] = useState<File | null>(null);
  const [table, setTable] = useState<Table | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [geography, setGeography] = useState<Geography>(dept.geographies[0]);
  const [meta, setMeta] = useState({ title: "", authority: "", foi_reference: "", period: "", requested_on: "", received_on: "", notes: "" });
  const [areaCol, setAreaCol] = useState(0);
  const [cols, setCols] = useState<Record<number, Column>>({});
  const [overrides, setOverrides] = useState<Record<number, string>>({}); // row index -> target code, or "" to skip

  const ts = useMemo(() => targets(ref_, geography), [ref_, geography]);
  const matcher = useMemo(() => new Matcher(ts, geography), [ts, geography]);
  const tByCode = useMemo(() => new Map(ts.map((t) => [t.code, t])), [ts]);

  async function load(f: File, sheet?: string) {
    setError(null);
    setBusy(true);
    try {
      const t = await readFile(f, sheet);
      if (!t.rows.length) throw new Error("No rows found under the header. Check the file, or pick another sheet.");
      setFile(f);
      setTable(t);
      // The area column: the one whose cells match best. Value columns: mostly numeric, other than that one.
      const scores = t.headers.map((_, k) => t.rows.filter((r) => { const m = matcher.match(r[k] ?? ""); return m.how === "exact" || m.how === "close"; }).length);
      const best = scores.indexOf(Math.max(...scores));
      setAreaCol(best);
      const picked: Record<number, Column> = {};
      t.headers.forEach((h, k) => {
        if (k !== best && numericShare(t.rows, k) >= 0.6) {
          picked[k] = { key: `c${k}`, label: h, unit: guessUnit(h, t.rows.map((r) => r[k])), direction: "higher_worse" };
        }
      });
      setCols(picked);
      setOverrides({});
      if (!meta.title) setMeta((m) => ({ ...m, title: f.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ") }));
    } catch (e) {
      setError((e as Error).message);
      setTable(null);
    } finally {
      setBusy(false);
    }
  }

  const matches: (Match & { name: string })[] = useMemo(() => (table ? table.rows.map((r) => ({ name: r[areaCol] ?? "", ...matcher.match(r[areaCol] ?? "") })) : []), [table, areaCol, matcher]);
  const finalCode = (i: number): string | null => (i in overrides ? overrides[i] || null : matches[i]?.code ?? null);
  const counts = useMemo(() => {
    const seen = new Map<string, number>();
    let ok = 0, close = 0, none = 0, total = 0;
    matches.forEach((m, i) => {
      const c = finalCode(i);
      if (m.how === "total" && !(i in overrides)) total++;
      else if (!c) none++;
      else { ok++; if (m.how === "close" && !(i in overrides)) close++; seen.set(c, (seen.get(c) ?? 0) + 1); }
    });
    return { ok, close, none, total, dupes: [...seen].filter(([, n]) => n > 1).map(([c]) => c) };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matches, overrides]);

  async function save() {
    if (!table) return;
    const columns = Object.entries(cols).map(([, c]) => c);
    const rows: DataRow[] = [];
    const unmatched: NewDataset["unmatched"] = [];
    const used = new Set<string>();
    table.rows.forEach((r, i) => {
      const values: Record<string, Cell> = {};
      const suppressed: Record<string, string> = {};
      for (const [k, c] of Object.entries(cols)) {
        const p = parseValue(r[Number(k)] ?? "");
        values[c.key] = p.value;
        if (p.suppressed) suppressed[c.key] = p.suppressed;
      }
      const code = finalCode(i);
      if (code && !used.has(code)) {
        used.add(code);
        rows.push({ code, source_name: r[areaCol] ?? "", values, ...(Object.keys(suppressed).length ? { suppressed } : {}) });
      } else if (matches[i].how !== "total" && (r[areaCol] ?? "").trim()) {
        unmatched.push({ source_name: r[areaCol] ?? "", values });
      }
    });
    const nul = (s: string) => s.trim() || null;
    setBusy(true);
    setError(null);
    try {
      await onSave({
        department, geography, title: meta.title.trim(), foi_reference: nul(meta.foi_reference), authority: nul(meta.authority),
        period: nul(meta.period), requested_on: nul(meta.requested_on), received_on: nul(meta.received_on), notes: nul(meta.notes),
        columns, rows, unmatched, file_path: null,
      }, file);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  const field = (k: keyof typeof meta, label: string, type = "text", placeholder = "") => (
    <label className="foi-field">
      <span>{label}</span>
      <input type={type} value={meta[k]} placeholder={placeholder} onChange={(e) => setMeta({ ...meta, [k]: e.target.value })} />
    </label>
  );

  return (
    <div className="foi-modal" role="dialog" aria-modal="true" aria-label="Upload an FOI response">
      <div className="foi-modal-box">
        <div className="foi-modal-head">
          <h2>Upload an FOI response · {dept.label}</h2>
          <button className="icon-btn" onClick={onCancel} aria-label="Close">✕</button>
        </div>
        <ol className="foi-steps">
          {(["file", "columns", "review"] as Step[]).map((s, i) => (
            <li key={s} className={s === step ? "on" : ""}>{i + 1}. {{ file: "File and details", columns: "Columns", review: "Check matches" }[s]}</li>
          ))}
        </ol>

        {step === "file" && (
          <div className="foi-step">
            <label className="foi-field">
              <span>File (CSV or Excel)</span>
              <input type="file" accept=".csv,.txt,.xlsx,.xlsm,.xls,.ods" onChange={(e) => e.target.files?.[0] && load(e.target.files[0])} />
            </label>
            {table?.sheets && table.sheets.length > 1 && (
              <label className="foi-field">
                <span>Sheet</span>
                <select value={table.sheet} onChange={(e) => file && load(file, e.target.value)}>
                  {table.sheets.map((s) => <option key={s}>{s}</option>)}
                </select>
              </label>
            )}
            {dept.geographies.length > 1 && (
              <fieldset className="foi-field">
                <span>Each row is a…</span>
                <div className="chips">
                  {dept.geographies.map((g) => (
                    <button key={g} className={`chip ${g === geography ? "on" : ""}`} onClick={() => { setGeography(g); setOverrides({}); }}>{GEOGRAPHY_LABEL[g]}</button>
                  ))}
                </div>
              </fieldset>
            )}
            {field("title", "Title", "text", "e.g. Officers on neighbourhood duty, 2025")}
            <div className="foi-grid2">
              {field("authority", "Answered by", "text", "e.g. 43 police forces, HMCTS")}
              {field("foi_reference", "FOI reference(s)")}
              {field("period", "Period covered", "text", "e.g. 2024-25")}
              {field("received_on", "Response received", "date")}
              {field("requested_on", "Request sent", "date")}
            </div>
            <label className="foi-field">
              <span>Notes (the question asked, caveats in the response)</span>
              <textarea rows={3} value={meta.notes} onChange={(e) => setMeta({ ...meta, notes: e.target.value })} />
            </label>
            <p className="tiny muted">
              One row per {GEOGRAPHY_LABEL[geography].toLowerCase()}, with its name or code in one column and figures in the others. Title rows above
              the header are skipped. Withheld figures (such as "&lt;5" or "*") are kept as withheld, not zero.
            </p>
          </div>
        )}

        {step === "columns" && table && (
          <div className="foi-step">
            <label className="foi-field">
              <span>Which column names the {GEOGRAPHY_LABEL[geography].toLowerCase()}?</span>
              <select value={areaCol} onChange={(e) => { const k = Number(e.target.value); setAreaCol(k); const c = { ...cols }; delete c[k]; setCols(c); setOverrides({}); }}>
                {table.headers.map((h, k) => <option key={k} value={k}>{h} (e.g. {table.rows[0]?.[k] || "blank"})</option>)}
              </select>
            </label>
            <div className="foi-field"><span>Figures to keep</span></div>
            <div className="foi-cols">
              {table.headers.map((h, k) => k === areaCol ? null : (
                <div key={k} className={`foi-col ${cols[k] ? "on" : ""}`}>
                  <label className="foi-col-pick">
                    <input type="checkbox" checked={!!cols[k]} onChange={(e) => {
                      const c = { ...cols };
                      if (e.target.checked) c[k] = { key: `c${k}`, label: h, unit: guessUnit(h, table.rows.map((r) => r[k])), direction: "higher_worse" };
                      else delete c[k];
                      setCols(c);
                    }} />
                    <span><strong>{h}</strong> <span className="tiny muted">e.g. {table.rows.slice(0, 3).map((r) => r[k] || "blank").join(", ")}</span></span>
                  </label>
                  {cols[k] && (
                    <div className="foi-col-opts">
                      <input aria-label="Label" value={cols[k].label} onChange={(e) => setCols({ ...cols, [k]: { ...cols[k], label: e.target.value } })} />
                      <select aria-label="Unit" value={cols[k].unit} onChange={(e) => setCols({ ...cols, [k]: { ...cols[k], unit: e.target.value as Column["unit"] } })}>
                        {UNITS.map(([u, l]) => <option key={u} value={u}>{l}</option>)}
                      </select>
                      <select aria-label="Direction" value={cols[k].direction} onChange={(e) => setCols({ ...cols, [k]: { ...cols[k], direction: e.target.value as Direction } })}>
                        {DIRECTIONS.map(([d, l]) => <option key={d} value={d}>{l}</option>)}
                      </select>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {step === "review" && table && (
          <div className="foi-step">
            <p className="small">
              <strong>{counts.ok}</strong> of {table.rows.length - counts.total} rows matched
              {counts.close > 0 && <>, <strong className="warn">{counts.close} by a close name: check them</strong></>}
              {counts.none > 0 && <>, <strong className="bad">{counts.none} not matched</strong> (kept separately, not mapped)</>}
              {counts.total > 0 && <>; {counts.total} total {counts.total === 1 ? "row" : "rows"} skipped</>}.
            </p>
            {counts.dupes.length > 0 && (
              <p className="small bad">Matched more than once: {counts.dupes.map((c) => tByCode.get(c)?.name).join(", ")}. Only the first row is kept; fix the others below.</p>
            )}
            <div className="foi-review">
              <table>
                <thead><tr><th>In the file</th><th>Matched to</th></tr></thead>
                <tbody>
                  {matches.map((m, i) => {
                    const code = finalCode(i);
                    const state = i in overrides ? (code ? "set" : "skip") : m.how;
                    return (
                      <tr key={i} className={`m-${state}`}>
                        <td>{m.name || <span className="muted">(blank)</span>}</td>
                        <td>
                          <select value={code ?? ""} onChange={(e) => setOverrides({ ...overrides, [i]: e.target.value })}>
                            <option value="">{m.how === "total" ? "Total row: skipped" : "Not matched: skip"}</option>
                            {ts.map((t) => <option key={t.code} value={t.code}>{t.name}{t.sub ? ` (${t.sub})` : ""}</option>)}
                          </select>
                          {state === "close" && <span className="tiny warn"> close match</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {error && <p className="small bad" role="alert">{error}</p>}
        <div className="foi-modal-foot">
          <button className="btn" onClick={step === "file" ? onCancel : () => setStep(step === "review" ? "columns" : "file")}>{step === "file" ? "Cancel" : "Back"}</button>
          {step === "file" && <button className="btn primary" disabled={!table || !meta.title.trim() || busy} onClick={() => setStep("columns")}>{busy ? "Reading…" : "Next"}</button>}
          {step === "columns" && <button className="btn primary" disabled={!Object.keys(cols).length} onClick={() => setStep("review")}>Next</button>}
          {step === "review" && <button className="btn primary" disabled={busy || !counts.ok} onClick={save}>{busy ? "Saving…" : `Save ${counts.ok} rows`}</button>}
        </div>
      </div>
    </div>
  );
}
