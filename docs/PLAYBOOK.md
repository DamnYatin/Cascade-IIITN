# The 72-Hour Warning: Technical Playbook for a 24-Hour Hackathon

*Theme 2 · Problem 2: predict cascading urban crises up to 72 hours ahead.*
*Written for Yatin. Based on the problem statement screenshot plus a read of your two zips (`CF26-S03-MidnightZombie-main` = Urban Infrastructure Cascade Simulator, `Rain_Prediction_System_using_AIML` = India Climate Digital Twin).*

---

## Contents

1. [Verdict in 60 seconds](#1-verdict-in-60-seconds)
2. [A prompt you can paste into any AI to go deeper](#2-a-prompt-you-can-paste-into-any-ai-to-go-deeper)
3. [The problem explained in detail](#3-the-problem-explained-in-detail)
4. [Requirement by requirement: what it means and the 24-hour version](#4-requirement-by-requirement-what-it-means-and-the-24-hour-version)
5. [Can your two projects be reused? (honest audit)](#5-can-your-two-projects-be-reused-honest-audit)
6. [Recommended architecture](#6-recommended-architecture)
7. [The core math, kept small enough to build in a day](#7-the-core-math-kept-small-enough-to-build-in-a-day)
8. [Data strategy: what is real, what must be synthetic](#8-data-strategy-what-is-real-what-must-be-synthetic)
9. [Validation protocol (this is where most teams lose)](#9-validation-protocol-this-is-where-most-teams-lose)
10. [24-hour schedule](#10-24-hour-schedule)
11. [What to avoid](#11-what-to-avoid)
12. [How to stand out](#12-how-to-stand-out)
13. [Tech stack: use / skip](#13-tech-stack-use--skip)
14. [Pre-hackathon checklist](#14-pre-hackathon-checklist)
15. [What I verified and what I did not](#15-what-i-verified-and-what-i-did-not)

---

## 1. Verdict in 60 seconds

**Is it feasible to enter with your two projects? Yes, but only as a foundation, not as the product.**

| | Cascade Simulator | Rain Prediction System |
|---|---|---|
| What it gives you | A forward simulation engine, graph UI, WebSocket streaming, seeded reproducibility | Real IMD rainfall data for 20 Maharashtra districts (2019–2025), a data loader, a dashboard |
| What this problem needs that it lacks | Learning from data, forecasting with probabilities, evidence, uncertainty, calibration, interventions, zones | Hourly resolution, multi-day horizons, spatial structure, uncertainty, extreme-event skill |
| Reusable share | ~30% (plumbing, UI shell, test discipline) | ~15% (data + loader + a few replayable flood events) |
| Core predictive logic reusable? | **No** | **No** |

The statement's "core challenge" is: *predict the cascade, not merely the individual event.* Both of your projects stop short of that:

- The Cascade Simulator is a **forward simulator with hand-set edge probabilities**. It asks "if X fails, what happens?" The problem asks the reverse: "given noisy evidence streaming in, what is *probably about to fail*, in what order, and when?" Its README itself says the edge probabilities are "calibrated domain heuristics", i.e. hand-set, whereas the problem says dependencies "are not provided" and must be inferred.
- The Rain system is a **next-day, state-wide-average point forecaster**. The problem needs hourly-to-72h, per-zone, probabilistic output.

**The winning move:** turn your simulator into the *forward model inside a learning-and-forecasting loop*. It becomes (a) the Monte Carlo engine that rolls the cascade forward, (b) the counterfactual engine for interventions, and (c) the generator of synthetic ground truth for validation. Everything around it (evidence ingestion, online learning, calibration, explanations) is new work.

**Ask the organizers before you start:** are pre-existing/pre-built components allowed? See [section 11, pitfall 1](#11-what-to-avoid). I could not see the rules, and this is the single biggest risk to your entry.

---

## 2. A prompt you can paste into any AI to go deeper

This is a *research/explainer* prompt (no code generation). Paste it as-is.

```text
You are a senior applied-ML and systems engineer who has judged hackathons and built early-warning systems for critical infrastructure. I need a deep technical explanation, NOT code.

PROBLEM STATEMENT ("The 72-Hour Warning"):
Build a system that predicts cascading urban crises up to 72 hours before they become critical, discovers how city systems depend on each other, and continuously revises its forecasts as evidence arrives. Inputs are asynchronous, heterogeneous, unreliable streams: weather/rainfall/river levels; traffic and public transport; power availability and infrastructure failures; hospital capacity, ambulance movement, emergency calls; satellite/geospatial data; historical incidents and citizen reports.
Output: four risk states (NORMAL, WATCH, HIGH RISK, CRITICAL) per zone and city-wide, the most probable failure sequence, and when each stage and the critical point will occur. Core challenge: predict the cascade, not merely the individual event.
Must also meet: (1) multi-horizon forecasting from next hour to 72h with calibrated probabilities and time-to-critical estimates; (2) dependency discovery: interdependencies are NOT provided and must be inferred from data and updated as the city changes; (3) cascade prediction including branching, feedback loops and simultaneous interacting cascades; (4) continuous online learning under concept drift without retraining from scratch; (5) handling missing, delayed, noisy, contradictory and deliberately misleading inputs, with confidence that degrades gracefully; (6) causal explainability: causal drivers of every risk change and the predicted failure chain with evidence per link; (7) constrained counterfactual intervention: preventive actions under limited resources, how each breaks the cascade, and side-effects; (8) generalization to a city or scenario unseen during development; (9) temporal validation: lead time, false-alarm rate and calibration on replayed streams with strict future-data isolation.

MY CONTEXT: 24-hour hackathon, I code in Python (FastAPI) and React/TypeScript. I already have (a) a discrete-tick cascade failure simulator (NetworkX directed graph, hand-set edge probabilities, seeded Monte Carlo, WebSocket UI) and (b) a BiLSTM daily rainfall/temperature forecaster on IMD data for Maharashtra districts. No real traffic/hospital/power data is available to me.

Please answer in these parts:
A. Explain the problem in plain language, then restate it as a precise ML/statistics problem (what is the state, observation model, prediction target?).
B. For each of the 9 requirements: what it really means technically, the standard methods, the simplest version I can build and validate in a few hours, and how a judge could test it.
C. A concrete system architecture and data model (zones, systems, nodes, edges with lags), including how risk states are derived from calibrated probabilities.
D. How to do dependency discovery and online learning when ground truth is unavailable, and how to avoid claiming causation from correlation.
E. How to build a leakage-proof replay/validation harness (event time vs arrival time, label delay for 72h targets, walk-forward evaluation) and which metrics to report.
F. The 15 most common mistakes teams make on this kind of problem, and the 10 things that would make a submission clearly stand out.
G. Where my existing simulator and rainfall model help, and where they do not.
Be specific, use formulas where helpful, flag trade-offs, and say what you are unsure about. Ask me clarifying questions only at the end.
```

---

## 3. The problem explained in detail

### 3.1 In plain language

Disasters are rarely one event. A flood is a *chain*: rain → drains saturate → roads flood → ambulances slow → hospitals strain → substations are exposed → comms get overloaded. By the time the last link is visible, it is too late. The task is to build an **early-warning brain** that watches many messy data streams, works out which city systems lean on which, and says *"Zone 4 will probably hit CRITICAL in about 31 hours, via this chain, here is the evidence, and here is what you can do about it."*

### 3.2 As a precise technical problem

It combines five classic problems. Name them in your pitch; judges like precision.

| Sub-problem | Technical name | One-line meaning |
|---|---|---|
| Noisy streams → current situation | **State estimation / data fusion** (Kalman/particle/Bayesian filtering) | What is the true state of each system right now, given unreliable sensors? |
| Who depends on whom | **Structure learning / dependency discovery** (Granger, transfer entropy, lagged regression, Hawkes processes) | Infer a directed, lagged graph from data and keep updating it |
| What happens next | **Probabilistic multi-horizon forecasting** with first-passage times | P(state ≥ X by hour h) and the distribution of time until CRITICAL |
| Keep learning as the world changes | **Online learning + drift detection** (ADWIN, Page–Hinkley, forgetting factors) | Update beliefs per event; detect when dynamics change |
| What should we do | **Counterfactual / decision-making under constraints** (do-operator on a simulator, knapsack/greedy) | Compare futures with and without each action, under a budget |

### 3.3 What the output looks like

For every zone *and* the whole city, at every update:

- A **risk state**: NORMAL · WATCH · HIGH RISK · CRITICAL
- **Calibrated probabilities** at several horizons (e.g. +1h, +3h, +6h, +12h, +24h, +48h, +72h)
- **Time-to-critical**: median plus an interval (e.g. 31h, 80% interval 22–44h), including the probability it never happens within 72h
- The **predicted failure chain**: ordered stages with ETAs, each link carrying its evidence, lag and strength
- **Confidence/evidence quality**, which must drop gracefully when inputs are bad
- **Recommended interventions** with expected effect on the cascade and side-effects

### 3.4 How risk states should be defined (example you can tune)

Do not threshold a raw model score. Define states on the **calibrated** probability and time-to-critical, then tune cut-offs on validation data to hit a target false-alarm rate.

| State | Example rule |
|---|---|
| NORMAL | P(CRITICAL within 72h) < 5% |
| WATCH | 5% to 20% |
| HIGH RISK | 20% to 50%, or median time-to-critical < 24h |
| CRITICAL | ≥ 50% within 12h, or a hard system limit already breached |

These numbers are placeholders. What matters is that the rule is explicit, documented and tuned on held-out data.

---

## 4. Requirement by requirement: what it means and the 24-hour version

"MVP" = what you must have. "Wow" = what separates you if time allows.

| # | Requirement | What a judge is really checking | MVP (24h) | Wow |
|---|---|---|---|---|
| 1 | **Multi-horizon forecasting** with calibrated probabilities and time-to-critical | Are probabilities *honest*? Is there a time estimate, not just a label? | Monte Carlo rollouts over hourly steps give P(state ≥ X at horizon h) and a first-passage time distribution. Isotonic calibration on a held-out window. Reliability diagram. | Online recalibration; per-zone calibration; interval coverage check |
| 2 | **Dependency discovery** (not provided) | Did you *infer* the graph or hard-code it? | Per-node online sparse (L1) logistic/linear model over *lagged* parent signals. Edges = significant weights with a confidence. Domain graph used only as a weak prior that data can override. | Recover a planted ground-truth graph and report edge precision/recall; show edges appearing/disappearing as the city changes |
| 3 | **Cascade prediction** (branching, feedback loops, simultaneous cascades) | Stage-by-stage chain with ETAs, not one score | Lagged edges + noisy-OR combination of parents + feedback edges (e.g. evacuation → congestion → ambulance delay). Rollouts naturally produce branching. Two concurrent triggers interacting at shared nodes. | Show a loop amplifying itself and the intervention that breaks it |
| 4 | **Continuous online learning under drift** | No "retrain from scratch"; handles regime change | Streaming updates (River or hand-written SGD) plus ADWIN on prediction error; raise the learning rate on drift. | Live demo: change the dynamics mid-stream, watch drift detection fire and edges re-learn |
| 5 | **Uncertainty and adversity** | Does it survive lies, gaps and delays? | Per-source trust score (Beta posterior); outlier gating; stuck-sensor detector; citizen reports count only as weak evidence unless corroborated; widen intervals when evidence quality drops. | Chaos panel: inject sensor outage and a spam flood of fake reports live; show trust scores falling and confidence degrading, not collapsing |
| 6 | **Causal explainability** | Every risk change traceable to evidence | An **evidence ledger**: each update stores which observations (with source, time, trust) moved which node, and each predicted chain link shows lag, strength, supporting evidence. Generated *deterministically from model internals*. | Click any link → see its evidence and "what if this link were removed?" |
| 7 | **Constrained counterfactual intervention** | Does the action actually break the cascade, with side-effects? | Action library with cost and effect vectors (positive *and* negative). Re-run rollouts with the action applied (same random numbers) and compare. Greedy selection under a budget. | Side-by-side "do nothing vs recommended plan" with ΔP(CRITICAL), Δ time-to-critical, and a side-effect list |
| 8 | **Generalization** to an unseen city/scenario | Zero code changes for a new city | **Config-driven city** (zones, assets, adjacency, available streams in one file). Train/tune on cities A and B, test on C. | Judge hands you a config and you load it live in under a minute |
| 9 | **Temporal validation** | Lead time, false-alarm rate, calibration, no future leakage | Replay harness that exposes data only by *arrival time*; walk-forward evaluation; report lead time, false alarms, Brier score, ECE. Compare with baselines. | Leakage canary test (see section 9.4) shown on a slide |

Two requirements are easy to under-deliver: **#9 (numbers)** and **#5 (adversarial demo)**. Teams build a pretty dashboard and then have no honest metrics. Do not be that team.

---

## 5. Can your two projects be reused? (honest audit)

### 5.1 Urban Infrastructure Cascade Simulator

**What it is (from the code):** 16 nodes across 6 sectors (Power, Water, Telecom, Transit, UPI/Payments, Healthcare) in a NetworkX `DiGraph`. Node status is one of UP / FAILED / RECOVERING / RECOVERED. Each tick, a node that *newly failed* rolls `rng.random() < propagation_probability` against each healthy downstream neighbour, and success means failure on the next tick. Seeded `random.Random(seed)` gives byte-identical reruns. Every failure records `source_service_id`, which gives you causal lineage and cascade depth. Backend: FastAPI with REST + WebSocket; frontend: React 18 + Tailwind + SVG graph with a timeline scrubber; pytest reproducibility suite (README claims 5 passing; I did not run it).

**Gap analysis against the 72-hour problem:**

| Need | Status in your simulator | What must change |
|---|---|---|
| Infer dependencies from data | Missing. Edge probabilities are hand-set. | New: online dependency learner |
| Evidence ingestion (async, noisy, delayed) | Missing. Only manual failure injection. | New: stream adapters, event-time/arrival-time model |
| Zones (spatial) | Missing. Nodes are named city-wide services, not zone-level. | Nodes become (zone, system) pairs |
| Severity / continuous load | Missing. Node state is categorical. | Add a continuous stress ∈ [0,1] plus thresholds |
| Time lags per edge | Fixed 1-tick lag for every edge | Per-edge lag distribution, ticks = hours |
| Sustained pressure | Propagation only fires when a parent *newly* fails; a parent that stays failed adds no continuing pressure | Hazard depends on parent's *current* stress each step |
| Probabilities at horizons | Missing. One stochastic run per seed. | Run N rollouts, aggregate P(state ≥ X by h) and first-passage times |
| Calibration | Missing | Isotonic/Platt on held-out predictions |
| Online learning, drift | Missing | New |
| Source trust, adversarial inputs | Missing | New |
| Interventions with side-effects | Missing | Re-run rollouts with `do(action)` |
| Generalization | Hard-wired 16-node city in `graph_builder.py` | Load city from config |
| Four risk states | Different state set | New mapping layer |

**What you can genuinely keep or adapt:**

- **Seeded-RNG discipline and the reproducibility tests.** For counterfactuals, running "with action" and "without action" using the *same random numbers* (common random numbers) cuts variance and makes comparisons meaningful. You already think this way.
- **Causal lineage (`source_service_id`)** is the seed of your explanation chain.
- **Pydantic models, FastAPI + WebSocket streaming skeleton.**
- **The React HUD shell**: graph view, timeline scrubber, metrics panel. Re-skin; don't rebuild from zero.
- **Noisy-OR is already implicit in your engine** (a target can be triggered by any parent's independent roll). Say so explicitly in the pitch.

**Realistic reuse: ~30%, mostly plumbing and UI.** The engine's tick loop will be rewritten, though your understanding of it carries over.

### 5.2 Rain Prediction System (India Climate Digital Twin)

**What it is (from the code):** IMD annual `.GRD` files (rainfall at 0.25°, Tmax/Tmin at 1°), 2019–2025, processed into `maharashtra_climate.csv` (51,140 rows × 20 districts, daily). A bidirectional LSTM (PyTorch) takes **7 days** of `[rainfall, tmax, tmin]` and predicts the **next day**. Streamlit dashboard with 4 tabs (map, predictions, what-if, data explorer). INSAT-3DR `.h5` satellite snapshots dated 1 June 2026 are bundled (I did not inspect their contents).

**Gap analysis:**

| Issue | Evidence in your code/data | Consequence for this problem |
|---|---|---|
| Daily resolution | CSV has one row per district per day | A 72-hour warning needs hourly steps |
| One-day-ahead only | `SEQ_LEN = 7`, predicts day 8 | No multi-horizon forecasting |
| Spatial info discarded | `train_model.py` averages all districts into one state-wide daily series | Cannot give per-zone risk |
| Point forecasts, no uncertainty | Single output vector | Fails "calibrated probabilities" |
| Heavy-tailed target | Rainfall mean 3.8 mm, 75th percentile 0.8 mm, max 359.5 mm | An MSE-trained LSTM will under-predict exactly the extremes that matter |
| Possible leakage | `MinMaxScaler` fitted on the full dataset before the train/val split | Judges testing "strict future-data isolation" will catch this pattern |
| Streamlit | Reruns the script on interaction | Poor fit for a live, streaming, revising system |

**What is genuinely valuable: your data contains real extreme events.** I checked the processed CSV:

| Candidate replay event | What the CSV shows |
|---|---|
| Mumbai, late June–early July 2019 | Mumbai 269 mm on 2019-06-29; district rainfall totals over 28 Jun–4 Jul: Mumbai ~923 mm, Thane ~749 mm |
| Konkan, July 2021 | Thane 360 mm on 2021-07-20 (the single largest value in the file); Mumbai 281 mm on 2021-07-19 |
| Early August 2019 | Thane 295 mm on 2019-08-04, Ratnagiri 266 mm on 2019-08-05; Kolhapur ~479 mm over 1–12 Aug |
| Other | Mumbai 301 mm on 2020-09-23; Mumbai 288 mm on 2023-07-20 |

The numbers above come from your data. The real-world labels (which flood this was) are from my general knowledge, so confirm them before putting them on a slide. Also note that **these are rainfall only**: neither project has real traffic, power, hospital or ambulance data.

**Realistic reuse: ~15%.** Keep the data loader, the CSV and the event list. Don't pitch "our BiLSTM predicts rain" as a feature; weather forecasting is not what is being judged. Treat rainfall as *one input stream*.

### 5.3 Housekeeping problems I found in the zips

- **`dashboard.py` line 17 contains a hardcoded Google Maps API key (`GMAPS_KEY = "AIza…"`).** Rotate or restrict that key now, and move it to an environment variable before any repo is public or shared with judges.
- The Rain zip is ~150 MB (`.GRD`, `.h5`, even a `Claude Setup.exe`). Don't put that in a submission repo; ship a download script or `.gitignore` the data.
- `CLAUDE.md`/`status.md` mention TensorFlow/`.keras`, but the code uses PyTorch/`.pth`. Docs are out of sync; fix before showing anyone.
- The Cascade README lists a four-person team with split roles, so check you are free to reuse teammates' parts (see pitfall 1).

---

## 6. Recommended architecture

```
                         ┌────────────────────────────────────────────┐
  Sources (replayed      │  1. INGEST                                  │
  with delay/loss) ────► │  per-source adapters · event_time vs        │
  rain · river · traffic │  arrival_time · out-of-order buffer         │
  power · hospital ·     │  fault injector (dropouts, spikes, spam)    │
  citizen reports        └───────────────┬────────────────────────────┘
                                         ▼
                         ┌────────────────────────────────────────────┐
                         │  2. TRUST + EVIDENCE LEDGER                 │
                         │  source reliability (Beta) · outlier gate · │
                         │  corroboration rules · provenance IDs       │
                         └───────────────┬────────────────────────────┘
                                         ▼
                         ┌────────────────────────────────────────────┐
                         │  3. STATE ESTIMATOR (per zone × system)     │
                         │  latent stress s ∈ [0,1] + uncertainty      │
                         │  Kalman/particle-style update; missing data │
                         │  simply skips the update (no zero-imputing) │
                         └──────┬───────────────────────┬─────────────┘
                                ▼                       ▼
        ┌───────────────────────────────┐   ┌──────────────────────────┐
        │ 4. DEPENDENCY LEARNER (online) │   │ 5. DRIFT DETECTOR         │
        │ lagged sparse hazard models;   │◄──│ ADWIN on prediction error │
        │ edge = (u→v, lag τ, weight w,  │   │ → raise learning rate     │
        │ confidence); domain prior only │   └──────────────────────────┘
        └──────────────┬────────────────┘
                       ▼
        ┌───────────────────────────────────────────────────────────┐
        │ 6. FORECASTER: Monte Carlo rollouts (your engine, upgraded)│
        │ N≈300 futures × 72 hourly steps · noisy-OR over parents ·   │
        │ feedback edges · concurrent cascades                        │
        │ → P(state ≥ X at h), first-passage time distribution        │
        └──────────────┬────────────────────────────────────────────┘
                       ▼
        ┌───────────────────────────────┐   ┌──────────────────────────┐
        │ 7. CALIBRATOR (isotonic)       │──►│ 8. RISK-STATE MAPPER      │
        │ fitted only on matured labels  │   │ NORMAL/WATCH/HIGH/CRITICAL│
        └───────────────────────────────┘   └───────────┬──────────────┘
                                                        ▼
        ┌───────────────────────────────┐   ┌──────────────────────────┐
        │ 9. EXPLAINER                   │   │ 10. INTERVENTION PLANNER  │
        │ chain + evidence per link,     │   │ do(action) rollouts with  │
        │ generated from model internals │   │ common random numbers     │
        └──────────────┬────────────────┘   └───────────┬──────────────┘
                       └────────────────┬───────────────┘
                                        ▼
                         WebSocket → React UI (map, cascade graph, fan charts,
                         evidence panel, chaos panel, intervention compare)
```

### Data model (keep it this small)

- **City config** (one JSON/YAML file): `zones[]` (id, name, centroid, neighbours), `systems[]` (e.g. drainage, roads, power, comms, hospital, emergency response), `assets[]` (optional), `streams[]` (which sources exist, units, cadence), `capacity` limits.
- **Node** = `(zone, system)`. With ~10 zones × 6 systems you have ~60 nodes. That is plenty for a demo and fast to simulate.
- **Observation event**: `{source, zone, system, value, event_time, arrival_time, quality_flags}`.
- **Edge** (learned): `{u, v, lag_hours (distribution), weight, confidence, last_updated}`.
- **Prediction record** (stored for later scoring): `{issued_at, node, horizon, p_state_geq_X, ttc_quantiles, evidence_ids}`.

### Scope advice

Pick **one city for the main demo** and **one held-out city for generalization**. Mumbai suits you: you already hold its rainfall and several extreme events. Make the second city a different topology (synthetic, or reconfigured zones for Pune/Thane) loaded purely from config.

---

## 7. The core math, kept small enough to build in a day

### 7.1 Node dynamics: a discrete-time hazard model

Let `s_i(t) ∈ [0,1]` be the stress of node *i* (drainage load, hospital occupancy, road saturation, grid load, …). Let `x_i(t)` be exogenous drivers (e.g. rainfall intensity for drainage nodes).

```
hazard_i(t)  =  sigmoid( b_i  +  Σ_j  w_ji · g( s_j(t − τ_ji) )  +  β_i · x_i(t) )
```

- `w_ji`: strength of dependency j → i. Signed (a diversion can *reduce* stress; evacuation can *increase* congestion).
- `τ_ji`: lag in hours. Learn from a small set of candidate lags (e.g. 1, 2, 3, 6, 12, 24 h) by including each lagged copy as a feature and letting L1 sparsity pick.
- **Edge exists** if `|w_ji|` is significantly non-zero. Report a confidence (bootstrap, or posterior variance). *Never call this causal proof*; call it a causal *candidate* and validate it with interventions in the simulator and the planted-graph test.

Multi-parent combination: `P(i fails) = 1 − Π_j (1 − p_ji)` (noisy-OR) when you want an interpretable, per-edge probability. This is also what your current engine does implicitly.

### 7.2 Dependency discovery in practice

Order of increasing effort. Start at the top; stop when time runs out.

1. **Lagged correlation / cross-correlation** per pair → candidate edges and lags (30 minutes).
2. **Per-node sparse lagged regression** (the model in 7.1, fitted online) → the actual learner (2–3 hours).
3. **Granger causality tests** (`statsmodels.tsa.stattools.grangercausalitytests`) as a cross-check (1 hour).
4. *(Stretch)* Hawkes processes for event cascades; PCMCI (Tigramite) is powerful but heavy, so skip it in 24 hours.

Make the prior explicit: initialise `w` from a *physics/domain* graph (heavy rain → drainage → roads → ambulances → hospital) with low confidence. Data must be able to override it. Show a screen where "prior edge" and "learned edge" are visibly different.

### 7.3 Forecast: Monte Carlo over the learned graph

```
for r in 1..N:                      # N ≈ 300
    s ← sample from current belief (state estimator posterior)
    for h in 1..72:                 # hourly
        x ← sample/forecast exogenous drivers (rain forecast ensemble member)
        for each node i:
            hazard ← f(learned weights, lagged s, x)
            s_i ← update stress (+noise), apply feedback edges
        record threshold crossings and first time s_i ≥ critical
aggregate across r:  P(state ≥ X at h) ,  quantiles of first-passage time
```

Cost check: 60 nodes × 72 steps × 500 rollouts ≈ 2.2 million node-steps. Vectorised in NumPy this is well under a second to a few seconds, so it is realistic to recompute on every update or every few seconds.

Time-to-critical is a **first-passage time with censoring**: some rollouts never reach CRITICAL within 72h. Report that mass explicitly ("38% no critical within 72h") rather than hiding it.

### 7.4 Online learning and drift

- Update each node's model per arriving batch with SGD (River's `linear_model.LogisticRegression` or a handful of lines of NumPy).
- Use an exponential **forgetting factor** so old regimes fade.
- Run **ADWIN** (or Page–Hinkley) on each node's prediction error. On drift: raise the learning rate, shrink confidence on affected edges, flag it in the UI.
- **Label delay** (critical subtlety): the label "did X go CRITICAL within 72h of time t?" is only known at t+72h. You may update from it **only after it matures**. Updating earlier is future leakage. Shorter-horizon proxies (+1h/+3h targets) can update the model sooner.

### 7.5 Trust, noise and misleading inputs

- **Source reliability** `r_k ~ Beta(α_k, β_k)`: update by agreement with the fused estimate and with later-confirmed outcomes. Temper each observation's influence: `likelihood ← r_k · p(obs | state) + (1 − r_k) · uniform`.
- **Outlier gating**: reject observations with large Mahalanobis/standardised residual vs. the model's prediction *and* peer sensors.
- **Stuck-at / dropout detection**: zero variance for too long, or flatlining at a sentinel value, means "no information", not "zero".
- **Citizen reports** are weak evidence: aggregate by geo-cell and time window, require independent corroboration (sensor or multiple unrelated reporters), and rate-limit bursts. Example sanity rule: "flooded street" reports from an area with a dry rain gauge and normal river level get down-weighted.
- **Late/out-of-order data**: process by event time but only after arrival; keep a short reorder buffer and re-run the affected window.
- **Graceful degradation**: widen predictive intervals as evidence quality falls, show an "evidence quality" meter, and let the system say "uncertain" rather than invent precision. Confidence should shrink smoothly with data loss, not collapse or stay falsely high.

### 7.6 Interventions

- **Action library**, each with `cost`, `target nodes`, and an *effect vector* with both benefits and side-effects. Examples: deploy mobile pumps to zone Z (reduces drainage stress, uses crew budget); pre-position ambulances (lowers response delay, raises other-zone delay); divert traffic (reduces road stress on A, adds to B); staged evacuation (reduces exposure, *increases* congestion).
- **Evaluation**: re-run the rollouts with `do(action)` using the **same random numbers** as the baseline (common random numbers). Compare ΔP(CRITICAL), Δ time-to-critical, and per-node side-effect deltas.
- **Selection under a budget**: greedy by marginal gain per cost (or a small knapsack/beam search). Explain why it chose that set.
- Wording matters: you are doing counterfactual *simulation* on a learned model. Say "estimated effect under the learned model", not "proven causal effect".

### 7.7 Explanations that are honest

Generate them from data structures, not from an LLM's imagination: for node *i* whose risk rose, list the top contributing terms in the hazard (parent *j*, lag, weight, parent's current stress, the observations that moved the parent, their sources and trust). The predicted chain is the highest-probability path (or the top-k paths) through the learned graph with ETAs. If you use an LLM, use it only to *phrase* the facts you hand it, and still show the structured evidence next to the text.

---

## 8. Data strategy: what is real, what must be synthetic

Be upfront about this; judges respect honesty and punish disguised synthetic data.

| Stream | Source for your demo | Label it as |
|---|---|---|
| Rainfall | **Real**: your IMD district data; replay known extreme windows | Real (daily; see resolution note below) |
| Hourly rain forecast ensemble | An external hourly forecast API or reanalysis if you can fetch it beforehand (check availability and terms at event time; the network may be restricted) | Real, if obtained |
| Geography (zones, hospital/road locations) | OpenStreetMap, cached *before* the event | Real |
| River/drain levels | Physical-ish model driven by real rainfall | Simulated, rain-driven |
| Traffic, power, hospital load, ambulance delays, calls | Generator with daily patterns plus coupling to the rain/stress state, using a **hidden planted dependency graph** | Simulated, and say so |
| Citizen reports | Generator with a configurable false-report rate and spam bursts | Simulated |

**Resolution problem:** IMD data is *daily*, but you need *hourly* steps. Options, from honest to risky: (1) distribute daily totals into hourly intensity with a stochastic storm-shape model and say that you did so; (2) use an hourly external dataset if you can cache it beforehand; (3) run the whole system at 3-hourly or 6-hourly steps for the real replay and hourly for synthetic scenarios. Pick one and disclose it.

**The planted-graph trick (your best validation asset):** when you generate synthetic city streams, you *know* the true dependency graph, lags and event times. That lets you report real numbers: edge-recovery precision/recall, lead time, false alarms. The catch is **circularity**: a model recovering a graph from data you generated with that kind of structure is a weaker claim than doing so on real data. Mitigate by (a) varying the generator family, so the generator's functional form differs from the learner's; (b) adding misspecification (nonlinear effects, unmodelled confounders); (c) holding out whole cities; (d) *also* replaying the real rainfall events.

---

## 9. Validation protocol (this is where most teams lose)

### 9.1 Replay harness

- Every observation carries `event_time` and `arrival_time`. The harness advances a **replay clock** and releases only observations with `arrival_time ≤ clock`.
- The model's `predict(t)` can only touch what the harness released. Enforce it in code (no global dataframe the model can index into).
- **Walk-forward (rolling-origin)**: at each step, predict the next 72h, store the prediction, advance the clock, score when outcomes mature.

### 9.2 Metrics to report (and how to define them)

| Metric | Definition (state yours on the slide) |
|---|---|
| **Lead time** | `t_critical_actual − t_first_alert`, where "alert" = calibrated P(CRITICAL within 72h) above a threshold for k consecutive steps. Report median and distribution across events. |
| **False-alarm rate** | Alerts with no CRITICAL within the horizon, per 100 zone-days (and as a fraction of alerts). Show it *at the operating threshold*, plus a lead-time-vs-false-alarm curve across thresholds. |
| **Hit rate (POD)** | Fraction of real CRITICAL episodes preceded by an alert |
| **Brier score** | Mean squared error of the probability, per horizon |
| **ECE + reliability diagram** | Calibration; bins of predicted probability vs observed frequency |
| **Time-to-critical error** | Median predicted vs actual, and whether the stated interval covers the truth ~80% of the time |

Use confidence intervals or at least multiple seeds/events. A single lucky run is not evidence.

### 9.3 Baselines (non-negotiable)

Without baselines your numbers mean nothing. Compare against:

1. **Isolated monitoring**: each system alerts on its own threshold with no dependency modelling (the thing the problem statement says is inadequate).
2. **Persistence/climatology** per zone.
3. **Static-graph version** of your own system (dependencies frozen at start), to show online learning and drift handling matter.
4. **Hand-set prior graph only**, to show that discovery adds value.

The money slide is: *"cascade-aware forecasting warns X hours earlier than isolated monitoring at the same false-alarm rate."* If you get only one headline result, make it this one.

### 9.4 Leakage canary (cheap, memorable, convincing)

Run the replay twice: once normally, once with all data after time *T* **replaced by garbage**. Assert that every prediction issued at or before *T* is **bit-for-bit identical**. Show the passing test. It proves future isolation better than any sentence on a slide.

### 9.5 Leakage patterns to hunt in your own code

- Scalers/normalisers fitted on the whole dataset (your Rain project does this).
- Random train/test splits on time series.
- Centered rolling windows or smoothing that peek forward.
- Imputing missing values using later values.
- Calibrating on data that overlaps your test window.
- Updating online from 72h labels before they mature.
- Timezone mix-ups (IST vs UTC) that shift events by 5.5 hours and silently create or destroy lead time.

---

## 10. 24-hour schedule

Assumes a team of 2–4. Solo: do all of Must, pick two of Should, skip Nice.

| Hours | Work | Output |
|---|---|---|
| 0–1 | Read the rules; agree scope; **freeze schemas** (city config, observation event, edge, prediction record, WebSocket message) | One-page spec; everyone codes against it |
| 1–5 | **Backbone**: config loader; replay engine with arrival-time clock; synthetic city generator with planted graph; fault injector; real-rain adapter | A replayable stream you can pause, rewind and corrupt |
| 5–10 | **Forecaster**: state estimator; hazard model; Monte Carlo rollouts (upgrade of your engine); risk-state mapper | Per-zone probabilities, time-to-critical, risk states |
| 10–13 | **Learning**: online dependency learner; drift detector; source-trust model | Edges that appear, change and are scored |
| 13–16 | **Validation**: harness; calibration; baselines; lead-time/false-alarm numbers; leakage canary | **Real numbers** and a reliability diagram |
| 16–19 | **UI**: cascade graph with ETAs, fan charts, evidence panel, chaos panel; wire WebSocket | A demo that tells the story |
| 19 | **FEATURE FREEZE** | |
| 19–21 | **Interventions** with side-effects and before/after comparison (do this earlier if you have a spare person) | "Break the cascade" panel |
| 21–22 | New-city load test; fix the worst bugs; pre-record fallback demo video | Safety net |
| 22–23.5 | README, pitch deck, 3-minute demo script, rehearse twice | Submission-ready |
| 23.5–24 | Buffer for upload problems | Submitted |

**Priority tiers**

- **Must:** replay harness + leakage isolation · multi-horizon probabilities with calibration · learned (not hard-coded) dependencies · cascade chain with ETAs · evidence behind each link · baselines and honest metrics · config-driven city.
- **Should:** drift demo · adversarial/chaos panel · intervention planner with side-effects · planted-graph recovery numbers.
- **Nice:** real-event replay polish · map visuals · LLM phrasing of explanations · extra cities.

**Role split for 3–4 people:** (A) stream/replay/data generation + validation, (B) models: estimator, learner, forecaster, (C) frontend + WebSocket + explanations, (D) interventions + pitch + testing. Interfaces are the frozen schemas from hour 1.

---

## 11. What to avoid

1. **Violating originality rules.** Many hackathons require work started during the event, or disclosure of pre-existing code. Ask. If reuse is allowed, **declare it** ("built on our earlier open-source simulator; everything on this list was built during the event"). Also: your Cascade project had four contributors with defined roles, so confirm your teammates are fine with reuse. When in doubt, re-implement the engine; you wrote the graph engine and tests, so a clean rewrite in a few hours is realistic and risk-free.
2. **Pitching "an LSTM that predicts floods".** The problem is explicitly about the *cascade*, not the single event. A black-box classifier with a softmax "87% confidence" fails requirements 1, 2, 3, 6 and 9 at once.
3. **Hard-coding the dependency graph and calling it "discovered".** Judges will ask "what happens if the city changes?" Have an answer on screen.
4. **Uncalibrated probabilities.** A confidence number that was never checked against outcomes is decoration. Show the reliability diagram.
5. **Future-data leakage** (see 9.5). It is the fastest way to lose credibility, and the statement explicitly demands "strict future-data isolation".
6. **Disguising synthetic data as real.** Label simulated streams clearly. The planted-graph benchmark is a strength *only* if you are transparent about it.
7. **Overclaiming.** "95% accuracy at 72 hours" means nothing. Say "median lead time 14h at 1 false alarm per 100 zone-days (n=… events, 95% CI …)". Include failure cases.
8. **Ignoring false alarms.** A system that cries wolf is useless to a city. Always pair lead time with false-alarm rate.
9. **Explanations that are LLM prose with no link to the model.** Evidence must be traceable to real observations and real model terms.
10. **Over-investing in visuals** (3D/WebGL, fancy maps) before the maths works. Your earlier HUD was SVG; stay there.
11. **Over-engineering infrastructure:** Kafka, Neo4j, Docker-compose with six services, Kubernetes. In-memory state + FastAPI + WebSocket is enough and far less likely to break on stage.
12. **Demo that depends on the internet, or a Streamlit rerun cycle.** Cache everything locally; keep a recorded fallback video.
13. **Training heavy models during the hackathon.** Online/lightweight learners only; no multi-hour GPU jobs.
14. **Overfitting to one demo scenario.** If a judge tweaks a parameter or loads a new city and it breaks, you lose requirement 8.
15. **Missing a requirement entirely.** Judges will likely walk the nine-point list. For each, have a visible proof panel, even a modest one.
16. **Timestamps and timezones.** Use UTC internally, convert only at the UI edge. Log event time and arrival time separately.
17. **Hardcoded secrets in the repo** (your `dashboard.py` has one; see 5.3) and committing large data files.
18. **Scope creep after hour 19.** Freeze features; use the remaining time for numbers, bugs and rehearsal.

---

## 12. How to stand out

Most teams will ship a dashboard with a risk map and an LSTM. These are the moves that separate winners, ordered by impact per hour.

1. **The requirement-to-proof matrix.** One slide (and one UI tab): each of the nine requirements → the live panel or test that demonstrates it. It shows you read the brief and makes judging easy.
2. **The baseline headline.** "Cascade-aware warning arrives *X hours earlier* than isolated monitoring at the same false-alarm rate." Back it with the lead-time vs false-alarm curve.
3. **A live chaos panel.** Buttons for "kill this sensor", "flood the system with fake reports", "delay feed by 3h", "swap in contradictory readings". Show trust scores falling and confidence degrading *gracefully*. This is requirement 5 made visceral.
4. **A drift moment.** Mid-demo, change the city's dynamics (e.g. a drain gets cleared, so a dependency weakens). Show drift detection firing and an edge re-learned without retraining.
5. **Planted-graph recovery plus real-rain replay.** Two kinds of evidence: controlled (known truth, precision/recall of edges) and realistic (your Mumbai 2019 / Konkan 2021 rain windows driving the system).
6. **"New city in 60 seconds."** Let a judge drop in a config; the system runs without code changes. This directly answers requirement 8.
7. **Evidence receipts.** Click any link in the predicted chain: see lag, strength, supporting observations, source trust, and "what if this link didn't exist?".
8. **Break-the-cascade comparison.** Side-by-side timelines (no action vs recommended plan) with ΔP(CRITICAL), Δ time-to-critical, **and the side-effects** the statement specifically asks for.
9. **Honest "when we don't know" behaviour.** A slide on failure modes and abstention. Judges trust teams that show limits.
10. **Leakage canary test on screen** (9.4). Almost nobody does this.
11. **One-command run and reproducible seeds.** Carry over your reproducibility culture: `./start.sh`, fixed seeds, a small pytest suite that runs in seconds.
12. **A story, not a feature tour.** Build the 3-minute demo around one event: "29 June 2019, Mumbai. Here is what a siloed monitor saw at hour −40, and what we saw." Open with the cascade, then show the evidence, then the intervention.

**Suggested 3-minute demo arc:** problem in one sentence (15s) → replay starts, system quiet (15s) → first WATCH, show chain and ETAs (45s) → chaos injection, confidence degrades but holds (30s) → intervention comparison (30s) → numbers vs baselines + reliability diagram + requirement matrix (45s).

---

## 13. Tech stack: use / skip

| Use | Why |
|---|---|
| Python 3.11, FastAPI, WebSocket | You already have it working |
| NumPy/SciPy | Vectorised Monte Carlo is the speed lever |
| NetworkX | Graph bookkeeping and path extraction (not for the hot loop) |
| scikit-learn | `IsotonicRegression` for calibration, metrics |
| River | Online learners and `ADWIN` drift detector (or write 30 lines yourself) |
| statsmodels | Granger tests as a cross-check |
| Pydantic | Schemas you freeze at hour 1 |
| React + TypeScript + Tailwind + Recharts | Reuse your HUD; Recharts for fan charts and reliability diagram |
| SVG zone map from simple GeoJSON | No tile-server dependency during the demo |
| pytest | Leakage canary, determinism, replay tests |

| Skip (in 24h) | Why |
|---|---|
| Kafka/Redis/Neo4j/Postgres | Nothing here needs them |
| TensorFlow / large deep nets | No time to train; poor calibration; hard to explain |
| PCMCI/Tigramite, deep causal discovery | Heavy; hard to debug in a day |
| Live map tiles, 3D/WebGL | Offline risk and time sink |
| Docker orchestration | One script is enough; maybe a single Dockerfile as stretch |
| LLM calls in the critical path | Latency, cost, and hallucination risk; optional wording only |

---

## 14. Pre-hackathon checklist

- [ ] Confirm rules: pre-existing code allowed? Are datasets or a replay stream provided? What are the judging criteria and weights?
- [ ] Get teammates' consent for reusing shared code; plan the "built during event" disclosure list.
- [ ] Rotate/restrict the Google Maps key found in `dashboard.py`; move secrets to `.env` (and add it to `.gitignore`).
- [ ] Cache before the event (if rules and network allow): OSM data for your demo city, any hourly weather data, and Python/npm packages.
- [ ] Prepare a clean repo skeleton: `backend/`, `frontend/`, `data/` (gitignored), `scripts/`, `tests/`, one-command start script.
- [ ] Pre-write the schemas (city config, observation, edge, prediction) so hour 0–1 is a review, not a design session.
- [ ] Pick your 2–3 replay events and write down what happened in each (verify the real-world details).
- [ ] Draft the requirement-to-proof matrix and the 3-minute demo script *now*; fill in numbers later.
- [ ] Prepare a fallback: pre-recorded demo video and cached outputs in case of venue Wi-Fi failure.

---

## 15. What I verified and what I did not

**Verified by reading your files:** the structure and logic of the Cascade engine (tick loop, propagation rule, status model, lineage, API, frontend stack); the Rain project's data shape (51,140 rows, 20 districts, 2019-01-01 to 2025-12-31), BiLSTM setup (7-day window, next-day target, state-wide averaging, scaler fitted before split), and rainfall statistics and extreme-event dates in your CSV; the hardcoded Maps key in `dashboard.py`.

**Not verified:**

- I did not run your pytest suite or either app; the "5 passing tests" claim comes from your README.
- I did not open the INSAT `.h5` files, so I cannot say what they contain or how usable they are.
- I have not seen the hackathon rules, scoring rubric, or whether data is provided. Everything about "what judges check" is inference from the nine listed requirements.
- Real-world event names (Mumbai 2019, Konkan/Kolhapur–Sangli floods) are from general knowledge; only the rainfall values come from your data. Confirm them before citing.
- External data sources and library behaviour (hourly weather APIs, River, statsmodels) should be checked on the day, since availability, terms and versions can change.
- All numeric thresholds, sample sizes and time estimates here are starting points to tune, not benchmarks.
