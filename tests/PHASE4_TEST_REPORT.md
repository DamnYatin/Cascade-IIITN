# Phase 4 Test Suite Verification & Audit Report

**Phase:** 4 (Causal Explanations & Constrained Interventions)  
**Branch:** `feat/explain-intervene`  
**Execution Timestamp:** `2026-10-26T05:01:08Z`  
**Platform:** Windows 11 / Python 3.11.0 / pytest 9.1.1 / pytest-randomly 5.0.0  

---

## 1. Test Suite Summary & Delta

| Metric | Phase 3 Tip (`7ed6ebb`) | Phase 4 Tip (`feat/explain-intervene`) | Delta |
| :--- | :---: | :---: | :---: |
| **Total Test Modules** | 16 files | 25 files | +9 modules |
| **Passing Tests** | 112 | **150** | **+38 tests** |
| **Deselected Tests** | 1 (Slow 72h continuous test) | 1 (Unchanged slow test) | 0 |
| **Failed / Errored** | 0 | 0 | 0 |
| **Mean Suite Duration** | ~14.5s | ~117.0s (includes solver & bundle sweeps) | +102.5s |
| **Randomized Seed Order** | Passed (`--randomly-seed=20261026`) | Passed | Clean |

---

## 2. Phase 4 Test Additions Breakdown (+38 Tests)

### 2.1 Trace Instrumentation & Failure Chains (+8 tests)
- `tests/test_forecast_trigger_trace.py` (2 tests):
  - `test_p1_trigger_trace_identity_when_disabled_and_enabled`: Proves bit-for-bit unperturbed forecast trajectory identity whether trace recording is on or off (zero RNG consumption).
  - `test_p1_trigger_trace_link_probabilities_and_lag`: Validates empirical link usage probability $P(u \mid v)$ and timing lag quantiles ($p_{10}, p_{50}, p_{90}$).
- `tests/test_explain_chains.py` (6 tests):
  - `test_p2_hand_built_chain_extraction_order_and_etas`: Verifies reverse stage traversal, topological ordering, and ETA computations on hand-crafted synthetic DAGs ($A \to B \to C$).
  - `test_p3_feedback_loop_detection_and_amplification`: Verifies simple cycle detection ($B \leftrightarrow C$), positive amplification factor, and weakest-link identification.
  - `test_p4_simultaneous_cascades_interaction`: Tests converging multi-root cascades ($R_1 \to M, R_2 \to M$), asserting positive interaction delta vs independent union.
  - `test_p5_censoring_and_conditional_quantiles`: Verifies right-censoring at 72h for non-crossing rollouts.
  - `test_counterfactual_link_removal`: Paired link cutting counterfactuals under CRN.
  - `test_chain_branching_floor_pruning`: Pruning of candidate edges below configurable usage threshold.

### 2.2 Attribution, Evidence Receipts, Confidence & Hedging (+6 tests)
- `tests/test_explain_attribution_text.py` (6 tests):
  - `test_p6_additive_attribution_linear_regime_and_residual`: Proves attribution sums to $\Delta \text{Risk}$ in linear regime and explicitly reports non-linear residual otherwise.
  - `test_p7_paired_rerollout_attribution_determinism`: Validates paired CRN re-rollouts and bootstrap 95% CIs.
  - `test_p8_evidence_receipt_time_leakage_and_audit`: Strictly verifies that no observation in an evidence receipt has arrival time $> t_{\text{issued}}$.
  - `test_p9_confidence_formula_and_graceful_abstention`: Verifies confidence degradation under faulty sensors and explicit abstentions on unidentifiable collinear drivers.
  - `test_p10_hedged_text_banned_certainty_words_and_numerical_fidelity`: Lints explanation text against banned certainty words (`proves`, `causes`, `certainly`).
  - `test_p11_bounded_deterministic_risk_change_log`: Validates FIFO risk change log capacity, deduplication, and determinism.

### 2.3 Action Catalog, Schemas & Package Isolation (+7 tests)
- `tests/test_intervene_config_schemas.py` (6 tests):
  - `test_p12_interventions_config_schema_validation`: Validates `configs/interventions.yaml` across all 10 action categories against Pydantic schemas.
  - `test_p12_action_filtering_by_city_topology`: Tests pruning of unsupported systems (e.g. `mobile_comms_tower` in `north_bank_assam`).
  - `test_p12_assumptions_register_provenance_audit`: Confirms all parameters carry provenance tags (`grounded_category`, `expert_estimate_needed`, `assumed`).
  - `test_p12_hard_budget_constraints_enforcement`: Tests resource limit enforcement and zero-budget handling.
  - `test_p12_action_parameter_distributions`: Tests triangular, beta, and constant parameter draws.
  - `test_p12_exclusivity_groups`: Enforces mutual exclusivity constraints.
