# Phase 4: Causal Explanations + Constrained Interventions — Implementation Log & Progress

## Progress Checklist

- [x] **H0: Step 0 Verification, Branch Setup & Measured Costs**
  - Verified starting state: 112 passing tests (+1 deselected).
  - Verified git clean working tree and established branch `feat/explain-intervene` from Phase 3 tip (`7ed6ebb`).
  - Saved prompt to `docs/PHASE4_PROMPT.md` and verified zero banned-term residue.
  - Verified `eval/heldout_lock.json` present and untouched (`rerun_count: 0`).
  - Measured compute costs:
    - N=300 rollouts (60 nodes × 72h = 1,296,000 node-steps): **0.209s** (~6.21M node-steps/sec).
    - Single forecast step (Kalman state estimation + RLS learning + N=300 rollouts): **~0.41s**.
    - Full 72h replay window at 3h cadence (24 forecast steps): **~24.5s** (~1.02s per cycle).
- [x] **H1: Additive Schemas, Interventions Config & Assumptions Register**
  - Additive schemas in `backend/app/explain/records.py` (`ExplanationRecord`, `ChainLink`, `DriverRecord`, `EvidenceReceipt`, `CascadeLoop`, `ConcurrentCluster`) and `backend/app/intervene/records.py` (`Action`, `ActionInstance`, `EffectPatch`, `InterventionPlan`, `PlanOutcome`, `SideEffect`, `ResourceUse`, `Assumption`).
  - Config `configs/interventions.yaml` with action catalog across all 10 placeholder categories with honest provenance classifications.
  - Implemented `backend/app/intervene/actions.py`: schema loader, strict validation, `filter_actions_for_city` (skips unsupported systems with logged warnings, e.g. `comms` in `north_bank_assam`), and `build_assumptions_register`.
  - Authored `docs/INTERVENTIONS.md` documenting catalog, Assumptions Register, multi-objective net benefit formulation, and tuning instructions.
  - Verified tests P12, P21, and schema determinism in `tests/test_intervene_config_schemas.py` and `tests/test_explain_intervene_isolation.py` (all passed).
- [x] **H2: Forecast Trigger Trace Instrumentation**
  - Additive `TriggerTrace` recorder in `backend/app/forecast/trace.py`: compact ndarray storage for crossing steps, dominant contributor terms, dominant parent nodes, and values.
  - Query methods: `get_link_usage_probability` ($P(u \text{ dominant } \mid v \text{ crossed})$) and `get_link_timing_stats` (p10, p50, p90, mean lag).
  - Wired into `backend/app/forecast/rollout.py` behind `enable_trace` flag (default False).
  - Verified test P1 in `tests/test_forecast_trigger_trace.py`: bit-for-bit trajectory identity between trace on and trace off (zero RNG consumption).
- [x] **H3: Failure Chains Engine**
  - Implemented `backend/app/explain/chains.py`:
    - `build_trigger_graph`: directed networkx graph with $p_{\text{link}} = P(u \text{ dominant } \mid v \text{ crossed})$ and timing stats.
    - `extract_failure_chain_tree`: hierarchical backwards stage traversal with branching floor and conditional / censored unconditional ETAs.
    - `detect_feedback_loops`: simple cycle detection, weakest-link identification, and paired CRN amplification estimation.
    - `detect_simultaneous_cascades`: converging multi-root interactions with independent union comparison and bootstrap CIs.
    - `evaluate_link_removal_counterfactual`: paired link cutting counterfactuals.
  - Verified tests P2 to P5 in `tests/test_explain_chains.py` (all 6 passed).
- [x] **H4: Risk-Change Attribution, Evidence Receipts, Confidence & Hedged Text**
  - `backend/app/explain/attribution.py`: Method A (additive decomposition with non-linear residual reporting) + Method B (paired re-rollouts under CRN with bootstrap 95% CIs and rank stability).
  - `backend/app/explain/receipts.py`: observation IDs strictly <= issued_at, source classification, trust scores, EdgeBook history, and transparent simulation disclosures.
  - `backend/app/explain/confidence.py`: multi-criteria confidence formula, graceful degradation under faults, and unidentifiable driver abstentions.
  - `backend/app/explain/text.py`: deterministic templating, approved hedged phrasing rules, banned certainty word filter, and numerical fidelity lints.
  - `backend/app/explain/log.py`: bounded deterministic FIFO risk-change log.
  - Verified tests P6 to P11 in `tests/test_explain_attribution_text.py` (all 6 passed).
