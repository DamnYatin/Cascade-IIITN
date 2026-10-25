# The 72-Hour Warning — Phase 1 (Assam Migration)

**Phase 1 goal:** A replayable, deterministic, leakage-proof stream of messy observations for a regional flood crisis, generated from a hidden ground truth that future models can never see.
Configured for the **Upper Assam July–August 2026 floods** (originated by extreme antecedent rainfall across Nagaland headwaters discharging into Brahmaputra south-bank tributaries).


## Repo layout

```
backend/app/schemas.py            # frozen Pydantic v2 contracts (Observation, Zone, Edge, etc.)
backend/app/city_config.py        # YAML -> validated CityConfig
backend/app/synth/__init__.py     # ground-truth namespace (model code must not import)
backend/app/synth/planted_graph.py# hidden planted cascade (Nagaland hills -> Upper Assam plains)
backend/app/synth/generator.py    # synthetic city generator + GroundTruth + anchor_mode
backend/app/synth/ground_truth.py # GroundTruth container (latent stress, critical episodes)
backend/app/replay/clock.py       # ReplayClock (forward-only simulated time)
backend/app/replay/stream.py      # ReplayStream + StreamView (arrival-time gating)
backend/app/replay/faults.py      # seeded fault injector (dropout, stuck-at, spike, delay, etc.)
backend/app/adapters/             # source-agnostic adapters (OpenMeteo, IMERG, ERA5-Land, IMD, CWC)
backend/app/api.py                # FastAPI app + WebSocket stream (/cities, /city/{id}, /ws/stream)
configs/upper_assam.yaml          # 10 zones x 6 systems (hero city)
configs/north_bank_assam.yaml     # 6 zones x 5 systems (held-out city generalisation)
configs/scenarios/assam_2026/     # windows.yaml, events.json, critical_labels.json, observed_response.json
scripts/run_replay.py             # CLI replay with provenance summary and stream hash
scripts/build_assam_config.py     # builds configs from geometry + simplified GeoJSON
scripts/fetch_assam_data.py       # multi-source data fetcher with 2 GB budget limit & offline cache
tests/                            # comprehensive acceptance and hygiene test suite
docs/ASSAM_MIGRATION.md           # migration log and inventory
docs/DATA_SOURCES.md              # source documentation and provenance matrix
docs/PLAYBOOK.md                  # project technical playbook
```

## How to run

```powershell
# 1. build configs from real geometry and simplified GeoJSON
python scripts/build_assam_config.py --offline

# 2. run data acquisition / inspect cache
python scripts/fetch_assam_data.py --city upper_assam --window hero_full --all --offline

# 3. run the test suite
python -m pytest tests/ -q

# 4. run a replay for Upper Assam hero scenario (peak window, seed 7)
python scripts/run_replay.py --city upper_assam --seed 7 --hours 72 --rain-window peak

# 5. run a replay for held-out North Bank Assam (zero code changes)
python scripts/run_replay.py --city north_bank_assam --seed 1 --hours 48

# 6. run with fault injection (spike, feed_delay)
python scripts/run_replay.py --city upper_assam --seed 7 --hours 72 --rain-window peak --faults spike,feed_delay

# 7. start the API (WebSocket at ws://localhost:8000/ws/stream?city=upper_assam&seed=1&speed=2)
python -m backend.app.api
```

## API Surface

- `GET /health` -> `{"status": "ok", "service": "72-hour-warning-phase1"}`
- `GET /cities` -> lists available cities: `upper_assam` and `north_bank_assam`
- `GET /city/{city_id}` -> configuration summary, systems, and thresholds
- `WS /ws/stream?city=upper_assam&seed=1&speed=1.0&hours=72&rain_window=peak&anchor=off` -> streams `StreamMessage` JSON observations
- `POST /faults?city=upper_assam&seed=1` with `FaultIn` payload -> injects runtime sensor/feed faults

## Stream Message Contract

```json
{
  "type": "observations",
  "clock_time": "2026-07-21T01:00:00+00:00",
  "observations": [
    {
      "obs_id": "openmeteo:sivasagar:202607210100",
      "source": "rain_openmeteo",
      "source_kind": "real",
      "zone": "sivasagar",
      "system": "river_embankment",
      "value": 14.2,
      "event_time": "2026-07-21T01:00:00+00:00",
      "arrival_time": "2026-07-22T01:00:00+00:00",
      "quality_flags": ["real", "product=openmeteo_era5", "aggregation=centroid"],
      "node_id": "sivasagar:river_embankment"
    }
  ],
  "meta": {
    "city": "upper_assam",
    "seed": 1,
    "released_count": 8,
    "faults": [],
    "anchor_mode": "off"
  }
}
```

Only observations with `arrival_time <= clock_time` are ever released. Future events and hidden ground truth are strictly inaccessible to the stream view.
