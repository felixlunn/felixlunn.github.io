export interface Theme {
  id: string;
  label: string;
  description: string;
}

export interface Metric {
  id: string;
  label: string;
  theme: string;
  unit: string;
  description: string;
  source: string;
  polarity: "higher_worse" | "higher_better" | "neutral";
  decimals: number;
  tags: string[];
  national: number | null;
  coverage: number;
}

export interface Seat {
  code: string;
  name: string;
  country: string;
  region: string;
  mp: string | null;
  party: string | null;
  party_colour: string | null;
  first_party_2024: string | null;
  second_party_2024: string | null;
  result_2024: string | null;
  peer_group: number | null;
}

export interface PeerGroup {
  id: number;
  label: string;
  description: string;
  size: number;
  high: string[];
  low: string[];
}

export interface Source {
  id: string;
  name: string;
  url: string;
  status: "ok" | "failed";
  detail: string;
  as_of: string | null;
}

export interface DashboardData {
  version: number;
  generated_at: string;
  demo: boolean;
  themes: Theme[];
  metrics: Metric[];
  seats: Seat[];
  values: Record<string, (number | null)[]>;
  peer_groups: PeerGroup[];
  sources: Source[];
  debates?: Debate[];
  /** Seats with neighbourhood (LSOA) files in data/lsoa/<code>.json. */
  neighbourhoods?: { seats: string[]; lsoas: number; metrics: number } | null;
  debate_topics?: DebateTopic[];
}

export interface Debate {
  id: number;
  date: string;
  time: string | null;
  venue: string;
  category: string;
  title: string;
  members: { name: string; party: string | null; constituency: string | null }[];
  topics: string[];
}

export interface DebateTopic {
  id: string;
  label: string;
  metrics: string[];
}

/** What the map is currently shading. Values are aligned with `data.seats`. */
export interface Choropleth {
  title: string;
  subtitle?: string;
  values: (number | null)[];
  format: (v: number) => string;
  /** Seats to outline (e.g. twin seats or top-ranked). */
  highlight?: string[];
  /** Reverse the ramp so that low values are dark (e.g. distances). */
  invert?: boolean;
  /** Categorical map: each value is an index into this list, coloured as given (e.g. parties). */
  categories?: { label: string; colour: string; count: number }[];
}

/** One seat's neighbourhood (LSOA) census profile. Arrays align with `lsoas`. */
export interface NeighbourhoodFile {
  seat: string;
  name: string;
  lsoas: { code: string; name: string; ward: string | null; council: string | null }[];
  metrics: string[];
  values: Record<string, (number | null)[]>;
  /** Percentile (0-100) among all LSOAs in England & Wales. */
  pct: Record<string, (number | null)[]>;
  /** IMD 2025 decile, 1 = most deprived 10% of neighbourhoods in England; null in Wales. */
  imd_decile?: (number | null)[];
  geo: GeoJSON.FeatureCollection;
}
