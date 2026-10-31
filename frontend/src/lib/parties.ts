import type { Choropleth, Seat } from "../types";

/** Conventional UK party colours, with the names and abbreviations each party appears under in the data. */
const PARTIES: { label: string; colour: string; aliases: string[] }[] = [
  { label: "Labour", colour: "#E4003B", aliases: ["labour", "lab", "labourcoop", "labourcooperative", "labourandcooperative"] },
  { label: "Conservative", colour: "#0087DC", aliases: ["conservative", "con", "conservativeandunionist", "conservativeandunionistparty"] },
  { label: "Lib Dem", colour: "#FAA61A", aliases: ["liberaldemocrat", "liberaldemocrats", "libdem", "libdems", "ld"] },
  { label: "Reform UK", colour: "#12B6CF", aliases: ["reformuk", "reform", "ruk"] },
  { label: "Green", colour: "#02A95B", aliases: ["green", "greenparty", "grn", "greenpartyofenglandandwales"] },
  { label: "SNP", colour: "#FDF38E", aliases: ["scottishnationalparty", "snp"] },
  { label: "Plaid Cymru", colour: "#005B54", aliases: ["plaidcymru", "pc"] },
  { label: "Sinn Féin", colour: "#326760", aliases: ["sinnfein", "sf"] },
  { label: "DUP", colour: "#D46A4C", aliases: ["democraticunionistparty", "dup"] },
  { label: "Alliance", colour: "#F6CB2F", aliases: ["alliance", "allianceparty", "alliancepartyofnorthernireland", "apni"] },
  { label: "SDLP", colour: "#2AA82C", aliases: ["socialdemocraticandlabourparty", "sdlp"] },
  { label: "UUP", colour: "#48A5EE", aliases: ["ulsterunionistparty", "uup"] },
  { label: "TUV", colour: "#0C3A6A", aliases: ["traditionalunionistvoice", "tuv"] },
  { label: "Independent", colour: "#B4B4B4", aliases: ["independent", "ind"] },
  { label: "Speaker", colour: "#6E6E6E", aliases: ["speaker", "spk"] },
];

const OTHER = "#8C8C8C";

const BY_ALIAS = new Map(PARTIES.flatMap((p) => p.aliases.map((a) => [a, p] as const)));

function key(name: string): string {
  return name.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z]/g, "");
}

/** Canonical label and conventional colour for a party name or abbreviation. */
export function partyStyle(name: string, fallbackColour?: string | null): { label: string; colour: string } {
  const p = BY_ALIAS.get(key(name));
  return p ? { label: p.label, colour: p.colour } : { label: name, colour: fallbackColour || OTHER };
}

/** Electoral map: every seat coloured by its current MP's party. */
export function partyChoropleth(seats: Seat[]): Choropleth {
  const index = new Map<string, number>();
  const categories: { label: string; colour: string; count: number }[] = [];
  const raw = seats.map((s) => {
    if (!s.party) return null;
    const { label, colour } = partyStyle(s.party, s.party_colour);
    let k = index.get(label);
    if (k === undefined) {
      k = categories.length;
      index.set(label, k);
      categories.push({ label, colour, count: 0 });
    }
    categories[k].count++;
    return k;
  });
  // Largest party first, so the category numbers (and legend) read in seat order.
  const order = categories.map((_, k) => k).sort((a, b) => categories[b].count - categories[a].count);
  const remap = new Map(order.map((k, pos) => [k, pos]));
  const sorted = order.map((k) => categories[k]);
  return {
    title: "Party",
    subtitle: "Current MP's party · UK Parliament",
    values: raw.map((k) => (k === null ? null : remap.get(k)!)),
    format: (v) => sorted[v]?.label ?? "–",
    categories: sorted,
  };
}

/** Pseudo-metric id for the party map (used in the URL hash and Themes tab). */
export const PARTY_ID = "party";
