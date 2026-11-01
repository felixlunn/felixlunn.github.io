# Whips Dashboard

Constituency analytics for MPs' offices, researchers and political consultancies. Open the map, pick a seat
(click it, or search by name, MP or postcode) and see how it compares with every other seat in the country,
theme by theme. The homepage opens on the electoral map, with every seat in its MP's party colour.

| Tool | What it answers |
|---|---|
| **Debates** | Upcoming Commons debates (not questions, statements or Private Members' Bills) from the UK Parliament calendar, tagged by topic. For each debate it lists the MPs of a chosen party (Lib Dem by default) whose seats are in the most extreme tenth of seats on the figures that debate touches, e.g. a policing debate flags seats with unusually high burglary or anti-social behaviour, and shades the map by those figures. With an office set (below), it shows how your seat ranks on every debate's figures and can filter to the debates where it stands out. |
| **Your office** (header) | The single search bar: choose the MP's office using the dashboard (search by MP, seat or postcode). It opens that seat's briefing (now headed by the upcoming debates where the seat stands out and a neighbourhoods summary), and does so on every later visit. The map outlines and zooms to that seat, Debates ranks it on each debate, Themes and Twins start from it, and the party flagged in Debates defaults to the MP's. Saved per browser; share `…/#office=<GSS code>` ("Copy link for this office") to set up a colleague's browser in one click. |
| **Neighbourhoods** | For seats held by Lib Dem MPs in England & Wales: every LSOA (about 1,500 residents each) in the seat, labelled with its ward and council, mapped and ranked on any Census 2021 metric, with badges where it is in the top or bottom 10% of all 35,672 LSOAs in England & Wales, and a CSV of every metric. One small file per seat (`data/lsoa/<code>.json`), loaded on demand. |
| **Themes** (thematic organiser) | How does this seat compare on people, households, housing, economy, jobs & pay, health, education, transport, policing and politics? About 150 metrics in all. Every metric shades the map, shows the seat's rank ("42nd highest of 575"), the national figure, and a distribution strip. Full rankings download as CSV. |
| **Constituency dossier** | One-click briefing for a seat: MP and party, 2024 majority and turnout, peer group, the metrics where the seat is most unusual, per-theme tables against national and peer-group averages, and its demographic twins. Exports to CSV or prints as a PDF briefing sheet. |
| **Twins** | Which seats look most like this one? Ranks every seat by similarity across the standardised metrics of whichever themes you tick (closest levels, or same overall shape). Can be restricted to the same nation or region. |
| **Index** | Build a composite index (e.g. *cost-of-living vulnerability* = private renting + household deprivation + claimant rate + ...) with weight sliders. Weights can be negative. The map re-shades and every seat is re-ranked instantly. Presets are included. |
| **Peer groups** | Every seat is clustered (k-means on its census profile) into one of 8 peer groups, so "national average" isn't the only benchmark. |

## Data

All data are open, refreshed automatically **every two days** by GitHub Actions, and keyed by GSS code to the
**July 2024 Westminster constituencies** (650 seats).

| Source | Used for | Coverage | Refresh |
|---|---|---|---|
| [ONS Open Geography Portal](https://geoportal.statistics.gov.uk/) | Constituency boundaries (ultra-generalised, web-optimised) | UK | Static |
| [Census 2021 via Nomis](https://www.nomisweb.co.uk/) | ~100 metrics across people, households, housing, economy, health, education, transport | England & Wales | Static (2021) |
| [ONS ASHE via Nomis](https://www.nomisweb.co.uk/sources/ashe) | Median pay of residents and of jobs based in the seat | Great Britain | Annual |
| [ONS Annual Population Survey via Nomis](https://www.nomisweb.co.uk/sources/aps) | Employment and inactivity rates, share in managerial/professional jobs | Great Britain | Quarterly (12-month) |
| [ONS BRES via Nomis](https://www.nomisweb.co.uk/sources/bres) | Jobs located in the seat by industry; jobs per working-age resident | Great Britain | Annual |
| [ONS UK Business Counts via Nomis](https://www.nomisweb.co.uk/sources/ukbc) | Business sites per resident, micro-business share | UK | Annual |
| [ONS small-area population estimates via Nomis](https://www.nomisweb.co.uk/sources/pest) | Population change since 2021 | England & Wales | Annual |
| [ONS Claimant Count via Nomis](https://www.nomisweb.co.uk/sources/cc) | Claimant rate (16-64) | UK | Monthly |
| [police.uk API](https://data.police.uk/docs/) | Crime rates by type, share of crimes closed with no suspect identified, share charged or sent to court | England, Wales, NI | Monthly |
| [House of Commons Library CBP-10009](https://commonslibrary.parliament.uk/research-briefings/cbp-10009/) | 2024 result, majority, turnout, party vote shares | UK | Static |
| [ONS Open Geography Portal](https://geoportal.statistics.gov.uk/) | LSOA 2021 boundaries and LSOA to ward lookup for the Neighbourhoods view | England & Wales | Static |
| [English Indices of Deprivation 2025](https://www.gov.uk/government/statistics/english-indices-of-deprivation-2025) (MHCLG) | Deprivation theme (share of residents in the most deprived 10%/20% of neighbourhoods, average IMD score, income, employment, child and pensioner deprivation), built from LSOAs with population weights; IMD decile and scores per neighbourhood | England | Static (2025) |
| [Energy Performance Certificates](https://get-energy-performance-data.communities.gov.uk/) (MHCLG) | Share of homes rated EPC A-C and F-G (domestic certificates lodged in the last 10 years). Needs a free bearer token as the `EPC_TOKEN` repository secret | England & Wales | Every run |
| [DfE Get Information about Schools](https://get-information-schools.service.gov.uk/) | Pupils eligible for free school meals, at academies, at independent schools (schools located in the seat) | England | Every run |
| [DfE Key stage 4 performance](https://explore-education-statistics.service.gov.uk/find-statistics/key-stage-4-performance) | GCSE English & maths grade 4+/5+ and Attainment 8, by pupils' constituency of residence | England | Annual |
| [UK Parliament What's On](https://whatson.parliament.uk/) | Upcoming Commons debates for the Debates panel (next 3 weeks) | UK | Every run |
| [UK Parliament Members API](https://members-api.parliament.uk/) | Current MP and party (picks up by-elections and defections) | UK | Every run |

Census 2021 covers England and Wales only (Scotland's census was 2022 and Northern Ireland's is published by
NISRA), so census metrics show "No data" for Scottish and Northern Irish seats. Wherever a metric is a ratio,
the national figure is the true combined rate (total numerator / total denominator), not an average of seat
averages.

Boundaries and Census are required: if either fails, the run fails and the live site keeps the last good
version. The other sources are optional: if one fails, the site still updates and the **Data updated** link in
the header shows which source failed.

## Architecture

```
GitHub Actions (every 2 days)
  └─ python -m whips.build      fetch APIs → compute metrics + peer groups
       └─ frontend/public/data/  data.json · boundaries.geojson · constituencies.csv
  └─ npm run build               React + MapLibre static site
  └─ deploy to GitHub Pages
```

The site is fully static and the analytics run in the browser. For 650 seats × ~60 metrics, an exact
similarity search or index recalculation takes well under a millisecond, so sliders respond instantly without
a server, a cache or an approximate-nearest-neighbour index. The whole dataset is about 120 kB gzipped, and
MapLibre loads in parallel as its own chunk.

```
whips/                Python package
  metrics.py          catalogue of themes and metrics (add new census metrics here)
  sources/            one adapter per API: nomis, boundaries, police, parliament
  engine.py           analytics: ranks, twins, composite index, k-means peer groups
  build.py            pipeline entry point
  api.py              optional FastAPI REST API over the same data
  demo.py             synthetic offline dataset for UI development
frontend/             Vite + React + TypeScript + MapLibre GL
  src/lib/analytics.ts  browser port of engine.py (same tests)
.github/workflows/    ci.yml (tests + build) · deploy.yml (refresh data every 2 days + publish)
```

## Map style

Choropleths use a temperature scale (cool blue for low values, through pale yellow, to hot red for high;
ColorBrewer RdYlBu), set in `frontend/src/lib/colors.ts`. Underneath is the standard OpenStreetMap map (no API key;
used within the [OSM tile usage policy](https://operations.osmfoundation.org/policies/tiles/), with attribution), which shows
through as you zoom in. The "Base map: on/off" button at the top left of the map hides or shows it, remembered per browser.

## Running it

```bash
pip install -e ".[dev]"
```

```bash
python -m whips.build --out frontend/public/data
```

This fetches real data from the live APIs and takes about 10-20 minutes, mostly police.uk. Add `--skip police`
to skip the slowest source. For offline UI work, use `--demo` instead, which writes clearly labelled synthetic
data.

```bash
cd frontend && npm install && npm run dev
```

Tests:

```bash
pytest
```

```bash
cd frontend && npm test
```

### Deploying to GitHub Pages

1. In the repository go to **Settings → Pages** and set **Source** to **GitHub Actions**.
2. Merge to `main` (or run **Actions → Refresh data & deploy → Run workflow**).
3. Optional: add a `NOMIS_UID` repository secret ([free Nomis account](https://www.nomisweb.co.uk/myaccount/userjoin.asp)) for higher API limits.

The site will be at `https://<owner>.github.io/<repo>/`. Generated data are published with the site and kept
as a 30-day workflow artifact; they are not committed, so the git history stays small.

### Optional REST API

```bash
pip install -e ".[api]"
```

```bash
WHIPS_DATA=frontend/public/data/data.json uvicorn whips.api:app
```

Endpoints: `GET /api/v1/constituencies/{code}`, `GET /api/v1/twins/{code}`, `POST /api/v1/index`,
`GET /api/v1/metrics`. Interactive docs are at `/docs`. A `Dockerfile` is included for
Render / Fly.io; point `WHIPS_DATA` at the deployed `data.json` URL.

## Method notes

- **Standardisation**: twins and index both work on z-scores (seat value minus the mean across seats,
  divided by the standard deviation), so a percentage-point gap in a rare characteristic counts as much as a
  larger gap in a common one.
- **Twins, Euclidean** = 1 / (1 + RMS distance in SD units); **cosine** = similarity of the pattern of
  above/below-average traits regardless of how extreme they are.
- **Policing**: each constituency's boundary polygon is queried against police.uk for the latest 3 months
  (`POLICE_MONTHS` to change it), then annualised per 1,000 residents. Crimes are located to anonymised map
  points, so seat-edge attribution is approximate. Outcome shares only count crimes with a final outcome;
  recent months are still being investigated, so treat them as provisional.
- **Census 2021 travel to work** was collected during lockdown (March 2021), so work-from-home figures are
  elevated.

## Roadmap

These parts of the original plan are not built yet:

- **Rail performance** (station delays and cancellations). Needs Rail Data Marketplace / HSP credentials; add
  them as a repository secret and write a `whips/sources/rail.py` adapter.
- **Schools**: DfE Explore Education Statistics (KS4 / Progress 8) and Ofsted. Most data are school- or
  local-authority-level, so they need a school → constituency lookup.
- **Health services**: NHS GP access and waiting lists by ICB, apportioned to constituencies.
- **Energy**: DESNZ EPC ratings and fuel poverty (sub-regional fuel poverty is published by LSOA → best-fit to
  constituencies).
- **Small-area view**: LSOA/MSOA layer (PMTiles) with drill-down from constituency.
- **Ward-level and local-election data** (Democracy Club), swing/marginality modelling and MRP integration.
- **Hansard / written questions** feed matched to the seat's outlier metrics.
