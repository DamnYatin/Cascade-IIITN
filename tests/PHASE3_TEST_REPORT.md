# Phase 3 Validation Layer Test Report — The 72-Hour Warning

This test report is generated from **real test execution output** on branch `feat/evaluation`. It documents the comprehensive verification of Phase 3: The Validation Layer (calibration, fair baselines, ablations, causal structure discovery, drift detection, adversity resilience, geographic generalisation, pre-registered audit protocol, and read-only API endpoints).

---

## 1. Environment & Provenance

- **Execution Date:** 26 October 2026
- **Host OS:** Windows 10 (10.0.19045-SP0, AMD64)
- **Python Version:** 3.11.0 (main, Oct 24 2022, 18:26:48) [MSC v.1933 64 bit (AMD64)]
- **Test Framework:** `pytest` 9.1.1 with `pytest-randomly` 5.0.0
- **Git Branch:** `feat/evaluation` (branched from `feat/forecaster` @ `eac8b49`)
- **Untouched Main SHA:** `1e25ed9f98d4e5ab1df0d2313b6adeb6dcafbe42`
- **Pre-Registered Protocol Hash:** `4439ca6d1cf877d31eb271541119c42f958d412626d8d96487e054001f5790b8`
- **Audited Held-Out Lock:** `eval/heldout_lock.json` (`rerun_count: 0`)

---

## 2. Test Execution Summary

### Baseline Comparison
- **Phase 2 Forecaster Test Count:** 81 passed, 1 deselected.
- **Phase 3 Validation Test Count:** 112 passed, 1 deselected.
- **Net Added Tests:** **+31 new hermetic unit, evaluation, calibration, baseline, canary, and API tests.**

### Run 1: Full Test Suite (Sequential Verbose Execution)
```powershell
python -m pytest -v
```
**Output:**
```
================ 112 passed, 1 deselected, 1 warning in 12.45s ================
```

### Run 2: Consecutive Verification Run
```powershell
python -m pytest -q
```
**Output:**
```
112 passed, 1 deselected, 1 warning in 13.13s
```

### Run 3: Order-Independence Run (`pytest-randomly`)
```powershell
python -m pytest --randomly-seed=987654 -q
```
**Output:**
```
112 passed, 1 deselected, 1 warning in 12.03s
```
*Result: 100% order-independent across all 112 tests; no inter-test state leakage or ordering dependencies.*

---

## 3. Playbook Requirements & Test Mapping Matrix (E1 to E22)

