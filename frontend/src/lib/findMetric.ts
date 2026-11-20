import type { Metric } from "../types";

/** Everyday words -> words used in metric labels and descriptions. */
const SYNONYMS: Record<string, string[]> = {
  pothole: ["roads needing repair"], potholes: ["roads needing repair"], dentist: ["dental"], dentists: ["dental"],
  doctor: ["gp"], doctors: ["gp"], surgery: ["gp"], chemist: ["pharmac"], unemployment: ["claimant", "unemployed"],
  dole: ["claimant"], benefits: ["claimant"], wages: ["pay", "income"], salary: ["pay", "income"], earnings: ["pay", "income"],
  debt: ["insolvenc", "debt relief"], bankruptcy: ["insolvenc"], truancy: ["absent"], attendance: ["absent"],
  university: ["higher education", "degree"], uni: ["higher education", "degree"], send: ["ehc", "sen support"],
  nursery: ["childcare"], refugees: ["asylum", "ukraine"], migrants: ["asylum", "born outside"], immigration: ["asylum", "born outside"],
  hotels: ["contingency"], sewage: ["sewage", "spills"], rivers: ["sewage"], flooding: ["flood"], pollution: ["air pollution", "sewage"],
  ev: ["ev charger", "plug-in"], electric: ["ev charger", "plug-in", "electricity"], trains: ["rail"], train: ["rail"],
  buses: ["bus"], crash: ["collision"], crashes: ["collision"], accidents: ["collision"], police: ["police", "crime"],
  courts: ["crown court"], rent: ["rent"], renters: ["rented", "rent"], homeless: ["homeless", "temporary accommodation"],
  "second homes": ["second homes"], holiday: ["second homes"], heating: ["heating", "gas grid", "fuel poverty", "heat pump"],
  oil: ["gas grid", "oil"], insulation: ["epc"], poverty: ["poverty", "deprived", "low income"], elderly: ["65", "80+", "pension", "care home"],
  pensioners: ["65", "80+", "pension"], vaccine: ["vaccinat"], mmr: ["vaccinat"], obesity: ["obes"], suicide: ["suicide"],
  drinking: ["alcohol"], smoking: ["smok"], cancer: ["cancer", "screening"], "mental health": ["depression", "mental", "antidepress"],
  parks: ["park", "garden"], solar: ["solar"], tax: ["council tax", "taxpayer"], business: ["business"], shops: ["business"],
};

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9+£% -]/g, " ").replace(/\s+/g, " ").trim();

/** Metrics matching a query, best first: label matches, then description/source, then everyday-word synonyms. */
export function findMetrics(metrics: Metric[], query: string, limit = 12): Metric[] {
  const q = norm(query);
  if (q.length < 2) return [];
  const words = q.split(" ");
  const extra = [...(SYNONYMS[q] ?? []), ...words.flatMap((w) => SYNONYMS[w] ?? [])];
  const scored = metrics.map((m) => {
    const label = norm(m.label), rest = norm(`${m.description} ${m.source} ${m.theme}`);
    let score = 0;
    if (label.startsWith(q)) score = 100;
    else if (label.includes(q)) score = 80;
    else if (words.every((w) => label.includes(w))) score = 70;
    else if (extra.some((e) => label.includes(e))) score = 60;
    else if (words.every((w) => label.includes(w) || rest.includes(w))) score = 40;
    else if (extra.some((e) => rest.includes(e))) score = 20;
    return { m, score };
  });
  return scored.filter((x) => x.score > 0).sort((a, b) => b.score - a.score).slice(0, limit).map((x) => x.m);
}
