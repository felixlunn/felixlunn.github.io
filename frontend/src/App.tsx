import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import type { Choropleth, DashboardData } from "./types";
import { compositeIndex, profileDistance, profileMetrics, similarity, topN, type Scored } from "./lib/analytics";
import { fmt, unitSuffix } from "./lib/format";
import ThemesTab from "./components/ThemesTab";
import TwinsTab, { type TwinSettings } from "./components/TwinsTab";
import IndexTab, { PRESETS } from "./components/IndexTab";
import MatchTab from "./components/MatchTab";
import Dossier from "./components/Dossier";
import SearchBox from "./components/SearchBox";
import Legend from "./components/Legend";
import { PARTY_ID, partyChoropleth } from "./lib/parties";
import DebatesTab from "./components/DebatesTab";
import BattlegroundTab, { battleground } from "./components/BattlegroundTab";
import { debateMetrics, flagSeats, partyOf } from "./lib/debates";

const MapView = lazy(() => import("./components/MapView"));

type Tab = "debates" | "battleground" | "themes" | "twins" | "index" | "match";
const TABS: { id: Tab; label: string }[] = [
  { id: "debates", label: "Debates" },
  { id: "battleground", label: "Battleground" },
  { id: "themes", label: "Themes" },
  { id: "twins", label: "Twins" },
  { id: "index", label: "Index" },
  { id: "match", label: "Match" },
];

function readHash(): Record<string, string> {
  return Object.fromEntries(new URLSearchParams(location.hash.slice(1)));
}

