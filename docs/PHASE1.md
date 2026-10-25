# The 72-Hour Warning — Phase 1

**Phase 1 goal (hours 0–5):** a replayable, deterministic, leakage-proof stream of
messy observations for a city, generated from a hidden ground truth that the future
model can never see. No forecasting, learning, calibration, UI, or interventions in
this phase — those come later and code against the frozen schemas here.

## Repo layout

```
backend/app/schemas.py            # frozen Pydantic v2 models
backend/app/city_config.py        # YAML -> validated CityConfig
backend/app/synth/__init__.py     # ground-truth namespace (model code must not import)
backend/app/synth/planted_graph.py# hidden planted dependency graph
backend/app/synth/generator.py    # synthetic city generator + GroundTruth
backend/app/synth/ground_truth.py # GroundTruth container (latent stress, episodes)
backend/app/replay/clock.py       # ReplayClock (forward-only simulated time)
backend/app/replay/stream.py      # ReplayStream + StreamView (arrival-time gating)
backend/app/replay/faults.py      # seeded fault injector
backend/app/adapters/imd_rain.py  # IMD daily -> hourly rainfall disaggregation
backend/app/api.py                # FastAPI app + WebSocket stream
configs/mumbai.yaml               # ~10 zones x 6 systems
configs/heldout_city.yaml         # 6 zones x 6 systems (generalization check)
scripts/run_replay.py             # CLI replay
scripts/generate_rain_fixture.py  # builds data/processed/maharashtra_climate.csv fixture
tests/                            # 20 acceptance tests
docs/PHASE1.md                    # this file
```

## How to run

```powershell
# 1. (once) build the fixture rainfall CSV used by the adapter presets
python scripts/generate_rain_fixture.py

# 2. run the acceptance suite (must be green)
python -m pytest tests/ -q

# 3. run a replay for Mumbai
python scripts/run_replay.py --city mumbai --seed 1 --hours 168 --family logistic_hazard --faults spike,dropout

# 4. run a replay for the held-out city (zero code changes)
python scripts/run_replay.py --city heldout --seed 5 --hours 168 --family threshold_nonlinear --faults citizen_spam,feed_delay

# 5. drive the mumbai generator with real rain (Mumbai 2019 preset)
python scripts/run_replay.py --city mumbai --seed 1 --hours 48 --rain-window mumbai_2019 --faults none

# 6. start the API (WebSocket at ws://localhost:8000/ws/stream?city=mumbai&seed=1&speed=2)
python -m backend.app.api
```

Endpoints:
- `GET /health`
- `GET /cities` — available city configs
- `GET /city/{city_id}` — config summary
- `WS /ws/stream?city=...&seed=...&speed=...&hours=...&rain_window=...` — streams
  `StreamMessage` JSON as the clock advances
- `POST /faults?city=...&seed=...` with a `FaultIn` body — toggle a fault at runtime

## Frozen schemas

Defined in `backend/app/schemas.py` (all Pydantic v2 `frozen=True` models):

- `Zone(id, name, centroid_lat, centroid_lon, neighbours[])`
- `SystemSpec(id, name?, capacity?, critical_threshold?, unit)`
- `NodeId = "zone_id:system_id"` (never spliced)
- `StreamSpec(source, system, cadence_hours, typical_delay_hours, noise_level,
  source_kind, false_report_rate?)`
- `CityConfig(city_id, zones[], systems[], streams[], domain_prior_edges[],
  start_time_utc, critical_stress_threshold)` — prior edges are weak, NOT truth
- `Observation(obs_id, source, source_kind, zone, system, value, event_time,
  arrival_time, quality_flags[], node_id)` — arrival_time >= event_time enforced
- `Edge(u: NodeId, v: NodeId, lag_hours, weight, confidence, last_updated)`
- `RiskState` enum: NORMAL / WATCH / HIGH_RISK / CRITICAL
- `PredictionRecord` — defined, unused in Phase 1
- `StreamMessage(type, clock_time, observations[], meta)` — the exact WebSocket message

Every timestamp is timezone-aware UTC; naive datetimes are rejected.

## Stream message format (WebSocket)

```json
{
  "type": "observations",
  "clock_time": "2019-06-01T00:00:00+00:00",
  "observations": [ { ... Observation ... } ],
  "meta": { "city": "mumbai", "seed": 1, "released_count": 12, "faults": [] }
}
```

Only observations with `arrival_time <= clock_time` are released, and each is
released exactly once. `StreamView` is the only object model code may receive; it
cannot return data whose `arrival_time` is in the future relative to the clock.

## Leakage isolation

- Ground truth lives in `backend.app.synth.*` and is **never** placed on the stream.
- `replay/`, `city_config.py`, and `schemas.py` do not import `synth` (enforced by
  `tests/test_phase1.py::test_import_isolation_no_synth_in_model_packages`).
- The replay clock only moves forward (`seek_forward` rejects earlier targets).
- All randomness uses isolated `numpy.random.default_rng(seed)`; the global RNG is
  never touched, so the same seed yields byte-identical output.
- `data/`, `.env`, and generated artifacts are gitignored (no secrets in the repo).

## Acceptance tests (20, all must pass)

| # | Test | What it proves |
|---|------|----------------|
| 1 | determinism (same / different seed) | byte-identical streams + ground truth per seed |
| 2 | arrival ordering / gating / no-repeat | `arrival_time <= clock`, sorted, released once, some out of event order |
| 3 | leakage canary | replacing post-T data with garbage leaves pre-T releases bit-identical |
| 4 | import isolation | model packages don't import synth ground truth |
| 5 | disaggregation | hourly totals conserve each daily total, deterministic per seed |
| 6 | planted graph | negative edge, feedback loop, cross-zone edge, time-windowed edge, decoy pairs |
| 7 | fault injector | each fault changes the stream and is reproducible by seed |
| 8 | config | both cities validate; heldout runs end-to-end; invalid config fails clearly |
| 9 | UTC-aware datetimes | every timestamp is timezone-aware UTC |

## Known limitations / out of scope for Phase 1

- No state estimator, dependency learner, forecaster, calibration, risk-state
  mapper, explainer, or intervention planner (Phase 2+).
- No frontend (React UI deferred per the playbook).
- The rainfall CSV shipped under `data/processed/` is a **fixture** built by
  `scripts/generate_rain_fixture.py` that mirrors the documented IMD structure and
  extreme-event magnitudes (Mumbai 269 mm on 2019-06-29; Thane 360 mm / Mumbai 281
  mm in July 2021). Replace it with the real IMD export before any public demo.
- The `mumbai_2019` / `konkan_2021` presets were verified against the fixture CSV
  (all three extremes MATCH).
- `api.py` keeps sessions in an in-memory dict (a real deployment needs a proper
  store); sessions keyed by `{city_id}:{seed}`.