- [x] **H5: Intervention Engine (Patches & Paired Evaluation)**
  - Implemented `backend/app/intervene/patches.py`: `ScheduledPatch`, `compile_scheduled_patches`, `draw_patch_rollout_values` with CRN distributions (constant, triangular, beta), and `apply_step_patches`.
  - Wired dynamic patches into `cascade_rollout` step loop in `backend/app/forecast/rollout.py` (default None preserves byte-for-byte baseline output).
  - Implemented `backend/app/intervene/evaluate.py`: `evaluate_plan` (paired outcomes under CRN, delta cascade-critical zone-hours, tail CVaR, broken chain links, side-effects accounting distinguishing explicit vs propagated, and LRU memory caching).
  - Verified tests P13, P14, P15, and P20 in `tests/test_intervene_eval_patches.py` (all 4 passed).
- [x] **H6: Solvers, Robustness & Value of Lead Time**
  - Implemented `backend/app/intervene/solver.py`: `is_feasible`, `compute_resource_use`, `generate_candidate_pool`, and `solve_interventions` (lazy greedy, beam search, brute force; multi-tier rollout screening; hard constraint enforcement; adversarial zero-budget handling).
  - Implemented `backend/app/intervene/robust.py`: `evaluate_effect_sensitivity` (scaling factors 0.5x..1.5x with optimism detection) and `evaluate_model_uncertainty` (edge covariance perturbation).
  - Implemented `backend/app/intervene/timing.py`: `evaluate_value_of_lead_time` (delays 0h..24h, cost of waiting per hour, and latest effective start offset).
  - Verified tests P16 to P19 in `tests/test_intervene_solver_robust_timing.py` (all 4 passed).
- [x] **H7: API Endpoints, CLI, Optional WebSocket & Demo Bundle**
  - Read-only explanation & intervention endpoints in `backend/app/api.py` (`/explain/latest`, `/explain/changes`, `/explain/link`, `/intervene/actions`, `/intervene/plan`, `/intervene/evaluate`).
  - CLIs: `scripts/explain.py` and `scripts/plan_interventions.py` with honesty disclosures.
  - Optional WebSocket flags (`explain=1`, `plan=1`) streamed cleanly in replay stream.
  - `scripts/build_demo_bundle.py` generating deterministic, offline JSON bundle in `frontend/public/phase4/` (242KB across 6 files) with UTF-8 byte hashes matching on Windows/Linux.
  - `scripts/export_schemas.py` exporting 14 canonical JSON Schemas to `frontend/public/schemas/` & generated `docs/API_CONTRACT.md`.
  - Verified tests P21 to P23, P25 to P27 in `tests/test_api_cli_bundle_contracts.py` (all 5 passed).
- [x] **H8: Phase 4 Evaluation Protocol, Truth Simulator & Benchmark Runs**
  - Pre-registered `docs/EVAL_PROTOCOL_P4.md` and committed in commit `ec5c1ee` before any held-out evaluation was run.
  - Implemented `backend/app/eval/truth_sim.py` (counterfactual latent generator re-simulation with identical CRN), `backend/app/eval/explain_eval.py`, and `backend/app/eval/plan_eval.py`.
  - Added generator patch hook with proven bit-for-bit unpatched identity (P24).
  - Verified unit tests P24, P28, P29, P30 in `tests/test_eval_phase4.py` (all 4 passed).
  - Dev benchmark on seeds {31, 32, 33} completed and saved to `eval/dev_results_p4.json`.
  - Single held-out run executed on seeds {201, 202, 203, 204, 205} and locked in `eval/heldout_lock_p4.json` (`rerun_count: 0`).
  - Cross-topology transfer on `north_bank_assam` (seed 201) completed and recorded.
