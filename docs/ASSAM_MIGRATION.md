# Assam Migration Log — 72-Hour Warning Phase 1

## Migration Progress Checklist

- [x] **Phase A: Pre-Flight**
  - [x] Clean base check on `main` (base SHA: `1e25ed9f98d4e5ab1df0d2313b6adeb6dcafbe42`)
  - [x] Branch `feat/assam-migration` created
  - [x] Baseline test suite: 21 passed, 0 failed
  - [x] Pre-flight answers recorded; `.env` & data artifacts ignored in `.gitignore`; `.env.example` created
- [x] **Phase B: Inventory of Maharashtra**
  - [x] Codebase provenance recorded
  - [x] Full scan of tracked & untracked files for Maharashtra terms
  - [x] Inventory table produced with concrete actions (delete / rewrite / generalise / keep)
- [x] **Phase C: Geography & City Configs (Assam)**
  - [x] Real district boundaries & asset locations fetched / cached (`data/cache/osm/ind_adm2_simplified.geojson`)
  - [x] `configs/upper_assam.yaml` (10 zones x 6 systems, Nagaland upstream drivers included, real Shapely adjacency)
  - [x] `configs/north_bank_assam.yaml` (6 zones x 5 systems held-out topology)
  - [x] `configs/scenarios/assam_2026/windows.yaml` (named UTC windows)
  - [x] `frontend/public/geo/upper_assam.geojson` simplified boundary file (77.0 KB, <300 KB)

- [x] **Phase D: Real Data Acquisition (`scripts/fetch_assam_data.py`)**
  - [x] 2 GB size budget enforcement & time-boxing (15 min per source) in `scripts/fetch_assam_data.py`
  - [x] Open-Meteo archive rain & soil moisture (10,080 rows cached for 10 zones, UTC hourly)
  - [x] NASA Earthdata GPM IMERG Late run subsetting via `earthaccess` (granules found & indexed)
  - [x] Copernicus CDS ERA5-Land (client verified, pending queue handling without blocking)
  - [x] CWC river-level contract & manual drop-in handling (marked unavailable, fallback to labelled `river_level_sim`)
  - [x] Cache under `data/cache/<source>/`, `data/manifest.json`, and offline capability verified (`--offline`)

- [x] **Phase E: Source-Agnostic Rain Adapters**
  - [x] `RainAdapter` protocol and implementations (`IMERGAdapter`, `ERA5LandAdapter`, `OpenMeteoAdapter`, `IMDGriddedAdapter`, `CWCAdapter`)
  - [x] Latency gating (`arrival_time = event_time + latency_hours`)
  - [x] Honest provenance labels (`real`, `simulated`, product IDs)
  - [x] ERA5-Land daily accumulation de-accumulation with 00:00 UTC reset logic
  - [x] IMERG half-hourly to hourly aggregation & missing granule handling
  - [x] Zonal area-weighted mean calculation for polygons

- [x] **Phase F: Synthetic City Generator (Assam Parameters)**
  - [x] Planted graph reflecting Assam physical chain: Nagaland hills -> Upper Assam floodplains
  - [x] Planted graph vs prior discrepancy (surprising edge present, circularity mitigations)
  - [x] Real-rain coupling with simulated downstream systems
  - [x] `anchor_mode: off|on` honesty flag implemented with explicit disclosure string
  - [x] Simulated streams tagged with driver provenance (`QualityFlag.SIMULATED`, `driver=...`)