export default function App({ data, geo }: { data: DashboardData; geo: GeoJSON.FeatureCollection }) {
  const initial = useMemo(readHash, []);
  const codeIndex = useMemo(() => new Map(data.seats.map((s, i) => [s.code, i])), [data]);
  const metricIds = useMemo(() => new Set(data.metrics.map((m) => m.id)), [data]);

  const [tab, setTab] = useState<Tab>((TABS.some((t) => t.id === initial.tab) ? initial.tab : "debates") as Tab);
  // The homepage opens on the electoral map (seats in party colours) unless the URL asks for a metric.
  const [metricId, setMetricId] = useState(metricIds.has(initial.metric) ? initial.metric : PARTY_ID);
  const partyMode = metricId === PARTY_ID;
  const metric = data.metrics.find((m) => m.id === metricId) ?? data.metrics.find((m) => m.theme === "politics") ?? data.metrics[0];
  const [theme, setTheme] = useState(partyMode ? "politics" : metric.theme);
  const partyMap = useMemo(() => partyChoropleth(data.seats), [data]);

  // Debates: which debate is open, which of its metrics shades the map, and whose MPs to flag.
  // The party the user works for: flags in Debates, defences and targets in Battleground. Remembered per browser.
  const parties = useMemo(() => {
    const n = new Map<string, number>();
    data.seats.forEach((_, i) => { const p = partyOf(data, i); if (p) n.set(p, (n.get(p) ?? 0) + 1); });
    return [...n.entries()].sort((a, b) => b[1] - a[1]).map(([p]) => p);
  }, [data]);
  const [debateParty, setDebatePartyState] = useState(() => {
    try { return localStorage.getItem("whips.party") || "Lib Dem"; } catch { return "Lib Dem"; }
  });
  const setDebateParty = useCallback((p: string) => {
    setDebatePartyState(p);
    try { localStorage.setItem("whips.party", p); } catch { /* storage unavailable: keep for this visit */ }
  }, []);
  const [debateId, setDebateId] = useState<number | null>(null);
  const [debateMetricId, setDebateMetricId] = useState<string | null>(null);
  const activeDebate = data.debates?.find((d) => d.id === debateId) ?? null;
  const openDebate = useCallback((id: number | null) => {
    setDebateId(id);
    const d = data.debates?.find((x) => x.id === id);
    setDebateMetricId(d ? debateMetrics(data, d)[0]?.id ?? null : null);
  }, [data]);
  const [selected, setSelected] = useState<number | null>(codeIndex.get(initial.seat) ?? null);
  const [focus, setFocus] = useState<{ code: string; n: number } | null>(selected !== null ? { code: data.seats[selected].code, n: 0 } : null);
  const [showSources, setShowSources] = useState(false);
  const [panelOpen, setPanelOpen] = useState(true);

  const [twinSettings, setTwinSettings] = useState<TwinSettings>({ themes: ["people", "housing", "economy", "health", "education", "transport"], method: "euclidean", scope: "uk", n: 20 });
  const [weights, setWeights] = useState<Record<string, number>>(() =>
    Object.fromEntries(Object.entries(PRESETS[0].weights).filter(([k]) => metricIds.has(k))),
  );
  const [targets, setTargets] = useState<Record<string, number>>(() => {
    const t: Record<string, number> = {};
    for (const id of ["age_20_34", "private_rented"]) {
      const m = data.metrics.find((x) => x.id === id);
      if (m?.national != null) t[id] = Math.round(m.national * 1.4 * 10) / 10;
    }
    return t;
  });

  // Keep the URL shareable: #seat=E14001063&metric=private_rented&tab=themes
  useEffect(() => {
    const p = new URLSearchParams();
    if (selected !== null) p.set("seat", data.seats[selected].code);
    p.set("metric", metricId);
    p.set("tab", tab);
    history.replaceState(null, "", `#${p.toString()}`);
  }, [selected, metricId, tab, data]);

  const select = useCallback((i: number | null, fly = true) => {
    setSelected(i);
    if (i !== null && fly) setFocus((f) => ({ code: data.seats[i].code, n: (f?.n ?? 0) + 1 }));
  }, [data]);

  const showMetric = useCallback((id: string) => {
    const m = data.metrics.find((x) => x.id === id);
    if (!m) return;
    setMetricId(id);
    setTheme(m.theme);
    setTab("themes");
  }, [data]);

  // --- analytics for each tool (recomputed instantly; ~650 rows) ---
  const twinIds = useMemo(() => profileMetrics(data.metrics, twinSettings.themes), [data, twinSettings.themes]);
  const twinScores = useMemo(
    () => (tab === "twins" && selected !== null && twinIds.length ? similarity(data, selected, twinIds, twinSettings.method) : null),
    [tab, data, selected, twinIds, twinSettings.method],
  );
  const twinResults: Scored[] = useMemo(() => {
    if (!twinScores || selected === null) return [];
    const s = data.seats[selected];
    const filter = twinSettings.scope === "country" ? { country: s.country } : twinSettings.scope === "region" ? { region: s.region } : {};
    return topN(data, twinScores, twinSettings.n, { exclude: selected, filter });
  }, [twinScores, data, selected, twinSettings]);

  const indexScores = useMemo(() => (tab === "index" ? compositeIndex(data, weights) : null), [tab, data, weights]);
  const indexRanking = useMemo(() => (indexScores ? topN(data, indexScores, data.seats.length) : []), [indexScores, data]);

  const matchDist = useMemo(() => (tab === "match" && Object.keys(targets).length ? profileDistance(data, targets) : null), [tab, data, targets]);
  const matchResults = useMemo(() => (matchDist ? topN(data, matchDist, 50, { ascending: true }) : []), [matchDist, data]);

  const choropleth: Choropleth = useMemo(() => {
    if (tab === "twins" && twinScores && selected !== null) {
      return {
        title: `Similarity to ${data.seats[selected].name}`,
        subtitle: `${twinIds.length} metrics · ${twinSettings.method === "euclidean" ? "closest levels" : "same shape"}`,
        values: twinScores, // the seat itself scores 100%
        format: (v) => `${(v * 100).toFixed(0)}%`,
        highlight: twinResults.slice(0, 10).map((r) => r.code),
      };
    }
    if (tab === "index" && indexScores && indexRanking.length) {
      return {
        title: "Custom index",
        subtitle: Object.keys(weights).map((k) => data.metrics.find((m) => m.id === k)?.label).filter(Boolean).join(", "),
        values: indexScores,
        format: (v) => `${v >= 0 ? "+" : ""}${v.toFixed(2)} SD`,
        highlight: indexRanking.slice(0, 20).map((r) => r.code),
      };
    }
    if (tab === "match" && matchDist) {
      return {
        title: "Distance from target profile",
        subtitle: `${Object.keys(targets).length} criteria`,
        values: matchDist,
        format: (v) => `${v.toFixed(2)} SD`,
        highlight: matchResults.slice(0, 15).map((r) => r.code),
        invert: true,
      };
    }
    if (tab === "battleground" && data.values["majority_pct"]) {
      const { defences, targets } = battleground(data, debateParty);
      const vals: (number | null)[] = data.seats.map(() => null);
      for (const r of [...defences, ...targets]) vals[r.i] = r.majority;
      return {
        title: `${debateParty} defences and targets`,
        subtitle: "Majority at the 2024 general election",
        values: vals,
        format: (v) => `${v.toFixed(1)}%`,
        invert: true,
        invertNote: "Darker = more marginal",
        highlight: targets.map((r) => data.seats[r.i].code),
        highlightLabel: "Targets (outlined)",
        nodataLabel: "Neither",
      };
    }
    if (tab === "debates") {
      const m = activeDebate && debateMetricId ? data.metrics.find((x) => x.id === debateMetricId) : null;
      if (!activeDebate || !m) return partyMap;
      const flagged = flagSeats(data, [m], debateParty).map((f) => data.seats[f.seat].code);
      return {
        title: m.label + unitSuffix(m),
        subtitle: activeDebate.title,
        values: data.values[m.id],
        format: (v) => fmt(m, v),
        highlight: flagged,
      };
    }
    if (partyMode) return partyMap;
    return {
      title: metric.label + unitSuffix(metric),
      subtitle: metric.source,
      values: data.values[metric.id],
      format: (v) => fmt(metric, v),
    };
  }, [tab, twinScores, twinResults, twinIds, twinSettings, selected, indexScores, indexRanking, weights, matchDist, matchResults, targets, metric, data, partyMode, partyMap, activeDebate, debateMetricId, debateParty]);

  const generated = new Date(data.generated_at);
  const failed = data.sources.filter((s) => s.status === "failed");

  return (
    <div className={`app ${selected !== null ? "has-dossier" : ""} ${panelOpen ? "" : "panel-closed"}`}>
      <header className="topbar">
        <div className="brand">
          <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden="true"><rect width="32" height="32" rx="6" fill="var(--accent)" /><path d="M7 22l5-12 4 8 4-6 5 10" stroke="#fff" strokeWidth="3" fill="none" strokeLinejoin="round" /></svg>
          <div>
            <h1>Whips Dashboard</h1>
            <div className="tiny muted">Constituency analytics · {data.seats.length} seats</div>
          </div>
        </div>
        <SearchBox seats={data.seats} onPick={(i) => select(i)} />
        <button className="link small" onClick={() => setShowSources(true)}>
          Data updated {generated.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}
          {failed.length > 0 && <span className="warn-dot" title={`${failed.length} source(s) failed to update`}> ⚠</span>}
        </button>
      </header>

      {data.demo && (
        <div className="demo-banner" role="alert">
          Synthetic demo data: every number and shape on this page is randomly generated for development. Run the data pipeline for real figures.
        </div>
      )}

      <nav className="sidebar" aria-label="Analysis tools">
        <div className="tabs" role="tablist">
          {TABS.map((t) => (
            <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? "on" : ""} onClick={() => { setTab(t.id); setPanelOpen(true); }}>
              {t.label}
            </button>
          ))}
          <button className="icon panel-toggle" aria-label={panelOpen ? "Collapse panel" : "Expand panel"} onClick={() => setPanelOpen((o) => !o)}>{panelOpen ? "‹" : "›"}</button>
        </div>
        {panelOpen && (
          <>
            {tab === "debates" && <DebatesTab data={data} party={debateParty} setParty={setDebateParty} active={debateId} setActive={openDebate}
              mapMetric={debateMetricId} setMapMetric={setDebateMetricId} selected={selected} onSelect={(i) => select(i)} />}
            {tab === "battleground" && <BattlegroundTab data={data} party={debateParty} parties={parties} setParty={setDebateParty}
              selected={selected} onSelect={(i) => select(i)} />}
            {tab === "themes" && <ThemesTab data={data} theme={theme} setTheme={(t) => { setTheme(t); const first = t === "politics" ? PARTY_ID : data.metrics.find((m) => m.theme === t)?.id; if (first) setMetricId(first); }} metric={metric} partyMode={partyMode} parties={partyMap} setMetric={setMetricId} selected={selected} onSelect={(i) => select(i)} />}
            {tab === "twins" && <TwinsTab data={data} selected={selected} settings={twinSettings} setSettings={setTwinSettings} results={twinResults} metricCount={twinIds.length} onSelect={(i) => select(i)} />}
            {tab === "index" && <IndexTab data={data} weights={weights} setWeights={setWeights} ranking={indexRanking} selected={selected} onSelect={(i) => select(i)} />}
            {tab === "match" && <MatchTab data={data} targets={targets} setTargets={setTargets} results={matchResults} selected={selected} onSelect={(i) => select(i)} />}
          </>
        )}
      </nav>

      <main className="main">
        <Suspense fallback={<div className="map-loading">Loading map…</div>}>
          <MapView geo={geo} seats={data.seats} choropleth={choropleth} selected={selected !== null ? data.seats[selected].code : null}
            focus={focus} onSelect={(code) => { const i = codeIndex.get(code); if (i !== undefined) select(i, false); }} />
        </Suspense>
        <Legend ch={choropleth} />
      </main>

      {selected !== null && (
        <Dossier data={data} index={selected} onClose={() => setSelected(null)} onSelect={(i) => select(i)} onShowMetric={showMetric} />
      )}

      {showSources && (
        <div className="modal-backdrop" onClick={() => setShowSources(false)}>
          <div className="modal" role="dialog" aria-modal="true" aria-labelledby="src-title" onClick={(e) => e.stopPropagation()}>
            <div className="rank-head">
              <h2 id="src-title">Data sources</h2>
              <button className="icon" onClick={() => setShowSources(false)} aria-label="Close">×</button>
            </div>
            <p className="small">Built {generated.toLocaleString("en-GB")}. The pipeline re-runs automatically every two days.</p>
            <table className="metric-table">
              <thead><tr><th scope="col">Source</th><th scope="col">Period</th><th scope="col">Status</th></tr></thead>
              <tbody>
                {data.sources.map((s) => (
                  <tr key={s.id}>
                    <td>{s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.name}</a> : s.name}<div className="tiny muted">{s.detail}</div></td>
                    <td className="small">{s.as_of ?? "–"}</td>
                    <td className={`small ${s.status === "ok" ? "ok" : "bad"}`}>{s.status === "ok" ? "✓ Updated" : "✕ Failed"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="tiny muted">
              Contains public sector information licensed under the Open Government Licence v3.0 and Open Parliament Licence.
              Census 2021 covers England and Wales; police.uk covers England, Wales and Northern Ireland.
            </p>
            <p className="small"><a href="./data/constituencies.csv" download>Download every metric for every seat (CSV)</a></p>
          </div>
        </div>
      )}
    </div>
  );
}
