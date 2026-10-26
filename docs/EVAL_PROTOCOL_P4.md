# Pre-Registered Evaluation Protocol: Phase 4 (Causal Explanations & Constrained Interventions)

**Protocol Version:** 1.0.0  
**Status:** FROZEN PRIOR TO HELDOUT EVALUATION  
**Phase:** 4 (Requirements 6 & 7)  
**Target Repository:** `72-hour-warning-phase1`  
**Target Branch:** `feat/explain-intervene`  

---

## 1. Executive Summary & Pre-Registration Discipline

This document formalizes the pre-registered evaluation protocol for Phase 4 of "The 72-Hour Warning". Following strict scientific discipline:
1. **Pre-Commitment:** This protocol is authored, reviewed, and committed to git **BEFORE** executing any evaluations on held-out seeds (`{201, 202, 203, 204, 205}`) or generating `eval/heldout_lock_p4.json`.
2. **Zero Held-Out Tuning:** Held-out seeds and the held-out city topology (`north_bank_assam`) are strictly evaluated once. No hyperparameters, objective weights, action parameter values, solver screening rollouts, or thresholds are adjusted after observing held-out numbers.
3. **Common Random Numbers (CRN):** All counterfactual with/without action comparisons and truth simulator validations are paired using identical SeedSequence RNG streams. The do-nothing plan reproduces the baseline unperturbed forecast byte-for-byte.
4. **Honesty & Provenance Disclosures:** Downstream municipal infrastructure dynamics are simulated; real inputs are rainfall and soil moisture; all action effect sizes are assumed with provable provenance tags (`assumed`, `expert_estimate_needed`, or `grounded_category`).

---

## 2. Pre-Registered Seed Partitions & Scenarios

To prevent data snooping and circular tuning, Phase 4 reserves dedicated seeds:

| Partition | Seeds | Purpose | Policy |
| :--- | :--- | :--- | :--- |
| **Dev Seeds** | `{31, 32, 33}` | Algorithm verification, solver benchmarking, sanity tests | Free inspection & profiling |
| **Held-Out Seeds** | `{201, 202, 203, 204, 205}` | Formal performance validation for Playbook submission | Evaluated ONCE post-freeze |
| **Held-Out Topology** | `north_bank_assam` (seed 201) | Cross-topology generalization test (6 northern districts) | Evaluated ONCE post-freeze |

Scenario windows:
- 72-hour forecast horizon across Upper Assam (hero window: July 2026 flood event).
- Anchor mode: `"off"` (canonical unanchored synthetic generation).

---

## 3. Evaluated Tasks & Frozen Metric Definitions

### Task A: Causal Explanation Accuracy & Faithfulness (Requirement 6)

Evaluates whether the candidate failure chains and attributed drivers match true latent dynamics and planted causal structures:
1. **Top-1 Dominant Parent Accuracy:** Fraction of threshold-crossing nodes where the predicted dominant parent matches the true planted contributor with highest lagged influence in ground truth.
2. **Chain Link Precision, Recall, and F1:** Overlap between predicted failure chain links $(u \to v)$ and true active cascade links in ground truth where $u$ crossed critical threshold before $v$.
3. **Stage Order Agreement (Spearman $\rho$):** Rank correlation between predicted stage traversal order and actual temporal crossing order.
4. **Stage ETA Error (MAE):** Mean absolute error in hours between predicted stage crossing ETAs and actual ground-truth crossing times.
5. **Root Cause Recall:** Fraction of true cascade trigger roots (nodes that crossed critical threshold without upstream parents having crossed) identified in the top-3 driver set.
6. **Faithfulness Deletion Gap:** Difference in risk reduction when removing the top-ranked driver versus the lowest-ranked driver under paired re-rollout ($\Delta P(\text{critical})_{\text{top}} - \Delta P(\text{critical})_{\text{bottom}}$).

**Baselines for Task A:**
- **Prior-Graph Shortest Path:** Static shortest distance on unweighted prior graph without real-time evidence.
- **Raw Correlation Attribution:** Pearson correlation of raw observations without learned lag or causal directionality.
- **Random Topology Path:** Random valid path on prior graph.