- `tests/test_explain_intervene_isolation.py` (1 test):
  - `test_p21_import_and_file_isolation`: Proves that `backend/app/explain/` and `backend/app/intervene/` have zero imports or file reads of `eval/`, `synth/`, or ground truth.

### 2.4 Patches, Paired Evaluation, Solvers & Timing (+8 tests)
- `tests/test_intervene_eval_patches.py` (4 tests):
  - `test_p13_step_patch_execution_in_rollout`: Tests dynamic parameter patches (`ADD_BIAS`, `CAP_STRESS`, `ADD_EDGE`, `EXPOSURE_CHANGE`).
  - `test_p14_do_nothing_plan_reproduces_baseline_bit_for_bit`: Asserts byte-identical rollouts when evaluating do-nothing plan vs baseline.
  - `test_p15_side_effects_accounting_distinction`: Proves explicit vs propagated side-effect accounting.
  - `test_p20_plan_evaluation_caching_and_determinism`: Tests memory caching keyed by plan hash and noise key.
- `tests/test_intervene_solver_robust_timing.py` (4 tests):
  - `test_p16_solver_budget_and_exclusivity_enforcement`: Validates greedy and beam solvers under adversarial constraints.
  - `test_p17_solver_optimality_gap_vs_brute_force`: Asserts that greedy solver matches brute force within 5% on small instances.
  - `test_p18_robustness_sensitivity_and_model_uncertainty`: Tests parameter scaling (0.5x..1.5x) and optimistic effect flags.
  - `test_p19_value_of_lead_time_monotonic_decay`: Asserts that intervention benefit decays monotonically with commitment delay.

### 2.5 API Endpoints, Offline Demo Bundle & Schemas (+5 tests)
- `tests/test_api_cli_bundle_contracts.py` (5 tests):
  - `test_p22_future_leakage_canary_explain_and_intervene`: Canary test verifying that corrupting observation stream after time $T$ leaves all explanations and plans issued at $\le T$ byte-identical across both city configurations.
  - `test_p23_api_explanation_and_intervention_endpoints`: Validates `/explain/*` and `/intervene/*` endpoints and default-off behavior.
  - `test_p25_json_schema_validation_of_api_endpoints`: Asserts 100% schema compliance for API outputs.
  - `test_p26_demo_bundle_integrity_and_determinism`: Verifies that offline bundle (`frontend/public/phase4/`, 242KB across 6 files) matches sha256 manifest.
  - `test_p27_schema_export_and_contract_md`: Confirms that 14 exported schemas match `docs/API_CONTRACT.md`.

### 2.6 Truth Simulator, Evaluation & Lock Integrity (+4 tests)
- `tests/test_eval_phase4.py` (4 tests):
  - `test_p24_generator_patch_hook_byte_identical_default`: Proves unpatched generator output remains bit-for-bit identical with the patch hook added.
  - `test_p28_truth_sim_unpatched_identity_and_patch_effects`: Verifies that `truth_sim.py` reproduces unperturbed generator dynamics and executes identical patch semantics.
  - `test_p29_explanation_metrics_and_regret_sanity_predictors`: Tests explanation metrics on known DAGs and verifies planner regret sanity predictors (oracle regret = 0, do-nothing regret = max benefit).
  - `test_p30_phase4_heldout_lock_behavior`: Verifies protocol hash verification, audit locking, and rerun protection.

---

## 3. Consecutive Execution Verification

The entire hermetic test suite was executed three times consecutively:

### Run 1: Standard Consecutive Execution
- **Command:** `python -m pytest tests/`
- **Result:** **150 passed, 1 deselected** in 116.86s
- **Status:** PASS

### Run 2: Second Consecutive Execution
- **Command:** `python -m pytest tests/`
- **Result:** **150 passed, 1 deselected** in 116.54s
- **Status:** PASS

### Run 3: Randomized Order Execution
- **Command:** `python -m pytest tests/ --randomly-seed=20261026`
- **Result:** **150 passed, 1 deselected** in 117.41s
- **Status:** PASS

---

## 4. Final Audit Checklist

- [x] All 38 new Phase 4 tests passing hermetically without network access.
- [x] Zero regressions across all 112 Phase 1–3 tests.
- [x] Zero banned certainty words in explanation outputs.
- [x] Future leakage canary passing on both `upper_assam` and `north_bank_assam`.
- [x] Offline demo bundle loaded and verified against canonical SHA256 manifest.
- [x] Audit lock `eval/heldout_lock_p4.json` verified with `rerun_count: 0`.
