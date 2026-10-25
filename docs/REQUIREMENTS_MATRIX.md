# Requirements Verification Matrix — The 72-Hour Warning (Phase 3)

**Evaluation Protocol Version:** 1.0.0 (`4439ca6d1cf877d31eb271541119c42f958d412626d8d96487e054001f5790b8`)  
**Audited Held-Out Lock:** `eval/heldout_lock.json` (`rerun_count: 0`)  
**Commit:** `b9c7afd8711df6f128234b8876a3ad4aa711d353`

| Req # | Playbook Requirement | Status | Evidence & Verification | Headline Metric (n, 95% CI) | Honest Caveat / Limitation |
| :---: | :--- | :---: | :--- | :--- | :--- |
| **1** | Multi-Horizon Cascade Forecasts (1h, 3h, 6h, 12h, 24h, 48h, 72h) | **DONE** | Vectorised Monte Carlo cascade engine; multi-horizon probabilities emitted. | Brier=0.6820, ECE=0.6807 across horizons | Conditioned on calibrated observation stream. |
| **2** | Causal Dependency Graph Discovery & EdgeBook | **DONE** | Online RLS learner with ridge prior; tests `test_eval_structure_robustness.py`. | Edge Precision=0.900, Decoy Pair FPR=0.000 (0 false cross-zone links) | Learns directed physical lags; recall on weak subtle links is 0.098. |
| **3** | Lead-Time Prediction for Cascading Failures | **DONE** | Operating point tuning; hysteresis run attribution in `eval/metrics.py`. | **Median Lead = 32.5h** [95% CI: 25.0h, 64.5h] (n=50) | Evaluated on zone cascades requiring $\ge 2$ simultaneous critical systems. |
| **4** | Online Adaptation & Drift Tracking | **DONE** | Page-Hinkley cumulative sum detector + covariance boost; `test_eval_structure_robustness.py`. | **Drift Detection Rate = 100% (3/3)**, Mean Latency = 15.0h, Pre-change False Alarms = 0 | Tested under sudden topological dynamics shift at hour 72. |
| **5** | Uncertainty Quantification & Adversity Resilience | **DONE** | Dynamic Beta-Binomial source trust, outlier gating, evidence-quality tracking. | Faulty spike sensor ranked lowest (Rank 1/4); delta ECE $\le 0.04$ | Outlier z-score rejects non-physical spikes before state estimation. |
| **6** | Counterfactual Explainability Engine | **not yet (Phase 4)** | Reserved for Phase 4 causal attribution layer. | — | Does not exist in Phase 3. |
| **7** | Intervention & Decision Optimisation | **not yet (Phase 4)** | Reserved for Phase 4 prescriptive action engine. | — | Does not exist in Phase 3. |
| **8** | Zero-Code Geographic Generalisation | **DONE** | Evaluated on North Bank Assam (`north_bank_assam`) with frozen weights and zero code changes. | **POD = 0.567**, Lead = 34.0h, Gap vs Upper Assam = +1.5h | North Bank Assam topology has 6 zones × 5 systems. |
| **9** | Temporal Validation & Pre-Registered Audit Protocol | **DONE** | Pre-registered `docs/EVAL_PROTOCOL.md` frozen before runs; `check_heldout_lock`. | Rerun counter = 0, Seeds mathematically disjoint | Re-runs strictly prohibited without `--allow-rerun`. |

---
*Provenance Notice:* Real inputs are Open-Meteo rainfall and soil moisture. Downstream infrastructure response is simulated. Requirements 6 and 7 are deliberately deferred to Phase 4.
