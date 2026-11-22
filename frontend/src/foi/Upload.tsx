import { useMemo, useState } from "react";
import { Matcher, targets, type Match } from "./match";
import { numericShare, parseCsv, parseValue, readFile, toTable, type Table } from "./parse";
import { parsePeriod, seriesName } from "./periods";
import { DEPARTMENTS, GEO } from "./geographies";
import { summarise } from "./orgs";
import { type Cell, type Column, type DataRow, type Department, type Direction, type Geography, type NewDataset, type Reference } from "./types";

interface Props {
  ref_: Reference;
  department: Department;
  onCancel: () => void;
  onSave: (d: NewDataset, file: File | null) => Promise<void>;
}

type Step = "file" | "columns" | "review";
const UNITS: [Column["unit"], string][] = [["count", "Count (number of…)"], ["rate", "Rate (per 1,000, per 100,000…)"], ["percent", "Percentage"], ["money", "Money (£)"], ["other", "Other"]];
const DIRECTIONS: [Direction, string][] = [["higher_worse", "Higher is worse"], ["higher_better", "Higher is better"], ["neutral", "Neither"]];

/** A value column, with its year or period if the header names one (e.g. "Officers 2023/24"). */
function makeColumn(k: number, header: string, cells: string[]): Column {
  const p = parsePeriod(header);
  return { key: `c${k}`, label: header, unit: guessUnit(header, cells), direction: "higher_worse", ...(p ? { period: p.label, series: seriesName(header) } : {}) };
}

