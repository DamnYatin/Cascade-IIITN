# Pre-Registered Evaluation Protocol — The 72-Hour Warning (Phase 3)

**Document Status:** FROZEN & PRE-REGISTERED  
**Protocol Version:** 1.0.0  
**Authority:** Playbook Section 9 (Validation Protocol) & Phase 3 Specification  
**Rule V3 Compliance:** This protocol is committed before running any held-out seed. No parameters, thresholds, or heuristics are tuned on held-out seeds.

---

## 1. Disjoint Seed Sets

Seeds are strictly partitioned to prevent data leakage and hyperparameter over-fitting:

- **DEV SEEDS (`{11, 12, 13}`):**
  Used exclusively for:
  - Sweeping alert thresholds $(\tau, k, \tau_{low})$.
  - Selecting optimal operating points.
  - Tuning baseline models (B1 through B7).
  - Diagnostic self-tests and adversarial fault analyses.

- **CALIB-FIT SEEDS (`{21, 22, 23, 24}`):**
  Used exclusively for:
  - Fitting the offline frozen isotonic calibrator (`FrozenIsotonicCalibrator`) via Pool-Adjacent-Violators (PAV).
  - Fitting the time-to-critical $[p10, p90]$ interval widening factor.
  - Saved to `eval/calibrator_frozen.json` with immutable cryptographic provenance.

- **HELD-OUT SEEDS (`{101, 102, 103, 104, 105}`):**
  Evaluated **once and only once**.
  - No parameter or threshold may be tuned on held-out seeds.
  - Generates the final headline verification numbers.
  - Protected by `eval/heldout_lock.json`. Re-runs require `--allow-rerun` and increment an auditable rerun counter.

---

## 2. Evaluation Scenario Families

| Family ID | Description | City Config | Duration | Cadence | Purpose |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`F-storm`** | Stochastic multi-storm rainfall driving Upper Assam. | `upper_assam` | 168h (7 days) | 3h | **Primary Statistical Yardstick**: Contains multiple cascading failure episodes per seed. |
| **`F-quiet`** | Low-rain negative control ($\le 1.0$ mm/h drizzle). | `upper_assam` | 168h | 3h | **Clean False-Alarm Benchmark**: Zero true critical episodes expected; all alerts are false alarms. |
| **`F-drift`** | `F-storm` with planted regime change at hour 72. | `upper_assam` | 168h | 3h | **Online Adaptation**: Measures drift detection latency and error recovery without retrain-from-scratch. |
| **`F-faulted`** | `F-storm` under sensor faults (dropout, stuck-at, spike, delay, spam, blackout). | `upper_assam` | 168h | 3h | **Adversity Resilience**: Measures degradation delta and tests source trust weighting. |
| **`F-heldout-city`** | North Bank Assam topology (6 zones × 5 systems). | `north_bank_assam` | 168h | 3h | **Zero-Code Generalisation**: Evaluated with exact same frozen hyperparameters and code. |
| **`F-real`** | Real Assam July–August 2026 rain/soil moisture series (`hero_full` window). | `upper_assam` | 168h | 3h | **Real-World Illustrative**: Real inputs, simulated downstream infrastructure, `anchor_mode=off`. |

*Modelling Disclosure Note:* The synthetic storm generator represents a modelling choice based on orographic rain bursts in the Nagaland hills flowing into Upper Assam. Synthetic benchmark numbers are conditioned on this generator family.

---

## 3. Ground-Truth Event Definitions

True episodes are extracted strictly by `backend/app/eval/events.py` from latent stress trajectories:

1. **Node-Critical Episode:**
   Latent stress $s_i(t) \ge 0.80$. Start is the first hour $\ge 0.80$; end is the first hour $< 0.80$.
2. **Zone Cascade-Critical Episode (PRIMARY YARDSTICK):**
   At least `zone_cascade_min_systems = 2` distinct infrastructure systems in the zone are simultaneously critical ($s \ge 0.80$). This matches the core mission: *"predict the cascade, not merely the individual event"*.
3. **City-Critical Episode:**
   At least `city_zone_fraction = 0.20` of city zones are simultaneously cascade-critical.
4. **Merge Rule:**
   Episodes separated by less than `merge_gap_hours = 6.0` hours are merged into a single continuous episode.

---

## 4. Alert Logic & Attribution Rules

Alerts are evaluated from calibrated zone-level probabilities $P(\text{cascade-critical within 72h})$:

- **Alert Activation:** Triggered when score $\ge \tau$ for $k$ consecutive forecast steps. First alert time $t_{\text{alert}}$ is the timestamp of the step where $k$ was reached.
- **Alert Deactivation (Hysteresis):** Run ends when score $< \tau_{\text{low}}$ for $k_{\text{off}} = 2$ consecutive steps.
- **Attribution Criteria:**
  - **Hit:** An alert run is credited as a hit for the next true episode that starts within $(0, H_{\text{hit}} = 72\text{h}]$ after the run's first alert step.
  - **Lead Time:** $\text{Lead Time} = t_{\text{episode\_start}} - t_{\text{first\_alert}}$.
  - **Late Alert:** An alert that begins after the episode has already started ($t_{\text{first\_alert}} \ge t_{\text{episode\_start}}$) has negative lead time and counts as a **miss** for POD purposes (reported separately as `late_alerts`).
  - **False Alarm:** An alert run with no true episode starting within $(0, 72\text{h}]$ is a false alarm.
  - **Miss:** A true episode with no qualifying preceding alert run is missed.
  - **Exclusivity:** One alert run serves at most one episode. One episode is credited to the earliest qualifying run.

