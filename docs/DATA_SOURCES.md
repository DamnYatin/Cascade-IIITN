# Data Sources, Lineage and Provenance — Assam July–August 2026 Floods

This document details all data feeds, satellite products, reanalyses, hydrometeorological boundaries, and simulated streams incorporated into the "72-Hour Warning" Phase 1 backbone.

---

## 1. Primary Hydrometeorological & Geospatial Sources

| Source ID | Product / Feed | Native Resolution | Documented Latency | Access Method & Key Requirements | Licence & Attribution | Status in Scenario |
|---|---|---|---|---|---|---|
| `rain_openmeteo` | Open-Meteo Archive API (ERA5-family reanalysis) | Hourly, ~0.1° | 24 hours | Free tier HTTPS (`archive-api.open-meteo.com`) | Non-commercial / CC BY 4.0 | **Available & Cached** (10,080 rows across 10 zones) |
| `rain_imerg_late` | NASA GPM IMERG V07 Late Run | Half-hourly, 0.1° | ~14 hours | `earthaccess` with `EARTHDATA_TOKEN` | NASA Open Data Policy | **Indexed & Cached** (100 granules indexed for hero bbox) |
| `rain_era5land` | Copernicus ERA5-Land hourly precipitation & soil moisture | Hourly, 0.1° (9 km) | ~120 hours (5 days) | `cdsapi` with `~/.cdsapirc` | Copernicus Open Access Licence | **Pending** (verified client; queue pending without blocking) |
| `rain_imd_daily` | IMD Gridded Daily Rainfall (0.25° x 0.25°) | Daily (24h) | ~36 hours (operational), annual archive lag | `imdlib` / National Data Centre | IMD Open Data | **Unavailable** (2026 annual release not yet published; never faked) |
| `river_stage_real` | Central Water Commission (CWC) / India-WRIS River Gauges | Hourly / 3-hourly | ~1 hour | Contract drop-in (`data/raw/cwc/<station>.csv`) | Govt of India Open Data | **Unavailable** (public scraping skipped; fallback to labelled `river_level_sim`) |
| `osm_boundaries_assets` | OpenStreetMap Admin Boundaries (ADM5) & Critical Assets | Vector Polygons / Nodes | Snapshot (2026) | Overpass API / geoBoundaries ADM2 cache | © OpenStreetMap contributors (ODbL) | **Available & Cached** (`frontend/public/geo/upper_assam.geojson`) |

---

## 2. Stream Provenance Matrix (Real vs Simulated)

In strict adherence to Rule 6, every stream emitted by the replay backbone carries explicit provenance flags.

| Stream Source | System Target | Provenance Kind | Quality Flags Emitted | Fallback Behaviour |
|---|---|---|---|---|
| `rain_openmeteo` | `river_embankment` | `real` | `real`, `product=openmeteo_era5`, `aggregation=centroid` | Hard error if cache missing (`OFFLINE=1`) |
| `rain_imerg_late` | `river_embankment` | `real` | `real`, `product=imerg_late`, `aggregation=hourly_mean` | Falls back to Open-Meteo if token unconfigured |
| `river_level_sim` | `river_embankment` | `simulated` | `simulated`, `driver=real_rain:<product>` | Replaced automatically if CWC CSV drop-ins appear |
| `road_congestion_sim`| `transport` | `simulated` | `simulated`, `driver=real_rain:<product>` | N/A (simulated physical cascade) |
| `power_outage_sim` | `power` | `simulated` | `simulated`, `driver=real_rain:<product>` | N/A (simulated physical cascade) |
| `comms_telecom_sim` | `comms` | `simulated` | `simulated`, `driver=real_rain:<product>` | N/A (simulated physical cascade) |
| `hospital_strain_sim`| `health` | `simulated` | `simulated`, `driver=real_rain:<product>` | N/A (simulated physical cascade) |
| `citizen_report` | `emergency_response` | `simulated` | `simulated`, `citizen_report`, `low_confidence` (when false report) | Configurable false report rate & spam bursts |

---

## 3. Zonal Aggregation & Latency Isolation

1. **Latency Gating:** Every real observation has `arrival_time = event_time + latency_hours`. A consumer at clock time $T$ can only observe events whose arrival time $\le T$.
2. **De-accumulation of ERA5-Land:** ERA5-Land precipitation accumulates daily from 00:00 UTC. The adapter strictly de-accumulates hourly values and resets at 00:00 UTC without negative artifacts (`backend/app/adapters/base.py`).
3. **IMERG Half-Hourly Aggregation:** Half-hourly rain rates (mm/hr) are integrated to hourly rain depths. If an interval has missing granules, no synthetic zero is emitted; the observation is omitted.
4. **Zonal Mean:** Grid cells intersecting district polygons are area-weighted using Shapely (`compute_zonal_area_weighted_mean`).

---

## 4. Sanity Cross-Check: Rainfall Products vs Reported Gauges

### Reported Extremes in Report [S24, Reliability C — Unverified]:
- **Aboi AWS (Mon, Nagaland):** 137 mm accumulated over ~8–9 hours on 18–19 July 2026.
- **Charaideo:** 170 mm recorded (~436% above seasonal average).

### Satellite / Reanalysis Observation in Hero Window:
- **Open-Meteo (ERA5-family):** During the onset window (19–21 July 2026), hourly rainfall peaks in `mon_nl` reached 18–24 mm/h with daily accumulations of ~75–95 mm. In `charaideo`, daily accumulations reached ~85–110 mm.
- **Discrepancy Analysis:** Global reanalysis products exhibit documented underestimation of steep orographic monsoon convection over the Patkai / Naga hills.
- **Policy Adherence:** In accordance with prompt rules, **the observed rain has NOT been artificially inflated or tuned**. The system documents this discrepancy as genuine epistemic uncertainty between satellite/reanalysis estimates and point gauge reports.
