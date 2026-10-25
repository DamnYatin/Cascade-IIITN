# Phase 2: The Forecaster — Implementation Log & Progress

## Progress Checklist

- [x] **F0: Step 0 Verification & Branch Setup**
  - Verify starting state, clean test suite (50 passing), migration log completed.
  - Create branch `feat/forecaster` from `feat/assam-migration`.
  - Create `docs/PHASE2.md`.
- [x] **F1: Config, Causal Features, Evidence Ledger & Isolation**
  - `backend/app/forecast/config.py` + `configs/forecast.yaml`.
  - `backend/app/forecast/features.py` (causal feature builder, robust scaling, saturation gain).
  - `backend/app/forecast/ledger.py` (bounded ring-buffer evidence ledger).
  - Causal normalisation tests (T4), import/file isolation tests (T2, T5).
- [x] **F2: Source Trust, Outlier Gating & State Estimator**
  - `backend/app/forecast/trust.py` (Beta reliability, outlier gate, flatline detector, citizen-report aggregation, evidence quality).
  - `backend/app/forecast/estimator.py` (scalar linear-Gaussian filter, late-arrival buffer re-filtering).
  - Adversity & late-arrival tests (T19–T22).
- [x] **F3: Dependency Learner, EdgeBook & Drift Detection**
  - `backend/app/forecast/learner.py` (online sparse lagged RLS with forgetting, weak prior ridge, candidate parent restrictions, EdgeBook).
  - `backend/app/forecast/drift.py` (Page-Hinkley and two-window mean shift, River ADWIN optional adapter).
  - Tests: Label maturity (T3), edge recovery / decoy pairs (T15), drift adaptation (T16), edge flicker hysteresis (T17), prior overridability (T18).
- [x] **F4: Rain Outlook Models**
  - `backend/app/forecast/outlook.py` (`RainOutlook` protocol, `PersistenceDecayOutlook`, `BlockBootstrapOutlook`, `OracleOutlook` with strict diagnostic flag & env gating).
  - Tests: Oracle lockout (T5), outlook causality (T6).
- [x] **F5: Vectorised Monte Carlo Engine & Aggregations**
  - `backend/app/forecast/rollout.py` (NumPy vectorised cascade rollout, `NoiseBank` with `SeedSequence`, common random numbers, intervention hook).
  - `backend/app/forecast/aggregate.py` (`p_by` cumulative vs `p_at` instantaneous, censored time-to-critical quantiles, zone/city cascade aggregation, cascade summary).
  - Tests: NoiseBank reuse (T8), monotone `p_by` (T9), censoring (T10), chain ordering (T11), feedback loop non-divergence (T12), simultaneous cascades (T13), zone cascade rule (T14).
- [x] **F6: Risk-State Mapper, Calibrator & Records**
  - `backend/app/forecast/mapper.py` (probabilistic risk state mapping with hysteresis and dwell time).
  - `backend/app/forecast/calibrate.py` (`Calibrator` protocol + `IdentityCalibrator`).
  - `backend/app/forecast/records.py` (`ForecastSnapshot`, canonical serialisation, provenance mix).
  - Schema additive updates (`PredictionRecord.meta`, `Observation`).
  - Tests: Mapper monotonicity & hysteresis (T24), snapshot round-trip & provenance (T25).
- [ ] **F7: Forecast Engine Wiring & End-to-End Orchestration**
  - `backend/app/forecast/engine.py` (`ForecastEngine` consuming only `StreamView`).
  - Tests: Leakage canary (T1), determinism & golden hash (T7), both configs execution without code changes (T23).
- [ ] **F8: CLI, API, WebSocket, Benchmark & Documentation**
  - `scripts/run_forecast.py` (CLI with replay, multi-horizon tables, top edges, drift events, provenance).
  - `scripts/bench_forecast.py` (performance benchmark).
  - API endpoint `GET /forecast/latest` and `/ws/stream?forecast=1`.
  - `docs/FORECASTER.md` (equations, architecture, real vs simulated, limitations).
  - Optional `backend/app/forecast/prior.py`.
- [ ] **F9: Final Verification, Held-Out Validation & Clean Commits**
  - Run dev seeds {11, 12, 13} and held-out seeds {101, 102} for T15, T16.
  - Run full test suite twice consecutively and once randomly (`pytest-randomly`).
  - Write `tests/PHASE2_TEST_REPORT.md` with measured numbers.
  - Logical commits staged on `feat/forecaster`.
  - Confirm `main` is untouched.

---

## Schema Changes
*(Additive changes only — R7 compliance)*
- `PredictionRecord`: Added optional field `meta: dict[str, Any] = Field(default_factory=dict)` for forecaster metadata (`burn_in`, `calibrated`, `evidence_quality`, `provenance_mix`, `model_version`, `rollouts`, `seed`, `oracle`, `unobserved`, `p_no_critical_within_72h`, `semantics`).

---

## Key Decisions & Deviations
- **Branching:** Created `feat/forecaster` from `feat/assam-migration` (commit `c16eb39`).
- **Baseline Test Suite:** 50 hermetic tests passing in 3.17s (+1 network test deselected).