---

## 5. Metrics Formulation

1. **Brier Score (BS):** $\frac{1}{N} \sum_{i=1}^N (p_i - y_i)^2$.
2. **Brier Skill Score (BSS):** $1 - \frac{\text{BS}}{\text{BS}_{\text{ref}}}$ relative to sample base-rate climatology.
3. **Expected Calibration Error (ECE):** $\sum_{b=1}^{10} \frac{n_b}{N} |\bar{p}_b - \bar{y}_b|$ across 10 equal-width bins with Wilson score 95% confidence intervals on observed frequencies.
4. **Probability of Detection (POD):** $\frac{\text{Hits}}{\text{Hits} + \text{Misses}}$.
5. **False-Alarm Rate (FAR):**
   - **Per 100 Zone-Days:** $\frac{\text{False Alarms}}{\text{Total Zone-Days}} \times 100$, where $\text{Zone-Days} = \frac{\text{num\_zones} \times \text{hours}}{24}$.
   - **Alert Ratio:** $\frac{\text{False Alarms}}{\text{Total Alert Runs}}$.
6. **Lead Time Distribution:** Median, Interquartile Range (IQR = $p75 - p25$), and fraction warned $\ge 6\text{h}, 12\text{h}, 24\text{h}$ ahead.
7. **Time-to-Critical Error:** Median absolute error $|\hat{\text{ttc}} - \text{actual\_ttc}|$ and empirical coverage of the conditional $[p10, p90]$ predictive interval for events that actually occurred.

---

## 6. Pre-Registered Operating Point Selection Rule

On DEV data (`seeds: [11, 12, 13]`), the operating point $(\tau^*, k^*, \tau_{\text{low}}^*)$ is chosen via grid search:
$$\tau \in [0.15, 0.60], \quad k \in [1, 2, 3], \quad \tau_{\text{low}} \in [\tau - 0.20, \tau]$$

**Rule:**
1. Maximize $\text{POD}$ subject to $\text{FAR}_{\text{zone-days}} \le 1.0$ false alarms per 100 zone-days.
2. Tie-break by larger median lead time.
3. If no operating point achieves $\text{FAR} \le 1.0$, select the point minimizing $\text{FAR}$, tie-breaking by higher $\text{POD}$.

The tuned parameters are written to `configs/forecast_tuned.yaml` with commit and protocol hashes.

---

## 7. Fair Baseline Comparisons

Every baseline consumes strictly the same `StreamView` and is tuned on the same DEV data under the exact same selection rule:

- **B1: Isolated Monitoring:** Each node monitors its own observed stress crossing a threshold; zone alert = any node in zone critical. (Represents the siloed architecture).
- **B2: Rain-Rule:** Causal rolling 24h/72h rainfall and soil moisture threshold rule. (Strong simple empirical baseline).
- **B3: Climatology/Persistence:** Running empirical historical frequency per zone.
- **B4: Static Graph Forecaster:** The full forecaster with online learning frozen after burn-in.
- **B5: Domain-Prior Only Forecaster:** Uses only weak domain prior edges without data-driven edge discovery.
- **B6: Unfiltered / No Trust Forecaster:** Forecaster with outlier gating, source trust, and evidence quality widening disabled.
- **B7: Persistence Rain Outlook Forecaster:** Forecaster with basic persistence outlook.

**Headline Comparison:**
- Median lead time at matched False-Alarm Rate.
- False-alarm rate at matched POD.

---

## 8. Statistical Bootstrap & Hypothesis Testing

- **Seed-Blocked Bootstrap:** 2,000 resamples with fixed seed (42). Resampling is blocked by global seed so cross-node and temporal correlations within an episode are preserved.
- **Confidence Intervals:** 95% two-sided intervals from the 2.5th and 97.5th empirical percentiles.
- **Paired Comparisons:** Evaluated on per-seed paired differences $\Delta = \text{Metric}_{\text{Forecaster}} - \text{Metric}_{\text{Baseline}}$.
- **Minimum Sample Size ($n_{\text{min}}$):** Metrics with fewer than 5 events are flagged as *"insufficient n"*.

---

## 9. Pre-Registered Success Criteria

1. **Calibration:** Calibrated forecaster achieves lower Brier Score and lower ECE than raw uncalibrated forecaster on both dev and held-out seeds.
2. **Cascade Advantage:** Forecaster achieves positive lead-time gain ($\Delta \text{Lead} > 0$) over B1 (Isolated Monitoring) at matched FAR on cascade episodes.
3. **Adversity Resilience:** Forecaster degrades less severely under injected faults than ablation B6.
4. **Generalisation:** North Bank Assam (`F-heldout-city`) executes end-to-end with zero code changes, maintaining positive skill ($BSS > 0$).
5. **Future Isolation:** 100% byte-identical predictions under the Evaluation Canary test (observations after $T$ replaced by garbage).

*Failure Clause:* If the forecaster does not outperform a baseline on any specific metric or scenario, the deficit must be stated plainly in `docs/EVALUATION.md` without omission or flattering reframing.
