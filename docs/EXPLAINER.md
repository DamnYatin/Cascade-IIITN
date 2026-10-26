# Causal Explanations Engine: Methods, Equations & Honesty Rules

**Phase:** 4 (Requirement 6: Causal Explainability)  
**Modules:** `backend/app/explain/` (`chains.py`, `attribution.py`, `receipts.py`, `confidence.py`, `text.py`, `log.py`, `coordinator.py`)  

---

## 1. Overview & Core Philosophy

The primary objective of Requirement 6 is to provide civil protection incident commanders with actionable, transparent, and faithful explanations of **why** a particular infrastructure risk state changed and **how** failures propagate across city networks.

In strict adherence to the **Honesty Principle (W3)**:
- Statistical dependencies learned by recursive state estimators are explicitly designated **"causal candidates"** or **"learned dependencies"**, never "proven physical causes".
- Municipal infrastructure dynamics are simulated; real inputs are rainfall and soil moisture.
- When observational evidence is corrupted by sensor faults, high latency, or collinearity, the engine **gracefully abstains** and reports an auditable receipt explaining why attribution is unidentifiable.

---

## 2. Mathematical Formulations & Algorithms

### 2.1 Trigger Trace & Failure Chain Links

During Monte Carlo cascade rollouts, the engine instruments node activations using the `TriggerTrace` recorder (`backend/app/forecast/trace.py`). For every rollout trajectory $r \in \{1, \dots, N\}$ and target node $v$, when $v$ crosses the critical stress threshold ($\tau_{\text{crit}} = 0.80$) at hour $t^*_r$:

The dominant parent $u^*_r$ is the active incoming dependency that contributed the largest lagged hazard term to $v$:
$$u^*_r = \arg\max_{u \in \text{Parents}(v)} w_{uv} \cdot s_u(t^*_r - \text{lag}_{uv})$$

The **Link Usage Probability** $p_{\text{link}}(u \to v)$ is the empirical fraction of critical activations of $v$ dominated by parent $u$:
$$p_{\text{link}}(u \to v) = \frac{\sum_{r=1}^N \mathbb{I}(v \text{ crossed in } r \land u^*_r = u)}{\sum_{r=1}^N \mathbb{I}(v \text{ crossed in } r)}$$

Timing statistics ($\mu_{\text{lag}}, p_{10}, p_{50}, p_{90}$) describe the empirical distribution of activation lag $(t^*_v - t^*_u)$ conditioned on $u$ triggering $v$.

---

### 2.2 Hierarchical Chain Trees & Censored ETAs

The failure chain tree is extracted via reverse stage traversal starting from target node $v$:
1. A candidate incoming link $(u \to v)$ is expanded into the chain tree if and only if $p_{\text{link}}(u \to v) \ge \text{branch\_floor}$ (default 0.15).
2. For each node in the tree, the engine reports both **conditional ETAs** (arrival time percentiles conditioned on crossing occurring within 72h) and **unconditional ETAs** (with non-crossing rollouts right-censored at 72h).

---

### 2.3 Feedback Loops & Amplification

Cyclic dependencies $\mathcal{C} = (v_1 \to v_2 \to \dots \to v_k \to v_1)$ are detected using directed graph cycle analysis:
- **Amplification Factor:** The ratio of steady-state loop stress to initial impulse under paired Common Random Numbers (CRN).
- **Weakest Link Identification:** The link $(u \to v) \in \mathcal{C}$ whose paired ablation minimizes residual cycle stress:
  $$(u^*, v^*) = \arg\min_{(u, v) \in \mathcal{C}} \mathbb{E}[\text{Stress}_{\mathcal{C} \setminus \{(u,v)\}}]$$

---

### 2.4 Simultaneous Interacting Cascades

When multiple upstream root clusters converge onto shared downstream nodes (e.g. roads or hospitals), the engine measures non-linear interaction:
$$\Delta_{\text{interaction}} = P(v \text{ critical} \mid \text{both roots active}) - \left(1 - (1 - P(v \mid R_1)) \cdot (1 - P(v \mid R_2))\right)$$
If $\Delta_{\text{interaction}} > 0.05$, the cluster is flagged as a **mutually amplifying multi-root cascade**.

---

### 2.5 Risk-Change Attribution: Additive Decomposition & Paired Re-Rollouts

When $P(\text{critical})$ changes between consecutive forecast cycles $t-1$ and $t$:
- **Method A (First-Order Additive Decomposition):** Decomposes $\Delta \text{Risk}$ across active drivers using linearized local gradient contributions. Reports an explicit **non-linear residual** $\epsilon_{\text{residual}} = \Delta \text{Risk} - \sum_i \Delta_i$.
- **Method B (Paired Counterfactual Ablation):** Re-simulates rollouts with driver $i$ frozen at prior state $t-1$ under identical CRN noise. The marginal risk reduction directly yields the attribution score with 95% bootstrap confidence intervals.

---

## 3. Explanation Confidence Score & Graceful Abstention

The overall confidence $C \in [0, 1]$ of an explanation is computed via a multi-criteria formula:
$$C = 0.35 \cdot \bar{T}_{\text{sources}} + 0.30 \cdot \bar{C}_{\text{EdgeBook}} + 0.20 \cdot (1.0 - \min(1.0, |\epsilon_{\text{residual}}|)) + 0.15 \cdot \min\left(1.0, \frac{N_{\text{rollouts}}}{100}\right)$$

Confidence is mapped into auditable categories:
- `high`: $C \ge 0.75$
- `medium`: $0.50 \le C < 0.75$
- `low`: $C < 0.50$ (triggers explicit uncertainty warnings)

### Abstention Criteria
The explainer explicitly records an **abstention** without crashing if:
1. **Unidentifiable Drivers:** Observational variance across parents is zero or collinear, leaving no distinguishable dominant path.
2. **Degraded Evidence:** More than 50% of incoming observation streams are gated by quality filters (e.g. sensor flatline or missing data).
3. **High Non-Linear Residual:** $|\epsilon_{\text{residual}}| > 0.40$, indicating regime shifts uncaptured by local first-order dynamics.

---

## 4. Approved Hedged Phrasing & Linguistic Lints

Every generated explanation string passes through a strict deterministic linter (`backend/app/explain/text.py`) enforcing honest communication:

| Rule Category | Approved Hedging Expressions | Banned Certainty Terms |
| :--- | :--- | :--- |
| **Causal Claims** | "causal candidate", "learned dependency", "empirical trigger" | `proves`, `causes`, `certainly`, `ground truth cause` |
| **Outcome Predictions** | "estimated under learned model", "projected risk", "under assumed effects" | `guarantees`, `will prevent`, `definitely stops` |
| **Data Provenance** | "simulated municipal stream", "grounded category" | `observed field reality`, `sensor ground truth` |

Violations of linguistic hygiene trigger automated test failures in `tests/test_explain_attribution_text.py`.