/** A column of years (one row per area per year): mostly periods, several distinct, and areas repeat. */
function findPeriodColumn(t: Table, areaCol: number): number | null {
  const names = t.rows.map((r) => (r[areaCol] ?? "").trim().toLowerCase()).filter(Boolean);
  if (new Set(names).size === names.length) return null;
  for (let k = 0; k < t.headers.length; k++) {
    if (k === areaCol) continue;
    const cells = t.rows.map((r) => (r[k] ?? "").trim()).filter(Boolean);
    const ps = cells.map(parsePeriod);
    const ok = ps.filter(Boolean).length;
    const distinct = new Set(ps.map((p) => p?.label)).size;
    if (cells.length && ok / cells.length >= 0.8 && distinct >= 2 && distinct <= 40) return k;
  }
  return null;
}

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
  const [dragging, setDragging] = useState(false);
  const [geography, setGeography] = useState<Geography>(dept.geographies[0]);
  const [meta, setMeta] = useState({ title: "", authority: "", foi_reference: "", period: "", requested_on: "", received_on: "", notes: "" });
  const [areaCol, setAreaCol] = useState(0);
  const [cols, setCols] = useState<Record<number, Column>>({});
  const [overrides, setOverrides] = useState<Record<number, string>>({}); // row index -> target code, or "" to skip
  const [periodCol, setPeriodCol] = useState<number | null>(null); // one row per area per period: the period column

  const ts = useMemo(() => targets(ref_, geography), [ref_, geography]);
  const matcher = useMemo(() => new Matcher(ts, geography), [ts, geography]);
  const tByCode = useMemo(() => new Map(ts.map((t) => [t.code, t])), [ts]);

  /** How many rows of a table match known names, in its best column, for a geography. */
  function score(t: Table, g: Geography): { best: number; hits: number } {
    const m = new Matcher(targets(ref_, g), g);
    const per = t.headers.map((_, k) => t.rows.filter((r) => { const x = m.match(r[k] ?? ""); return x.how === "exact" || x.how === "close"; }).length);
    const hits = Math.max(0, ...per);
    return { best: per.indexOf(hits), hits };
  }

  function applyTable(t: Table, f: File) {
    if (!t.rows.length) throw new Error("No rows found under the header. Check the file, or pick another sheet.");
    // Which kind of body the rows are (e.g. trusts or NHS areas), judged by which matches more names.
    const scored = dept.geographies.map((g) => ({ g, ...score(t, g) })).sort((x, y) => y.hits - x.hits);
    const g = scored[0].hits > 0 ? scored[0].g : geography;
    const best = scored.find((x) => x.g === g)!.best;
    setGeography(g);
    setFile(f);
    setTable(t);
    setAreaCol(Math.max(best, 0));
    const pcol = findPeriodColumn(t, Math.max(best, 0));
    setPeriodCol(pcol);
    const picked: Record<number, Column> = {};
    t.headers.forEach((h, k) => {
      if (k !== best && k !== pcol && numericShare(t.rows, k) >= 0.6) picked[k] = makeColumn(k, h, t.rows.map((r) => r[k]));
    });
    setCols(picked);
    setOverrides({});
    if (!meta.title) setMeta((m) => ({ ...m, title: f.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ") }));
  }

  async function load(f: File, sheet?: string) {
    setError(null);
    setBusy(true);
    try {
      let t = await readFile(f, sheet);
      // Workbooks: unless a sheet was chosen, use the one whose names match best.
      if (!sheet && t.sheets && t.sheets.length > 1) {
        let top = { t, hits: Math.max(...dept.geographies.map((g) => score(t, g).hits)) };
        for (const name of t.sheets.slice(1, 12)) {
          const other = await readFile(f, name);
          const hits = Math.max(...dept.geographies.map((g) => score(other, g).hits));
          if (hits > top.hits) top = { t: other, hits };
        }
        t = top.t;
      }
      applyTable(t, f);
    } catch (e) {
      setError((e as Error).message);
      setTable(null);
    } finally {
      setBusy(false);
    }
  }

  function loadPasted(text: string) {
    setError(null);
    try {
      if (!text.trim()) return;
      applyTable(toTable(parseCsv(text)), new File([text], "pasted-from-spreadsheet.tsv", { type: "text/tab-separated-values" }));
    } catch (e) {
      setError((e as Error).message);
      setTable(null);
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
      else {
        ok++;
        if (m.how === "close" && !(i in overrides)) close++;
        const k = periodCol !== null ? `${c}|${parsePeriod(table!.rows[i][periodCol] ?? "")?.label ?? ""}` : c;
        seen.set(k, (seen.get(k) ?? 0) + 1);
      }
    });
    return { ok, close, none, total, dupes: [...seen].filter(([, n]) => n > 1).map(([c]) => c.split("|")[0]) };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matches, overrides, periodCol]);

  async function save() {
    if (!table) return;
    const valueCols = Object.entries(cols).map(([k, c]) => [Number(k), c] as const);
    const read = (r: string[]) => {
      const values: Record<string, Cell> = {};
      const suppressed: Record<string, string> = {};
      for (const [k, c] of valueCols) {
        const p = parseValue(r[k] ?? "");
        values[c.key] = p.value;
        if (p.suppressed) suppressed[c.key] = p.suppressed;
      }
      return { values, suppressed };
    };
    let columns: Column[] = valueCols.map(([, c]) => c);
    const byCode = new Map<string, DataRow>();
    const unmatched: NewDataset["unmatched"] = [];
    if (periodCol === null) {
      table.rows.forEach((r, i) => {
        const { values, suppressed } = read(r);
        const code = finalCode(i);
        if (code && !byCode.has(code)) byCode.set(code, { code, source_name: r[areaCol] ?? "", values, ...(Object.keys(suppressed).length ? { suppressed } : {}) });
        else if (matches[i].how !== "total" && (r[areaCol] ?? "").trim()) unmatched.push({ source_name: r[areaCol] ?? "", values });
      });
    } else {
      // One row per area per period: one column per measure and period ("Officers 2023", "Officers 2024", ...).
      const periods = [...new Map(table.rows.map((r) => parsePeriod(r[periodCol] ?? "")).filter((p): p is NonNullable<typeof p> => !!p).map((p) => [p.label, p])).values()]
        .sort((a, b) => a.key - b.key);
      const key = (c: Column, p: string) => `${c.key}_${p.replace(/[^0-9A-Za-z]+/g, "")}`;
      columns = valueCols.flatMap(([, c]) => periods.map((p) => ({ ...c, key: key(c, p.label), label: `${c.label} ${p.label}`, period: p.label, series: c.label })));
      table.rows.forEach((r, i) => {
        const p = parsePeriod(r[periodCol] ?? "");
        const { values, suppressed } = read(r);
        const code = finalCode(i);
        if (!code || !p) {
          if (matches[i].how !== "total" && (r[areaCol] ?? "").trim()) unmatched.push({ source_name: `${r[areaCol] ?? ""} (${r[periodCol] ?? ""})`, values });
          return;
        }
        const row = byCode.get(code) ?? { code, source_name: r[areaCol] ?? "", values: {} };
        for (const [, c] of valueCols) {
          const k = key(c, p.label);
          if (k in row.values) continue; // first row for an area and period wins
          row.values[k] = values[c.key];
          if (suppressed[c.key]) row.suppressed = { ...row.suppressed, [k]: suppressed[c.key] };
        }
        byCode.set(code, row);
      });
    }
    const rows = [...byCode.values()];
    const nul = (s: string) => s.trim() || null;
    setBusy(true);
    setError(null);
    try {
      const draft: NewDataset = {
        department, geography, title: meta.title.trim(), foi_reference: nul(meta.foi_reference), authority: nul(meta.authority),
        period: nul(meta.period), requested_on: nul(meta.requested_on), received_on: nul(meta.received_on), notes: nul(meta.notes),
        columns, rows, unmatched, summary: null, file_path: null,
      };
      // The size and headline figure, saved alongside so the dataset list never has to load the rows.
      await onSave({ ...draft, summary: summarise(ref_, draft) }, file);
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
            <label className={`foi-drop ${dragging ? "over" : ""}`}
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
              onDrop={(e) => { e.preventDefault(); setDragging(false); const f = e.dataTransfer.files?.[0]; if (f) load(f); }}>
              <strong>{file ? `✓ ${file.name}` : "Drop the FOI response here"}</strong>
              <span className="tiny muted">{table ? `${table.rows.length} rows${table.sheet ? ` from sheet “${table.sheet}”` : ""} · ` : ""}CSV or Excel, or choose a file</span>
              <input type="file" accept=".csv,.txt,.tsv,.xlsx,.xlsm,.xls,.ods" onChange={(e) => e.target.files?.[0] && load(e.target.files[0])} />
            </label>
            <details className="foi-paste">
              <summary className="small">…or paste cells copied from Excel or a web page</summary>
              <textarea rows={5} placeholder="Select the table in Excel (including its header row), copy, and paste here" onPaste={(e) => { const t = e.clipboardData.getData("text"); e.preventDefault(); (e.target as HTMLTextAreaElement).value = t; loadPasted(t); }}
                onChange={(e) => loadPasted(e.target.value)} />
            </details>
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
                    <button key={g} className={`chip ${g === geography ? "on" : ""}`} onClick={() => { setGeography(g); setOverrides({}); }}>{GEO[g].label}</button>
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
              One row per {GEO[geography].label.toLowerCase()}, with its name or code in one column and figures in the others. Title rows above
              the header are skipped. Withheld figures (such as "&lt;5" or "*") are kept as withheld, not zero.
            </p>
          </div>
        )}

        {step === "columns" && table && (
          <div className="foi-step">
            <label className="foi-field">
              <span>Which column names the {GEO[geography].label.toLowerCase()}?</span>
              <select value={areaCol} onChange={(e) => { const k = Number(e.target.value); setAreaCol(k); const c = { ...cols }; delete c[k]; setCols(c); setOverrides({}); }}>
                {table.headers.map((h, k) => <option key={k} value={k}>{h} (e.g. {table.rows[0]?.[k] || "blank"})</option>)}
              </select>
            </label>
            <label className="foi-field">
              <span>Does each row cover one year (or period)?</span>
              <select value={periodCol ?? ""} onChange={(e) => { const k = e.target.value === "" ? null : Number(e.target.value); setPeriodCol(k); if (k !== null) { const c = { ...cols }; delete c[k]; setCols(c); } }}>
                <option value="">No: one row per {GEO[geography].label.toLowerCase()}</option>
                {table.headers.map((h, k) => k === areaCol ? null : <option key={k} value={k}>Yes: the year is in “{h}”</option>)}
              </select>
            </label>
            {(() => {
              const years = periodCol !== null ? new Set(table.rows.map((r) => parsePeriod(r[periodCol] ?? "")?.label).filter(Boolean)).size
                : new Set(Object.values(cols).map((c) => c.period).filter(Boolean)).size;
              return years >= 2 ? <p className="tiny ok">{years} years found: maps of the average per year and the % change from the first year to the last will be made automatically.</p> : null;
            })()}
            <div className="foi-field"><span>Figures to keep</span></div>
            <div className="foi-cols">
              {table.headers.map((h, k) => k === areaCol ? null : (
                <div key={k} className={`foi-col ${cols[k] ? "on" : ""}`}>
                  <label className="foi-col-pick">
                    <input type="checkbox" checked={!!cols[k]} onChange={(e) => {
                      const c = { ...cols };
                      if (e.target.checked) c[k] = makeColumn(k, h, table.rows.map((r) => r[k]));
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