---

### Task B: Counterfactual Fidelity (Truth Simulator Validation)

Evaluates whether the planner's internal predicted benefits under the learned model match realised physical outcomes under latent ground-truth simulation (`eval/truth_sim.py`):
1. **Sign Agreement Rate:** Fraction of candidate plans where the predicted benefit ($\Delta$ critical zone-hours) and realised benefit agree in sign ($\text{sgn}(\Delta_{\text{pred}}) == \text{sgn}(\Delta_{\text{real}}}$).
2. **Rank Correlation (Spearman $\rho$):** Correlation between predicted plan ranking and realised benefit ranking under true latent dynamics.
3. **Calibration Slope:** Regression slope of realised benefit onto predicted benefit ($\beta$ in $\text{Realised} = \alpha + \beta \cdot \text{Predicted}$).
4. **Realised Cascade-Broken Rate:** Fraction of plans predicted to break a cascade that successfully prevent or terminate critical episodes in ground truth.

---

### Task C: Constrained Decision Quality & Regret vs Baselines (Requirement 7)

Evaluates the decision quality of the greedy solver under strict multi-resource budget caps (crews, pumps, boats, generators, cost in INR Lakhs):
1. **Realised Net Benefit:** Total cascade-critical zone-hours eliminated minus weighted side-effects and resource penalties.
2. **Regret vs Truth Simulator Oracle:**
   $$\text{Regret} = \max_{p \in \mathcal{P}_{\text{feasible}}} \text{RealisedBenefit}(p) - \text{RealisedBenefit}(p_{\text{chosen}})$$
3. **Side-Effects Avoided Rate:** Fraction of available plans rejected due to excessive adverse side-effects (e.g. road gridlock from sandbagging trucks).
4. **Optimality Gap (%):** Regret expressed as a percentage of the oracle best possible benefit.

**Baselines for Task C:**
- **Truth Simulator Oracle:** Upper-bound exhaustive search directly under latent ground truth.
- **Treat Highest Risk Node:** Heuristic allocating resources purely to nodes with current highest stress.
- **Static Priority Order:** Standard municipal SOP deploying fixed actions in static order regardless of cascade state.
- **Side-Effect Blind Planner:** Ablation of the planner with side-effect weight set to 0.0.
- **Random Feasible Plan:** Random sampling within budget constraints.
- **Do Nothing:** Zero actions deployed.

---

### Task D: Robustness Under Faults & Held-Out Topology

Evaluates system degradation and honest abstention under:
1. Sensor dropouts (20% packet loss).
2. Spurious sensor spikes (30% false positive spikes).
3. Feed latency delays (6-hour telemetry lag).
4. Cross-geography transfer to `north_bank_assam` (distinct 6-district network).
- **Abstention Verification:** Asserts that confidence drops below threshold and unidentifiable driver abstentions fire appropriately without crashing.

---

### Task E: Value of Lead Time

Measures the decay of intervention efficacy as action commitment is delayed:
$$\Delta \text{Start} \in \{0\text{h}, 3\text{h}, 6\text{h}, 12\text{h}, 24\text{h}\}$$
Reports the Cost of Waiting ($\text{INR/hr}$ or $\text{Zone-Hours/hr}$) and the latest start offset retaining $\ge 50\%$ benefit.

---

## 4. Statistical Rigour & Bootstrap Confidence Intervals

1. **Bootstrap Resampling:** All reported metrics include 95% bootstrap confidence intervals derived from 1,000 resamples blocked by simulation seed.
2. **Paired CRN Differences:** Differences between methods are evaluated paired within seed, eliminating scenario difficulty variance.
3. **Full Sweep Disclosure:** Every evaluated parameter sweep is reported, including instances where the forecaster or planner does not outperform a baseline.

---

## 5. Audit & Immutability Lock

Once this file is committed:
- SHA256 protocol hash is recorded in `eval/heldout_lock_p4.json`.
- The evaluation runner (`scripts/eval_phase4.py`) verifies protocol hash and git commit hash before running held-out seeds.
- Any rerun requires an explicit `--allow-rerun` flag, logs the reason, and increments the `rerun_count` visible in all final reports.
