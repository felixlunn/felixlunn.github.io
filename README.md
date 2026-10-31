# Whips Dashboard

Constituency analytics for MPs' offices, researchers and political consultancies. Open the map, pick a seat
(click it, or search by name, MP or postcode) and see how it compares with every other seat in the country,
theme by theme. The homepage opens on the electoral map, with every seat in its MP's party colour.

| Tool | What it answers |
|---|---|
| **Debates** (homepage) | Upcoming Commons debates (not questions, statements or Private Members' Bills) from the UK Parliament calendar, tagged by topic. For each debate it lists the MPs of a chosen party (Lib Dem by default) whose seats are in the most extreme tenth of seats on the figures that debate touches, e.g. a policing debate flags seats with unusually high burglary or anti-social behaviour, and shades the map by those figures. |
| **Battleground** | A party's defences (its seats, most marginal first, with the main challenger) and targets (seats where it came second in 2024, closest first), with the swing needed, a CSV export and a map of both. The party chosen here and in Debates is remembered per browser. |
| **Themes** (thematic organiser) | How does this seat compare on people, households, housing, economy, jobs & pay, health, education, transport, policing and politics? About 150 metrics in all. Every metric shades the map, shows the seat's rank ("42nd highest of 575"), the national figure, and a distribution strip. Full rankings download as CSV. |
| **Constituency dossier** | One-click briefing for a seat: MP and party, 2024 majority and turnout, peer group, the metrics where the seat is most unusual, per-theme tables against national and peer-group averages, and its demographic twins. Exports to CSV or prints as a PDF briefing sheet. |
| **Twins** | Which seats look most like this one? Ranks every seat by similarity across the standardised metrics of whichever themes you tick (closest levels, or same overall shape). Can be restricted to the same nation or region. |
| **Index** | Build a composite index (e.g. *cost-of-living vulnerability* = private renting + household deprivation + claimant rate + ...) with weight sliders. Weights can be negative. The map re-shades and every seat is re-ranked instantly. Presets are included. |
| **Match** | Describe a place ("35% private renters, 30% aged 20-34") and find the seats that fit it best. |
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
  engine.py           analytics: ranks, twins, composite index, profile match, k-means peer groups
  build.py            pipeline entry point
  api.py              optional FastAPI REST API over the same data
  demo.py             synthetic offline dataset for UI development
frontend/             Vite + React + TypeScript + MapLibre GL
  src/lib/analytics.ts  browser port of engine.py (same tests)
.github/workflows/    ci.yml (tests + build) · deploy.yml (refresh data every 2 days + publish)
```

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
`POST /api/v1/match`, `GET /api/v1/metrics`. Interactive docs are at `/docs`. A `Dockerfile` is included for
Render / Fly.io; point `WHIPS_DATA` at the deployed `data.json` URL.

## Method notes

- **Standardisation**: twins, index and match all work on z-scores (seat value minus the mean across seats,
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