- [x] **H9: Phase 4 Reporting & Requirements Matrix Update**
  - Generated `docs/EVALUATION_P4.md` from cached held-out results with 95% bootstrap CIs, paired baseline tables, and explicit caveats.
  - Updated `docs/REQUIREMENTS_MATRIX.md` marking Requirements 6 & 7 as completed with real evidence.
  - Authored `docs/EXPLAINER.md` (method, equations, attribution additivity, confidence formula, abstention rules, hedging rules, and text lints).
  - Authored `docs/INTERVENTIONS.md` (action catalog, Assumptions Register with provenance, multi-objective net benefit formulation, and tuning instructions).
- [x] **H10: Final Verification & Clean Repository Discipline**
  - Ran full test suite twice consecutively (150 passed, 1 deselected) and once with randomized order (`--randomly-seed=20261026`, 150 passed, 1 deselected).
  - Authored `tests/PHASE4_TEST_REPORT.md` from actual test execution runs (+38 new tests, 150 total).
  - Verified git status clean on `feat/explain-intervene`, main untouched, zero untracked garbage.

---

## Decisions

1. **Branching:** Work is conducted on branch `feat/explain-intervene` branched from commit `7ed6ebb` (the tip of Phase 3 / `feat/evaluation`).
2. **Package Boundaries:**
   - `backend/app/explain/` and `backend/app/intervene/` are FORECAST-SIDE: they consume `ForecastModel`, `EdgeBook`, `NoiseBank`, `EvidenceLedger`, `StateEstimator`, snapshots, and configurations. They never import ground truth, planted graph, generator internals, scenario labels, or `backend/app/eval/`.
   - Evaluation routines comparing against ground truth or latent simulation live in `backend/app/eval/`, `scripts/`, and `tests/`.
3. **Common Random Numbers (CRN):**
   - Paired counterfactual comparisons reuse the exact same `NoiseBank` instances as the baseline unperturbed rollouts. The "do-nothing" intervention plan yields byte-identical output to the baseline forecaster.
4. **Honest Language & Phrasing:**
   - Model-based dependencies are strictly referred to as "learned dependencies" or "causal candidates", never "proven causes".
   - Counterfactual effects are labeled "estimated under the learned model with assumed action effects".
   - Simulated streams are explicitly flagged in all disclosures and receipts.
5. **Pre-Registration:**
   - Fresh seeds for Phase 4: Dev {31, 32, 33}, Held-out {201, 202, 203, 204, 205}.
   - `docs/EVAL_PROTOCOL_P4.md` will be committed prior to running held-out evaluation.

---

## Schema & Config Changes
*(All additions are strictly additive)*

- To be added in H1:
  - `configs/interventions.yaml`: action catalog, costs, delays, durations, parameter patches, side-effects, and provenance markers.
  - `backend/app/explain/records.py`: `ExplanationRecord`, `ChainLink`, `DriverRecord`, `EvidenceReceipt`, `CascadeLoop`, `ConcurrentCluster`.
  - `backend/app/intervene/records.py`: `Action`, `ActionInstance`, `InterventionPlan`, `PlanOutcome`, `SideEffect`, `ResourceUse`, `Assumption`.

---

## Measured Costs

- **Vectorised Monte Carlo Rollouts (`scripts/bench_forecast.py`):**
  - 60 nodes × 72 hours × 300 rollouts = 1,296,000 node-steps.
  - Measured runtime: **0.209 seconds** (Throughput: **6,212,580 node-steps/sec**).
- **Single Forecast Step (`scripts/run_forecast.py`):**
  - State estimation + RLS learning + 300 rollouts + aggregation: **0.41 seconds**.
- **Full Replay Stream Ingestion & Processing:**
  - 72-hour scenario window at 3h cadence: **24.5 seconds** (~1.02s per 3h cadence tick).
- **Planner Budgeting:**
  - Fast mode screening: N=100 rollouts (~0.07s per candidate plan).
  - High-precision re-ranking: N=300 rollouts (~0.21s per top plan).
  - Greedy solver with 10 candidate actions evaluates in < 1.0 second.

---

## Assumptions Register

*(Will be populated in H1 with every action effect, parameter, cost, and provenance classification)*

---

## Deviations

- None so far. All rules W1–W12 respected.
