# Rooftop Solar Potential Estimator (Bengaluru pilot)

Open-data web app (pilot: **Kumaraswamy Layout, Bengaluru**) that estimates, for individual buildings, how much electricity a rooftop can generate **after shadows from neighbouring buildings and trees**, what it would cost, and how long it takes to pay back. MapLibre front end, Python/FastAPI back end, only open data, no API keys, no paid services.

> **Scope.** Real solar calculations exist only for the analysed study areas: the Kumaraswamy Layout pilot (2.06 km², default) and an earlier Indiranagar–Domlur pilot (2.03 km²). The rest of Bengaluru is a basemap. Select a rectangle on the map to run the pipeline for another area (≤ 2.5 km²).
> **Status.** All figures are modelled estimates. **No field validation has been performed** (see [Validation status](#validation-status)). Retail energy charges are the official BESCOM FY2026-27 rates (tariff booklet); the FY25 true-up and PM Surya Ghar subsidy amounts are still unverified.

## Architecture

```
open datasets ──► rse.ingest ──► data/raw/<area>/ ──► rse.pipeline ──► data/processed/<area>/ ──► rse.api (FastAPI) ──► React + MapLibre
 Overture, Open Buildings V3,      (idempotent        footprints → QA → heights → canopy →       buildings.parquet (GeoParquet),    /api/...      map, ranking, detail panel,
 2.5D heights, canopy, OSM,         downloads)         shadow engine → pvlib energy →             obstacles_utm.parquet, trees.parquet,            shadow-time slider, validation page
 NASA POWER, PVGIS                                     economics → ranking                        meta.json, qa_*.geojson
```

| Package | Role |
|---|---|
| `backend/rse/geometry.py` | UTM-43N projection, geodesic footprint area, roof cell grid |
| `backend/rse/sun.py` | pvlib solar position (azimuth/elevation) |
| `backend/rse/shadow.py` | STRtree-indexed shadow engine (sweep of footprints along the shadow vector) |
| `backend/rse/pv.py` | NASA typical year, closure QC, POA irradiance, temperature and PV model (pvlib) |
| `backend/rse/heights.py` | height hierarchy with provenance; footprint model (only with real measurements) |
| `backend/rse/economics.py` | scenarios, capacity, cost, savings by metering mechanism, simple payback |
| `backend/rse/ingest.py`, `pipeline.py` | data acquisition and the end-to-end analysis |
| `backend/rse/api.py` | REST API; serves the built front end if `frontend/dist` exists |
| `frontend/` | React + TypeScript + MapLibre GL JS + Recharts |

Storage: **GeoParquet + in-memory spatial indexes** instead of PostGIS (an equally suitable open-source option for a single-machine project; the data per area is a few MB). Expensive area analysis runs in a background thread (`POST /api/jobs`); shade results are cached on disk keyed by a hash of geometry, heights, shadow casters and settings.

## Install and run

Requirements: Python 3.11+, Node 20+, internet access (no accounts).

```bash
pip install -r requirements.txt
cp .env.example .env              # optional; no secrets are needed

# 1. acquire data and analyse the pilot (≈ 40–60 min on one CPU core; ~10 min of that is downloads)
python scripts/ingest_pilot.py    # footprints, heights, canopy, OSM, Open Buildings V3
python scripts/fetch_irradiance.py  # NASA POWER hourly 2015–2024 (+ run once: PVGIS check is stored in data/raw)
python scripts/run_pilot.py       # shadows, energy, economics → data/processed/indiranagar-pilot/

# 2. run
cd frontend && npm install && npm run build && cd ..
uvicorn rse.api:app --app-dir backend --port 8000     # open http://localhost:8000
# development: npm run dev (port 5173, proxies /api to :8000)

# 3. tests
python -m pytest tests -q
```

The PVGIS comparison reads `data/raw/pvgis_PVGIS-ERA5.json`; fetch it with
`https://re.jrc.ec.europa.eu/api/v5_3/PVcalc?lat=12.979&lon=77.640&peakpower=1&loss=14&angle=12&aspect=0&raddatabase=PVGIS-ERA5&outputformat=json`.

## Datasets (all public, no credentials)

| Data | Source | Licence | How acquired |
|---|---|---|---|
| Building footprints | Overture Maps buildings, release 2026-10-21.0 (`s3://overturemaps-us-west-2`) | ODbL / CDLA-P (OSM-derived rows ODbL) | DuckDB over public S3, bbox filter |
| Footprint cross-check | Google Open Buildings V3 polygons (`gs://open-buildings-data/v3`) | CC BY 4.0 / ODbL | streamed S2 level-6 tile, bbox filter |
| Heights | Open Buildings 2.5D Temporal v1, 2023-06-30 (`gs://open-buildings-temporal-data`) | CC BY 4.0 | ranged reads of the covering GeoTIFF tile |
| Tree canopy | Meta/WRI Global Canopy Height Map v1 (`s3://dataforgood-fb-data/forests/v1`) | CC BY 4.0 | ranged reads of the z9 quadkey tile |
| Trees, tags, addresses | OpenStreetMap via Overpass | ODbL | public mirrors, tiled queries |
| Irradiance | NASA POWER hourly (GHI, DNI, DHI, T2M, WS10M), 2015–2024 | public domain | REST API |
| Unshaded yield check | PVGIS PVcalc (ERA5) | © European Union, reuse permitted | REST API, **comparison only** |
| Basemap | OpenFreeMap vector tiles (© OpenStreetMap contributors) | ODbL | MapLibre style URL |
| Costs, export tariffs, metering rules | KERC order 25.08.2026 and KERC DSPV Regulations 2026 (hosted at `srtpv.bescom.org`) | public regulatory documents | read manually; values stored in `config.ECON_PARAMS` with source and effective date |
| Retail tariffs, electricity tax, solar fixed-charge rebate | BESCOM “Electricity Tariff 2026 to 2028” booklet (KERC order 27.03.2025), schedules LT-1/2/3(a)/5, FY2026-27 | public regulatory document | read from the official PDF; stored in `config.ECON_PARAMS` |

Earth Engine is not used (it needs authentication). **Refreshing:** delete `data/raw/<area>` (and `data/cache`) and re-run ingest + pipeline; change `OVERTURE_RELEASE` in `ingest.py` to move to a newer release.

## API

`GET /api/health` · `/api/areas` · `/api/areas/{id}/meta` · `/buildings` (GeoJSON) · `/trees` · `/missing` · `/ranking?min_kwh&max_shading_pct&min_usable_m2&min_kwp&quality&limit`
`GET /api/areas/{id}/buildings/{bid}` · `POST .../recalculate` (body `{economics:{…}, pv:{tilt_deg, azimuth_deg, system_loss_pct}}`)
`GET /api/areas/{id}/shadows?time=ISO[&west&south&east&north]` (ground shadows for a date/time, IST if no zone) · `GET .../buildings/{bid}/shade?time=ISO` (roof cells + shadow sources)
`GET /api/sunpath?date=YYYY-MM-DD` · `GET /api/search?q=` (Nominatim proxy, 1 req/s; coordinates accepted) · `GET /api/assumptions`
`POST /api/jobs` `{bbox,name}` / `GET /api/jobs/{id}` · `POST /api/contributions` (stored as *unverified*)
`GET /api/areas/{id}/validation` · `POST /api/validation/height-measurements` · `POST /api/validation/shadow-checks`

## Environment variables

None are required. Optional: `RSE_CORS_ORIGINS`, `RSE_NOMINATIM_EMAIL`, `RSE_OVERPASS_URL`, `RSE_MAX_JOB_KM2` (see `.env.example`; values go in a local `.env`, never in this README, and `.env` is git-ignored). No dataset needed a credential, so there are no credential-acquisition steps.

## Methodology and assumptions

**Footprints.** Overture rows are made valid, exploded to polygons, ≥3 m²; pairs with IoU > 0.5 are de-duplicated (larger kept), 0.1–0.5 are flagged. Open Buildings V3 (confidence ≥ 0.70, ≥ 15 m²) and OSM structures absent from Overture are recorded as *possibly missing* (`qa_missing_buildings.geojson`), not added silently.

**Heights** (first available wins; every building stores its source and a range): field-measured → mapped height tag (Overture/OSM) → Open Buildings 2.5D Temporal median over footprint pixels (presence ≥ 0.5, coverage ≥ 50%, ≥ 4 pixels) → floors × 3 m → footprint model `h = a + b·ln(area)` fitted/tested only if ≥ 10 real measurements exist (70/30 split, MAE reported) → neighbourhood median of the same size class, flagged `unverified` with an IQR range. Conflicts between sources (> max(3 m, 40%)) flag the building `unverified`.

**Trees.** Canopy height ≥ 3 m, pixels inside building footprints (+1 m) removed (canopy products are contaminated by roofs), > 35 m discarded as artefacts, classes 3–6/6–10/10–15/15+ m polygonised (≥ 6 m²). OSM tree points without canopy support are flagged and never used. Trees block 70% of the beam (`tree_opacity`).

**Shadows.** `L = (h_obstacle − h_roof) / tan(elevation)`, direction `(−sin az, −cos az)`. Each obstacle is decomposed into convex-ish pieces (concave footprints triangulated, trees tiled 6 m) and swept along the vector; a roof cell (1 m grid, 0.5 m setback, ≤ 400 cells) is shaded if inside any swept piece. Roof shaded fraction = shaded cells / cells. Beam loss = building share + 0.7 × tree-only share. Only obstacles taller than the roof by > 0.3 m and within 150 m are considered; sun < 3° elevation is skipped; flat ground. Shade is computed for the 15th of every month at each interval hour and applied to the whole month in the NASA typical year; direct beam is reduced, diffuse and ground-reflected irradiance are retained.

**Energy.** Typical year: per month, the year (2015–2024) closest to the 10-year mean GHI (simplified TMY-style). NASA POWER does not close its own balance (DNI·cosZ + DHI is 4–20% below GHI), so DNI and DHI are rescaled hourly (bounded 0.8–1.5) with GHI as anchor. POA by Hay–Davies, ASHRAE IAM (b = 0.05), SAPM cell temperature (open rack, glass/polymer), PVWatts DC (γ = −0.35%/°C), PVWatts loss categories (soiling 3, mismatch 2, wiring 2, connections 0.5, LID 1.5, nameplate 1, availability 2, **shading 0 because it is modelled explicitly**) ≈ 11.6%, inverter 97% with DC/AC 1.15. Default array: 12° tilt, south; roof orientation is unknown.

**Capacity.** usable area = footprint × {25, 50, 70}%; kWp = usable area / 7.4 m² per kWp (540 W, 2.583 m² module → 20.9% efficient, 65% layout efficiency). The middle scenario ranks buildings by annual kWh.

**Money** (indicative, `economics.py`). Capital cost: KERC benchmark ₹45,000/kW (domestic ≤ 10 kW) or ₹27,090/kW (non-DCR) / ₹36,015/kW (DCR); ±10% analyst spread. **Retail energy charge follows the BESCOM schedule inferred from the building use** (Overture subtype; unknown → by system size): LT-1 residential/religious ₹5.80, LT-2 private medical/education ₹6.55, LT-3(a) commercial ₹6.80, LT-5 industrial ₹4.40 per kWh (FY2026-27). Because Karnataka levies a 9% electricity tax on charges payable, avoided energy charges also avoid that tax (switchable). Under net metering / net billing a self-consumption (offset) share earns the retail energy charge and the rest the KERC PPA tariff (₹3.89 domestic 1–10 kW, ₹2.34 non-DCR, ₹3.11 DCR); gross metering pays the PPA tariff on everything; behind-the-meter pays nothing for exports. Scenarios 30/60/90% self-consumption because consumption is unknown. Fixed charges and the FY25 true-up (₹0.56/kWh, billed on FY2024-25 consumption) are **not** counted as savings. The LT-1 rooftop-solar fixed-charge rebate (₹25/kW/month, domestic ≤ 10 kW) is shown separately. Simple payback = cost / annual savings (no O&M, financing, degradation or escalation). The PM Surya Ghar subsidy is shown separately, off by default, eligibility unverified. The real tariff schedule depends on the actual connection, which is unknown; medical/education buildings are assumed private.

## Known limitations

- No detection of tanks, stair rooms, parapets; the 25/50/70% shares stand in. A contribution form collects roof details as **unverified** records (`data/contributions/contributions.jsonl`) that never alter calculations.
- Roof tilt and orientation unknown; one default array geometry for all roofs.
- NASA POWER is a ~0.5° × 0.625° regional product; the 2.5D height raster is ~4 m resolution and unreliable for small roofs; canopy data is ~2018–2020.
- Ground is flat; shadow of roof-mounted obstacles and inter-row shading are not modelled.
- Missing information makes estimates **optimistic**.
- **Tariff inputs**: retail rates, electricity tax and the solar rebate are read from the official BESCOM tariff booklet. Still unverified: the FY25 true-up amount (news reports) and PM Surya Ghar subsidy amounts (not re-fetched). FPPCA (monthly fuel adjustment) is not modelled. Government hospitals/schools, HT consumers (> 150 kW) and the real sanctioned load are not known per building. Check `GET /api/assumptions` — every parameter carries a `verified` flag.
- Overpass mirrors are slow and unreliable: for Kumaraswamy Layout OSM returned only a handful of tree points and **no buildings**, so OSM address/height tags, the OSM footprint cross-check and the OSM tree second pass are effectively absent there (the QA report states it). Overture already contains OSM-derived footprints.
- Small roofs (< ~4 raster pixels) get no 2.5D height; ~24% of Kumaraswamy Layout buildings therefore use the flagged `unverified` neighbourhood-median height.

## Validation status

| Check (from the project brief) | Status |
|---|---|
| Unit tests for area, heights, sun position, shadow length/direction, shaded fraction, scenarios, energy, payback, invalid input, monotonic shading | **42 tests pass** |
| Unshaded yield vs PVGIS-ERA5 (independent dataset, not an input) | **Done**: see `GET /api/areas/{id}/validation` (model ≈ +1% on specific yield, ≈ −1% on in-plane irradiation; without the closure correction ≈ −8%/−10%) |
| Height measurements on 10–15 structures | **Not performed** – workflow built (`POST /api/validation/height-measurements`); the footprint height model stays uncalibrated until ≥ 10 exist |
| Field shadow checks on 3–5 roofs at three times of day | **Not performed** – workflow built (`POST /api/validation/shadow-checks`), errors computed automatically |
| QA of 20 roofs against imagery/field | **Not performed** |
| Second-pass tree review | Canopy filtering done; OSM tree-point comparison only 4 points available for Kumaraswamy Layout (0 supported by canopy height); field spot-check **not performed** |
| Live shade vs stored annual shade table | 52 comparisons (Kumaraswamy Layout): mean abs difference 0.05 percentage points, max 0.5 |
| Browser acceptance (headless Chromium) | Map loads, building click opens panel with data/shade/energy/finance, second building updates panel, shadow layer geometry changes with time, rectangle selection reports area statistics |

The closure correction was adopted because NASA's own components do not sum to its GHI; PVGIS was compared afterwards and was not used to tune any parameter.

## Tests

`python -m pytest tests -q` – covers footprint area, height hierarchy and the refusal to calibrate on too few measurements, solar position (equator equinox, Bengaluru solstices, night), shadow length/direction/sweep, concave footprints, hand-computed roof shaded fraction, scenarios, capacity, payback, export valued below retail, subsidy separation, monotonic shading vs energy, diffuse retention, and invalid inputs.
