# Phase 3: The Validation Layer — Implementation Log & Progress

## Progress Checklist

- [x] **G0: Step 0 Verification, Branch Setup & Measured Costs**
  - Verified starting state: 81 passing tests (+1 deselected).
  - Created and checked out branch `feat/evaluation` from `feat/forecaster` tip (`eac8b49`).
  - Benchmarked forecaster rollout engine: 9.18M node-steps/sec (0.141s for 60 nodes × 72h × 300 rollouts).
  - Measured replay runtime: 23.49s for 72-hour lead window at 3h cadence.
  - Created `docs/PHASE3.md`.
- [x] **G1: Yardstick Core (Events, Alerts, Metrics & Bootstrap)**
  - `backend/app/eval/events.py` (true episode extraction at node, zone-cascade, and city levels).
  - `backend/app/eval/alerts.py` (alert-run hysteresis and event attribution).
  - `backend/app/eval/metrics.py` (Brier, BSS, ECE, reliability bins, lead time, FAR, POD, TTC error/coverage, bootstrap).
  - `backend/app/eval/sweeps.py` (threshold evaluation, operating point selection, matched FAR interpolation).
  - Unit tests E1 to E6 in `tests/test_eval_metrics.py` (all 6 passed).
- [x] **G2: Scenarios, Protocol & Parallel Cached Runner**
  - `backend/app/eval/storm_rain.py` (spatially correlated lagged storm generator).
  - `backend/app/eval/scenarios.py` (scenario family builders: F-real, F-storm, F-quiet, F-drift, F-faulted, F-heldout-city).
  - `backend/app/eval/protocol.py` (seed sets, protocol specification, hash computation, held-out lock).
  - `backend/app/eval/runner.py` (parallel execution, disk cache keyed by run signature, resume support).
  - Pre-registered protocol document: `docs/EVAL_PROTOCOL.md`.
  - Unit tests E7 and E20 in `tests/test_eval_scenarios_runner.py` (all passed).
- [x] **G3: Calibration & Observed Outcome Tracker**
  - `backend/app/forecast/outcomes.py` (`ObservedOutcomeTracker` without ground truth, enforcing label maturity).
  - `backend/app/forecast/calibrate.py` (`FrozenIsotonicCalibrator` and `OnlineRollingCalibrator` with custom PAV algorithm).
  - Wrote `scripts/eval_calibrate.py` and fitted `eval/calibrator_frozen.json` on calib-fit seeds {21, 22, 23, 24}.
  - Unit tests E8 to E11, E14 in `tests/test_eval_calibration.py` (all passed).
- [x] **G4: Baselines & Ablations**
  - `backend/app/baselines/isolated.py` (B1 isolated per-node monitoring).
  - `backend/app/baselines/rainrule.py` (B2 rain-threshold rule and B3 climatology/persistence).
  - `backend/app/baselines/ablations.py` (B4 to B7 adapters/flags).
  - Added additive `ablation:` section in `configs/forecast.yaml` and `ForecastConfig`.
  - Wired ablations into `ForecastEngine`.
  - Unit tests E12, E17, E18 in `tests/test_baselines_ablations.py` (all passed).
- [x] **G5: Dev-Seed Runs & Operating Point Tuning**
  - Ran dev seeds {11, 12, 13} across forecaster, B1–B3 baselines, and B4–B7 ablations.
  - `backend/app/eval/sweeps.py` (threshold sweeps, matched-FAR comparison, operating point selection).
  - `scripts/eval_tune.py` -> generated `configs/forecast_tuned.yaml` with cryptographic provenance.
  - Forecaster selected tau=0.15, k=1, tau_low=0.15: POD=1.000, FAR=0.00, Lead=19.0h (beats B1 Isolated by +3.5h).
  - Tests E13 (future-isolation canary on both configs) and E19 (diagnostic predictors: perfect, constant 0.5, random, shuffled) in `tests/test_eval_canary_selftests.py` (all passed).
- [x] **G6: Structure, Drift & Robustness Analyses**
  - `backend/app/eval/structure.py` (edge precision 0.900, recall 0.098, F1 0.176, decoy pair FPR 0.000, mean lag error 0.5h).
  - `backend/app/eval/structure.py` (drift detection rate 3/3 on F-drift, mean delay 15.0h, pre-change false drift alerts 0).
  - `backend/app/eval/robustness.py` (fault deltas, source trust ordering: faulty spike sensor correctly downweighted to Rank 1/4 lowest trust, evidence quality vs error binning).
  - `scripts/eval_analyses.py` executed on DEV seeds {11, 12, 13} and outputs saved to `eval/analyses_dev.json`.
  - Unit tests in `tests/test_eval_structure_robustness.py` (5/5 passed).