- [x] **Phase G: Ground Truth & Scenario Files from Assam Report**
  - [x] `configs/scenarios/assam_2026/README.md` (provenance, caveats from Section 1, source quality rules)
  - [x] `events.json` with source tags [S#] and reliability grades A-D (21 events strictly parsed)
  - [x] `critical_labels.json` coarse intervals for real nodes (8 critical node intervals)
  - [x] `observed_response.json` response baseline (8 response milestones for counterfactual evaluation)
  - [x] `official_bulletins.json` ASDMA daily snapshots recorded as observation records
  - [x] Conflict groups preserved (crop area: 11,933.46 vs ~119,000 ha; death toll: 31 vs 41)
  - [x] Documented ambiguities resolved in `docs/ASSAM_MIGRATION.md` (Betbari, Santak, Teok, Nepalikhuti)

- [x] **Phase H: CLI, API, WebSocket, Docs**
  - [x] `scripts/run_replay.py` updated with Assam scenarios, named windows, provenance breakdown, and stream hash
  - [x] FastAPI `/cities` (listing only `upper_assam` and `north_bank_assam`), `/city/{id}`, `/ws/stream`
  - [x] Documentation updated (`docs/DATA_SOURCES.md`, `README.md`, `docs/PHASE1.md`)
  - [x] `.env.example` created with placeholders and documentation

- [x] **Phase I: Final Sweep & Maharashtra Cleanup**
  - [x] Delete inventory items marked for deletion (`configs/mumbai.yaml`, `configs/heldout_city.yaml`, `scripts/generate_rain_fixture.py`, `backend/app/adapters/imd_rain.py`, `data/processed/`)
  - [x] Zero residue check for banned terms (outside migration log and test scanner) verified
- [x] **Phase J: Verification & Comprehensive Test Suite**
  - [x] All existing acceptance tests ported to Assam (50 hermetic tests passing)
  - [x] New tests: hygiene, geography, time, adapters, generator, faults/leakage, ground truth, integration
  - [x] Two consecutive full clean test runs plus random order run (`pytest-randomly`) passed

- [x] **Phase K: Migration Test Report**
  - [x] `tests/ASSAM_MIGRATION_TEST_REPORT.md` written from real test execution output
- [x] **Phase L: Git Commits & Definition of Done**
  - [x] Structured logical commits on `feat/assam-migration`
  - [x] Verification that `main` is untouched

---

## Provenance of this Codebase

This codebase was adapted from an earlier Phase 1 backbone ("72-Hour Warning") originally configured around Maharashtra urban flooding. Under the migration to the Assam July-August 2026 flood event:

### Carried Over from Base Commit (`1e25ed9f98d4e5ab1df0d2313b6adeb6dcafbe42`)
- **Core Architecture & Schema contracts:** `backend/app/schemas.py` (`Observation`, `Edge`, `RiskState`, `PredictionRecord`, `StreamMessage`, `QualityFlag`, `SourceKind`), `backend/app/city_config.py` (YAML config loader).
- **Replay Engine:** `backend/app/replay/clock.py` (`ReplayClock`), `backend/app/replay/stream.py` (`ReplayStream`, `StreamView`).
- **Fault Injection Framework:** `backend/app/replay/faults.py` (`FaultInjector`, `FaultSpec` supporting dropout, stuck-at, spike, feed-delay, contradictory-duplicate, zone-blackout).
- **Synthetic Generator Skeleton:** `backend/app/synth/ground_truth.py`, generator structure in `backend/app/synth/generator.py`.
- **API Surface:** FastAPI skeleton in `backend/app/api.py`.
- **Base Verification Logic:** Core replay, determinism, and leakage-isolation test principles in `tests/test_phase1.py`.

### Built During this Migration
- **Assam Topologies & Configs:** `configs/upper_assam.yaml` (10 zones x 6 systems), `configs/north_bank_assam.yaml` (heldout 6 zones x 5 systems).
- **Geographic Extraction:** `scripts/build_assam_config.py`, OSM Overpass boundary and asset extractors, GeoJSON generator `frontend/public/geo/upper_assam.geojson`.
- **Multi-Product Real Data Pipeline:** `scripts/fetch_assam_data.py` (Open-Meteo, NASA GPM IMERG, Copernicus ERA5-Land, IMD gridded, CWC drop-in contract).
- **Source-Agnostic Rain Adapters:** Refactored `backend/app/adapters/` with latency gating, accumulation conversion, and zonal area aggregation.
- **Physical Cascade Generator:** Re-parameterised `backend/app/synth/planted_graph.py` modeling the Nagaland hills -> Upper Assam plains surge, with anchor mode and circularity mitigations.
- **Ground Truth Scenarios:** `configs/scenarios/assam_2026/` (`events.json`, `critical_labels.json`, `observed_response.json`, `windows.yaml`) fully traceable to `Assam_Floods_2026_Report.md`.
- **Comprehensive Test Suite & Reports:** `tests/test_phase1.py` ported to Assam, test reports in `tests/ASSAM_MIGRATION_TEST_REPORT.md`, documentation in `docs/DATA_SOURCES.md`.

---

## Phase B: Inventory of Maharashtra References

Searches executed across all tracked and untracked files:
- `git grep -niE 'maharashtra|mumbai|thane|konkan|kolhapur|sangli|ratnagiri|raigad|palghar|pune|nashik|satara|asia/kolkata'`
- File and directory searches for `*mumbai*`, `*maharashtra*`, `*konkan*`, `*thane*`

| File / Path | What it is | Action | Rationale / Target |
|---|---|---|---|
| `configs/mumbai.yaml` | 10-zone Maharashtra city configuration | **Delete** (in Phase I) | Replaced by `configs/upper_assam.yaml` |
| `configs/heldout_city.yaml` | Old held-out city config (Nashik/Pune/Satara) | **Delete** (in Phase I) | Replaced by `configs/north_bank_assam.yaml` |
| `data/processed/maharashtra_climate.csv` | Synthetic/fixture daily rainfall for 20 Maharashtra districts | **Delete** (in Phase I) | Replaced by real and fixture Assam rainfall data |
| `scripts/generate_rain_fixture.py` | Generates Maharashtra synthetic daily climate CSV | **Delete** (in Phase I) | Replaced by Assam data acquisition & test fixtures |
| `backend/app/adapters/imd_rain.py` | IMD rain adapter with hardcoded Mumbai 2019 / Konkan 2021 presets | **Generalise** | Refactor into source-agnostic `RainAdapter` layer supporting IMERG, ERA5-Land, Open-Meteo, IMD |
| `backend/app/synth/planted_graph.py` | Planted graph hardcoded with drainage/roads/emergency/hospital | **Generalise** | Dynamic graph mapping Assam infrastructure systems (`river_embankment`, `transport`, `power`, `comms`, `health`, `emergency_response`) and Nagaland-to-Assam hydrological edges |
| `backend/app/synth/generator.py` | Generator hardcoding drainage driving rain, Mumbai parameters | **Generalise** | Support zonal real rain driving river embankment, add `anchor_mode` flag, label simulated streams |
| `backend/app/api.py` | Default city `"mumbai"`, presets lookup | **Rewrite** | Default city `"upper_assam"`, dynamically read scenario windows and configs |
| `scripts/run_replay.py` | CLI default `--city mumbai`, `--rain-window mumbai_2019/konkan_2021` | **Rewrite** | Default `--city upper_assam`, `--scenario assam_2026`, named rain windows |
| `tests/conftest.py` | Fixtures `mumbai_config`, `maharashtra_climate.csv` | **Rewrite** | Provide `upper_assam_config`, `north_bank_config`, and Assam fixtures |
| `tests/test_phase1.py` | Tests with hardcoded Mumbai/Thane dates and values | **Rewrite / Port** | Port all acceptance tests to Assam topologies, add new hygiene/geography/canary tests |
| `docs/PHASE1.md` | Phase 1 docs referencing Mumbai commands | **Rewrite** | Update commands to Upper Assam hero scenario |
| `README.md` | Top-level readme referencing Mumbai | **Rewrite** | Update description and commands to Assam 2026 |

---

## Schema Changes Documentation (Rule 1 Compliance)

No breaking schema changes have been made.
- `Zone`: Added optional backward-compatible fields: `systems: list[str] | None = None`, `jurisdiction: str | None = None`, `role: str | None = None`, `river_links: list[dict[str, Any]] = Field(default_factory=list)`, `assets: dict[str, Any] | list[dict[str, Any]] = Field(default_factory=dict)`.
- `Observation`: `quality_flags` allows standard `QualityFlag` enum values as well as descriptive string flags (e.g. `real`, `simulated`, `anchored`, `product=...`, `aggregation=area_mean`).