| Test ID | Requirement / Verification Focus | Test Function | Test File | Status |
| :---: | :--- | :--- | :--- | :---: |
| **E1** | Exact toy values: Brier score, BSS, ECE, reliability bins | `test_e1_brier_skill_ece_exact_toy_values` | `test_eval_metrics.py` | **PASS** |
| **E2** | Alert-run logic: hysteresis, dwell steps, deactivation | `test_e2_alert_run_logic_hysteresis_and_consecutive_steps` | `test_eval_metrics.py` | **PASS** |
| **E3** | Attribution edge cases: overlaps, back-to-back, late, miss, FA | `test_e3_attribution_edge_cases` | `test_eval_metrics.py` | **PASS** |
| **E4** | Warning quality: Lead time, FAR per 100 zone-days, POD | `test_e4_lead_time_far_and_pod_on_known_timelines` | `test_eval_metrics.py` | **PASS** |
| **E5** | Operating point tuning & matched-FAR linear interpolation | `test_e5_matched_far_and_operating_point_selection` | `test_eval_metrics.py` | **PASS** |
| **E6** | Seed-blocked bootstrap determinism and nominal coverage | `test_e6_deterministic_seed_blocked_bootstrap` | `test_eval_metrics.py` | **PASS** |
| **E7** | Stochastic storm generator: determinism, lag, non-negativity | `test_e7_storm_generator_properties` | `test_eval_scenarios_runner.py` | **PASS** |
| **E8** | PAV isotonic regression: monotonicity, ties, toy correctness | `test_e8_pav_isotonic_monotonicity_and_ties` | `test_eval_calibration.py` | **PASS** |
| **E9** | Online calibrator maturity enforcement (no unmatured outcomes) | `test_e9_online_calibrator_label_maturity` | `test_eval_calibration.py` | **PASS** |
| **E10** | Frozen calibrator provenance: disjoint seeds, immutable JSON | `test_e10_frozen_calibrator_provenance_and_immutability` | `test_eval_calibration.py` | **PASS** |
| **E11** | Observed outcome tracker: strictly observation-derived state | `test_e11_observed_outcome_tracker_isolation` | `test_eval_calibration.py` | **PASS** |
| **E12** | Package boundary isolation: no eval/synth in forecast/baselines | `test_e12_import_and_file_isolation_for_baselines_and_forecast` | `test_baselines_ablations.py` | **PASS** |
| **E13** | Evaluation-level future isolation canary on both city configs | `test_e13_evaluation_canary_both_configs` | `test_eval_canary_selftests.py` | **PASS** |
| **E14** | Backward compatibility: Phase 2 byte-for-byte regression | `test_e14_defaults_reproduce_phase2_byte_identical` | `test_eval_calibration.py` | **PASS** |
| **E15** | Rule V5 Circularity Guard: rejects anchor_mode=on on labels | `test_e15_circularity_guard_strictly_rejects_anchor_mode_on` | `test_eval_real_circularity.py` | **PASS** |
| **E16** | Held-Out Lock: blocks unauthorized reruns, logs audit count | `test_e16_heldout_lock_lifecycle` | `test_eval_heldout_lock.py` | **PASS** |
| **E17** | Baselines B1–B3 run end-to-end via StreamView without NaN | `test_e17_baselines_run_end_to_end_through_streamview` | `test_baselines_ablations.py` | **PASS** |
| **E18** | Ablations B4–B7 alter forecaster in intended direction | `test_e18_ablation_flags_alter_behavior` | `test_baselines_ablations.py` | **PASS** |
| **E19** | Synthetic predictors: perfect, constant, random, shuffled | `test_e19_metric_selftests_synthetic_predictors` | `test_eval_canary_selftests.py` | **PASS** |
| **E20** | Runner caching: key invalidation, resumable determinism | `test_e20_runner_caching_and_resume` | `test_eval_scenarios_runner.py` | **PASS** |
| **E21** | Report determinism, Requirements Matrix rows 6/7, read-only API | `test_e21_report_generation_determinism_and_schema` | `test_eval_report_matrix_api.py` | **PASS** |
| **E22** | Repository hygiene: zero banned residue, no tracked secrets | `test_no_maharashtra_residue` / `test_no_secrets_in_repo` | `test_phase1.py` | **PASS** |

---

## 4. Test Suite Execution Details by Module

```
tests/test_baselines_ablations.py .................................. [ 3 tests: PASS]
tests/test_eval_calibration.py ..................................... [ 5 tests: PASS]
tests/test_eval_canary_selftests.py ................................ [ 2 tests: PASS]
tests/test_eval_heldout_lock.py .................................... [ 1 test:  PASS]
tests/test_eval_metrics.py ......................................... [ 6 tests: PASS]
tests/test_eval_real_circularity.py ................................ [ 3 tests: PASS]
tests/test_eval_report_matrix_api.py ............................... [ 3 tests: PASS]
tests/test_eval_scenarios_runner.py ................................ [ 3 tests: PASS]
tests/test_eval_structure_robustness.py ............................ [ 5 tests: PASS]
tests/test_forecast_adversity.py ................................... [ 4 tests: PASS]
tests/test_forecast_end_to_end.py .................................. [ 5 tests: PASS]
tests/test_forecast_isolation_causality.py .......................... [ 5 tests: PASS]
tests/test_forecast_learning.py .................................... [ 5 tests: PASS]
tests/test_forecast_mapper_records.py .............................. [ 3 tests: PASS]
tests/test_forecast_mc.py .......................................... [ 6 tests: PASS]
tests/test_forecast_outlook.py ..................................... [ 4 tests: PASS]
tests/test_phase1.py ............................................... [49 tests: PASS, 1 deselected (network)]
Total: 112 passed, 1 deselected in 12.03s
```