- [x] **G7: Real-Event Check (Assam 2026)**
  - `backend/app/eval/realcheck.py` and `scripts/eval_real.py`.
  - Coarse interval lead-time evaluation with label grades, response milestone rank correlation, negative controls.
  - Enforced Rule V5 circularity guard: strictly rejects `anchor_mode=on` when evaluating against historical response/labels.
  - Evaluated on real Assam July 2026 rainfall/soil moisture series (`F-real`, `anchor_mode=off`): 8/8 label hits (POD 1.0), honest provenance disclosing simulated downstream systems.
  - Test E15 in `tests/test_eval_real_circularity.py` (3/3 passed). Output saved to `eval/real_event_summary.json`.
- [ ] **G8: Protocol Freeze & Single Held-Out Execution**
  - Verify `docs/EVAL_PROTOCOL.md` and config commits.
  - Write `eval/heldout_lock.json` with code/config/protocol SHA-256 hashes.
  - Run held-out evaluation once for seeds {101..105} on upper_assam and north_bank_assam.
  - Test E16 (lock enforcement and rerun logging).
- [ ] **G9: Reporting, Visuals, Matrix & API**
  - `backend/app/eval/report.py` and `scripts/eval_report.py`.
  - Generate `eval/summary.json`, `eval/tables/*.csv`, `eval/figures/*` (SVG/PNG), `frontend/public/eval/*.json`.
  - Write `docs/EVALUATION.md` and `docs/REQUIREMENTS_MATRIX.md`.
  - Add read-only API endpoints (`/eval/summary`, `/eval/reliability`, `/eval/curves`, `/eval/matrix`).
  - Test E21.
- [ ] **G10: Final Verification & Clean History**
  - Run full test suite twice consecutively and once randomly (`pytest-randomly`).
  - Update `tests/PHASE3_TEST_REPORT.md` from live execution outputs.
  - Verify clean git status, untouched main, hermeticity (no network).

---

## Decisions
1. **Branching:** Created `feat/evaluation` from the tip of `feat/forecaster` (`eac8b49`). Main and feat/forecaster branches will remain untouched.
2. **Package Boundaries:** Ground truth and label files restricted strictly to `backend/app/eval/`, `scripts/eval_*`, and `tests/`. `backend/app/forecast/` and `backend/app/baselines/` only consume `StreamView`.
3. **Calibrator Architecture:** Built-in Pool Adjacent Violators (PAV) algorithm for isotonic regression so no heavy external dependencies are required during inference/testing.
4. **Data Cache:** Evaluated predictions cached in `eval/cache/` keyed by `(config_hash, city, scenario_family, seed, faults, window, rollouts, cadence, code_version)`.

---

## Schema & Config Changes
*(Additive only)*
- `configs/forecast.yaml`: Added `ablation:` section (defaulting to all off, ensuring backward compatibility).
- `configs/forecast_tuned.yaml`: Pre-registered tuned parameters from dev-set calibration/sweeps.

---

## Measured Costs
- **Rollout Monte Carlo Benchmark (`scripts/bench_forecast.py`):**
  - 60 nodes × 72 horizons × 300 rollouts = 1,296,000 node-steps.
  - Elapsed: 0.141 seconds (Throughput: 9,187,391 node-steps/sec).
- **End-to-End Stream Replay (`scripts/run_forecast.py`):**
  - 72-hour `lead` window at 3h forecast cadence (24 full forecaster steps):
  - Elapsed: 23.49 seconds (~0.98s per step including streaming ingestion, Kalman filtering, RLS learning, EdgeBook updates, and Monte Carlo rollouts).
- **Sweep Sizing Plan:**
  - With 4 CPU worker processes, a 72-hour scenario replay takes ~6-8 seconds.
  - Dev runs: 3 seeds × 3 families = 9 runs (~1.5 minutes).
  - Calib-fit runs: 4 seeds × 1 family = 4 runs (~40 seconds).
  - Held-out runs: 5 seeds × 3 families + 1 held-out city = 16 runs (~3 minutes).
  - Total compute time for all families across all seeds is well under 15 minutes, well within the 60-90 minute budget.

---

## Deviations
- None yet.
