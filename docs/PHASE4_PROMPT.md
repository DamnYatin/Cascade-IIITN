# PHASE 4 PROMPT: CAUSAL EXPLANATIONS + CONSTRAINED INTERVENTIONS

**How to use:** paste everything inside the code block into your coding agent after Phase 3 is finished and committed. Attach `72_Hour_Warning_Playbook.md` to the session but keep it OUTSIDE the repo (it contains terms the hygiene test bans). Save this prompt in the repo as `docs/PHASE4_PROMPT.md` so a resumed session can re-read it (it contains no banned terms).

---

```text
ROLE
You are a senior ML/decision-systems engineer building Phase 4 of "The 72-Hour Warning". Phases 1 to 3 produced: a leakage-proof replay backbone for the Assam 2026 scenario, a Forecaster (learned dependencies, source trust, drift handling, Monte Carlo cascade rollouts with a reusable NoiseBank), and a pre-registered validation layer (calibration, baselines, lead time, false alarms). Phase 4 delivers the last two playbook requirements that judges will probe hardest:

  Requirement 6, CAUSAL EXPLAINABILITY: identify the causal drivers of every risk change and present the predicted chain of failures with evidence behind each link.
  Requirement 7, CONSTRAINED COUNTERFACTUAL INTERVENTION: recommend preventive actions under limited resources, estimate how each would break the cascade, and account for side-effects (for example evacuation increasing congestion).

Reference document: 72_Hour_Warning_Playbook.md (attached, NOT in the repo). Sections that matter: 4 (requirements 3, 6, 7), 7.6 and 7.7 (interventions and honest explanations), 9 and 12 (validation and standing out). Everything essential is restated below.

Guiding principle: every claim the system makes must be traceable to a structure the system actually holds (an edge, an observation, a rollout statistic), and every claim about the effect of an action must say it is an estimate UNDER THE LEARNED MODEL and UNDER ASSUMED ACTION EFFECTS. The system must never sound more certain than its evidence, and the evaluation must be able to show when it is wrong.

======================================================================
STEP 0: VERIFY THE STARTING STATE BEFORE WRITING ANY CODE
======================================================================
Read docs/PHASE3.md (all items G0 to G10 ticked?), docs/EVALUATION.md, docs/EVAL_PROTOCOL.md, docs/REQUIREMENTS_MATRIX.md, tests/PHASE3_TEST_REPORT.md, eval/heldout_lock.json, docs/FORECASTER.md, docs/PHASE2.md, configs/forecast.yaml and configs/forecast_tuned.yaml, backend/app/schemas.py, and the code in backend/app/forecast/ (especially rollout.py with NoiseBank and the intervention hook, aggregate.py cascade summary and dominant-parent statistics, learner.py EdgeBook, ledger.py, trust.py, records.py, engine.py), backend/app/eval/, backend/app/baselines/, the generator and ground-truth modules (read-only for you in the forecast side), configs/upper_assam.yaml, configs/north_bank_assam.yaml, and docs/sources/Assam_Floods_2026_Report.md. Names in this prompt come from earlier prompts; where the real code differs, follow the real code and record the difference in docs/PHASE4.md.

Then run in PowerShell:
  git status
  git branch --show-current
  git log --oneline -n 20
  python -m pytest -q

Expected: branch feat/evaluation, clean tree, all tests green (report the real count), Phase 3 held-out lock present, REQUIREMENTS_MATRIX rows 6 and 7 reading "not yet".
- If Phase 3 items are unticked or tests are red: stop, tell me exactly what is missing, propose the smallest fix. Do not build on a broken base.
- If Phase 3 is complete: create branch feat/explain-intervene from the tip of feat/evaluation. Never touch main, feat/forecaster or feat/evaluation directly. Do NOT modify Phase 3 held-out results, the Phase 3 protocol, or the tuned config; if you find a bug in earlier phases, follow the post-hoc correction procedure in docs/PHASE3.md (failing test first, focused commit, logged, affected results rerun and reported with before and after).
- Measure cost before designing anything: time one forecast, one full replay, and one batch of N rollouts. Write the numbers in docs/PHASE4.md. Planner and evaluation sizes below must fit those measurements.

Create docs/PHASE4.md with a progress checklist at the top (one box per work item H0 to H10), plus sections "Decisions", "Schema/config changes", "Measured costs", "Assumptions register", "Deviations". Update it after every item so a fresh session can resume from the first unticked item.

======================================================================
NON-NEGOTIABLE RULES
======================================================================
W1  Package boundaries. New runtime packages backend/app/explain/ and backend/app/intervene/ are FORECAST-SIDE: they may use forecaster outputs and internals (ForecastModel, EdgeBook, NoiseBank, ledger, snapshots) but must NEVER import or read ground truth, the planted graph, generator internals, scenario label files, or backend/app/eval/. Code that needs truth (explanation accuracy, counterfactual fidelity, regret) lives under backend/app/eval/, scripts/eval_*, tests/. Extend the import/file-isolation test to cover explain/ and intervene/.
W2  No future information. Explanations and plans issued at time t use only data with arrival_time <= t and the forecaster state at t. Extend the canary test: replace everything after T with garbage; all explanation records and plans issued at or before T must be byte-identical.
W3  Honest language. Edges are "learned dependencies" (causal candidates), never proven causes. Intervention outcomes are "estimated under the learned model with assumed action effects". Add a lint test on every text template and generated string: no unhedged causal certainty words for model-based claims (define the banned and required phrasing lists in docs/EXPLAINER.md), and every number printed in text must match the structured record it came from.
W4  Assumed effects are labelled assumed. There is no real data on how effective any action is in this environment. Every action effect size, cost, delay and side-effect in configs/interventions.yaml carries provenance: assumed | expert_estimate_needed | grounded_category (with source tag from docs/sources/Assam_Floods_2026_Report.md for the existence of the kind of action only, never for its magnitude). Show them in an Assumptions register (docs/INTERVENTIONS.md and the API) and run sensitivity analysis on them (see 5.8). Do NOT set effect sizes from the report's observed timings (that would be circular).
W5  Common random numbers. All with/without-action comparisons reuse the same NoiseBank draws as the baseline rollouts so differences are paired. The "do nothing" plan must reproduce the Phase 2/3 forecast byte-for-byte (test).
W6  Honest provenance. Downstream systems are simulated; real inputs are rainfall and soil moisture. Every explanation record, plan and report page states this. Never imply plans were tested on real interventions.
W7  Defaults unchanged. With explain/intervene features off, all Phase 2 and Phase 3 outputs and hashes are byte-identical (test). New API endpoints, WebSocket message types and config sections are additive and default off.
W8  Pre-registration and held-out discipline for Phase 4 evaluation: write docs/EVAL_PROTOCOL_P4.md (definitions, metrics, baselines, seeds, statistics, success and failure criteria) and COMMIT it before any Phase 4 held-out run. Use FRESH seeds: dev {31, 32, 33}, held-out {201..205}; do not reuse the Phase 3 held-out seeds. Held-out runs once with a lock file (eval/heldout_lock_p4.json), reruns need --allow-rerun and are counted in the report. Never tune on held-out seeds.
W9  Statistics: report n and 95% bootstrap CIs (blocked by seed), paired comparisons against baselines, "insufficient n" flags, and list every sweep run. Report results where the system did not beat a baseline.
W10 Same global rules as before: UTC-aware datetimes, SeedSequence-derived RNGs, determinism (same inputs give byte-identical outputs), additive schema/config changes recorded in docs/PHASE4.md, never print or commit keys or tokens, hermetic tests (no network), banned-term hygiene test must keep passing, PowerShell commands only, golden hashes computed in code from canonical bytes, never push, never touch main, never amend or rewrite history, focused commits with explicit staging.
W11 No LLM in the critical path. Explanations are generated deterministically from structure with templates. An optional LLM phrasing hook may exist behind a flag, default off, never needed by any test, and must receive and display the structured facts alongside its text.
W12 Continue through all work items without stopping. Ask only if truly blocked; when you stop say exactly what you need and what you will do meanwhile.

======================================================================
SCOPE
======================================================================
IN SCOPE
  - Trigger-attribution recording inside rollouts (additive, off by default).
  - Explanation engine: failure chains with branching, feedback loops and interacting simultaneous cascades; risk-change attribution; evidence receipts with provenance and trust; link-removal counterfactuals; confidence and abstention; deterministic text.
  - Intervention engine: action library, parameter-patch application with activation delay and duration, effect uncertainty, explicit and propagated side-effects, resource constraints, objective and solvers (greedy, beam, small-case brute force), robustness analyses, value-of-lead-time analysis.
  - API, CLI, optional WebSocket message types (flagged), and a reproducible offline "demo bundle" of JSON for the Assam hero scenario.
  - Phase 4 evaluation (truth-based, eval layer): explanation accuracy and faithfulness, counterfactual fidelity against a truth simulator with the same intervention applied, planner regret vs baselines, robustness under faults, generalisation to north_bank_assam.
  - Docs, generated requirement-matrix update, generated API contract and JSON schemas for the frontend.
OUT OF SCOPE (Phase 5): the React UI, map visuals, pitch deck, demo video. Provide data and contracts the UI can consume; build no UI.

======================================================================
DESIGN
======================================================================

5.1 PACKAGE LAYOUT
  backend/app/forecast/ (additive only)
    trace.py        TriggerTrace recorder hooked into rollout.py (off by default)
  backend/app/explain/
    chains.py       trigger graph, most-probable chains, branching, loops, concurrent cascades
    attribution.py  risk-change attribution (analytic + common-random-number ablation)
    receipts.py     evidence receipts per link and per driver
    confidence.py   explanation confidence, abstention rules
    text.py         templates, lints, fact consistency
    records.py      ExplanationRecord, ChainLink models (additive schemas)
    log.py          risk-change log (bounded, deterministic)
  backend/app/intervene/
    actions.py      action models, loader/validator for configs/interventions.yaml
    patches.py      parameter patches, activation timing, effect uncertainty
    evaluate.py     rollouts with do(action) under common random numbers, outcome metrics, side effects
    solver.py       greedy (lazy), beam, brute-force; objective and constraints
    robust.py       sensitivity to assumed effects, model uncertainty, noise seeds
    timing.py       value-of-lead-time and cost-of-waiting analysis
    records.py      InterventionPlan, PlanOutcome, SideEffect, ResourceUse models
  backend/app/eval/ (truth allowed)
    truth_sim.py    re-simulate the latent generator with the same patches applied
    explain_eval.py explanation accuracy and faithfulness
    plan_eval.py    counterfactual fidelity, regret, baselines
  scripts/explain.py, plan_interventions.py, eval_phase4.py, build_demo_bundle.py, export_schemas.py
  configs/interventions.yaml
  docs/PHASE4.md, docs/EXPLAINER.md, docs/INTERVENTIONS.md, docs/EVAL_PROTOCOL_P4.md, docs/EVALUATION_P4.md, docs/API_CONTRACT.md
  frontend/public/phase4/ (small demo-bundle JSON) and frontend/public/schemas/ (generated JSON Schemas)

5.2 TRIGGER TRACE (forecast/trace.py, additive and off by default)
- During rollouts, when a node first crosses a stress level (watch/high/critical) in rollout r at time t, record: the node, the level, t, the per-term contributions to its stress update at that step (each lagged parent term, rain/soil feature terms, bias, noise), and the dominant contributor (largest positive contribution). Store compactly (arrays, not Python objects) for the nodes and levels requested; bounded memory.
- This reuses the Phase 2 dominant-parent statistics but at path level. Default off: with tracing disabled the rollout must be byte-identical to before (test). With tracing on, the sampled trajectories must be identical too (tracing must not consume random numbers).

5.3 FAILURE CHAINS (explain/chains.py)
- Trigger graph: nodes are (node, level) events; a directed edge u -> v with weight p_link = P(u was v's dominant trigger | v crossed), with timing stats (lag between crossings, p10/p50/p90), from the trace over rollouts in which v crossed.
- Most-probable chain per target (zone cascade-critical, any critical node, city): walk back from the target through dominant triggers to root causes (the rain/upstream/soil drivers), producing an ordered chain of stages with: node, level, probability of occurring within 72h, ETA quantiles (p10/p50/p90, conditional and unconditional with censoring), and for each link: u, v, lag, learned weight (signed), edge confidence, p_link, how long the edge has been active (EdgeBook), the parent's current estimated stress with its uncertainty.
- Branching: report alternative branches whose probability exceeds a configurable floor, as a tree, not one line.
- Feedback loops: detect strongly connected components in the trigger graph with a probability floor; for each loop report the participating links and an amplification estimate (same rollouts with and without the loop's weakest link removed, paired by common random numbers), and flag it. Clipping must keep loops bounded; test that.
- Simultaneous cascades: identify disconnected or weakly connected root clusters active in the same horizon; for nodes where chains converge, report the interaction effect (joint P(critical) vs the value implied by either chain alone, estimated by paired ablation of each root's influence). State the number of rollouts and CI.
- Zone and city chains use the SAME rollouts as the Phase 2 aggregation so dependence structure is preserved.

5.4 RISK-CHANGE ATTRIBUTION (explain/attribution.py)
- Trigger: whenever a zone or city risk state changes, or its P(cascade-critical within 72h) moves by more than a configured amount between consecutive forecasts, create an ExplanationRecord for that change (bounded log).
- Method A (cheap, analytic): decompose the change in the expected stress trajectory of the key nodes into additive contributions: new observations (grouped by source and zone, weighted by trust), updated parent states through learned edges (term by term), changed rain/soil precursors, changed outlook, and estimator uncertainty change. Check additivity: contributions must sum to the total change within tolerance in the near-linear regime (test; report the residual when clipping or thresholds break linearity, never hide it).
- Method B (faithful, paired re-rollout): for the top-k candidate drivers from method A, re-run rollouts with common random numbers after RESETTING that driver to its previous-forecast value (evidence group reset to prior belief; edge weight to previous value; precursor feature to previous value) and report the paired change in P(cascade-critical by 24h and 72h) and in median time-to-critical with bootstrap CIs. This answers "how much of the change was due to this driver".
- Drivers are typed: observation_group, learned_edge, precursor_feature, outlook, uncertainty. Each carries contribution with CI, direction, evidence receipt (5.5) and a plain-language label from templates.
- Rank stability: the top-3 drivers should be stable under different noise seeds; compute and report stability (Jaccard of top-k across seeds). If unstable, the record says "attribution unstable" and lowers its confidence.

5.5 EVIDENCE RECEIPTS (explain/receipts.py)
For every chain link and every driver, a receipt with: observation ids behind the parent node's state in the last window (from the ledger), their sources, source_kind (real | simulated | disaggregated), trust at the time, quality flags (gated, flatline, late), arrival times; the edge's learning evidence (first seen, current weight and confidence, number of updates, drift events touching it); the paired link-removal effect (ΔP and Δ time-to-critical with CI) computed lazily and cached; and a provenance line that says plainly when a link's parent is a simulated stream. Every referenced id must exist in the ledger and have arrival_time <= issued_at (test).

5.6 CONFIDENCE, UNCERTAINTY AND ABSTENTION (explain/confidence.py)
- Explanation confidence in [0,1] combines: evidence quality of the nodes involved, edge confidences along the chain, rollout-based link usage probability, attribution stability, and drift state of the edges. Document the formula.
- Graceful degradation: when evidence quality is low, the explanation keeps working but says so, shows wider ETA intervals, and drops to "low confidence". When attribution is not identifiable (for example two drivers perfectly correlated, or unstable ranks), say "cannot separate X from Y" instead of picking one. When no chain reaches the probability floor, say "no coherent cascade above threshold" rather than inventing one.
- Under injected faults (the existing FaultInjector) explanations must remain valid, flag the affected evidence, and show the confidence drop. Test it.

5.7 TEXT (explain/text.py)
- Deterministic templates keyed by template_id, filled from ExplanationRecord fields. Examples of the required hedged style: "Heavy upstream rain and saturated soil are estimated to raise embankment stress in zone Z; this is the largest contributor to the rise in P(critical within 72h) from 18% to 41% (paired estimate, n=300)." Use only hedged verbs for model-based claims ("is estimated to", "under the learned model", "the model links").
- Lints (tests): hedging rules; numbers match the structure; every sentence maps to a record field or template id; no sentence about a simulated stream reads as real; text length bounded; deterministic output.

5.8 INTERVENTION MODEL (intervene/actions.py, patches.py, configs/interventions.yaml)
Action definition (all fields validated at load, clear errors):
  id, name, system(s) and scope (node pattern or zone), parameters, effect patches, side-effect patches, resource costs (vector over resource types), earliest start offset, activation delay (hours until effect), duration (hours), max units, exclusivity group, availability by zone, provenance of every number (assumed | expert_estimate_needed | grounded_category), grounded_in (list of Assam report source tags for the category only).
Patch types (applied to the ForecastModel inside rollouts via the Phase 2 intervention hook, with no change to the baseline path):
  scale_term(node, term, factor)         e.g. reduce the rain-to-embankment gain
  add_bias(node, delta)                   e.g. a standing stress offset
  scale_edge(u, v, factor)                e.g. diversion weakens an overflow-to-transport link
  add_edge(u, v, weight, lag)             e.g. evacuation adds stress to transport and emergency_response
  cap_stress(node, max_value)             e.g. surge capacity limiting a node's stress
  exposure_change(zone, factor)           e.g. evacuation reduces demand on health and emergency_response
Every action has a benefit patch set AND a side-effect patch set. Side-effects therefore propagate through the learned cascade engine like anything else, in addition to being listed explicitly. Placeholder action categories to define (names only; magnitudes are assumptions to be marked as such and reviewed by me): deploy pumps or dewatering (river_embankment), embankment reinforcement or sandbagging (river_embankment), traffic diversion or controlled road closure (transport), rail service diversion (transport), backup power or priority restoration (power), mobile communications cover (comms), medical surge capacity and pre-positioned supplies (health), ambulance and rescue pre-positioning (emergency_response), staged evacuation to relief camps (reduces exposure on health/emergency_response, ADDS stress on transport and on relief-camp capacity), early school closure (reduces transport load, small side-effect on emergency_response). Choose categories that exist in the configured systems of each city; actions referencing missing systems are skipped with a logged warning (both configs must run with zero code changes).
Effect uncertainty: each effect size is a distribution (for example a triangular or beta around the assumed value with configurable spread). Draw it per rollout from the NoiseBank so plan outcomes include effect uncertainty, with the same draws reused across plans (common random numbers).
Timing: an action committed at decision time t0 takes effect from t0 + start_offset + activation_delay for duration hours. Plans are evaluated over the same 72-hour horizon as the forecast.

5.9 EVALUATING A PLAN (intervene/evaluate.py)
- evaluate(plan, baseline_rollouts, noise_bank) returns paired outcomes versus doing nothing: per zone and city, change in P(cascade-critical by 24/48/72h), change in time-to-critical quantiles (unconditional and conditional), change in expected cascade-critical zone-hours (the primary loss), tail metric (90th percentile of cascade-critical hours or CVaR), and "cascade broken" flags: a chain link's usage probability falls below its floor, or a zone's cascade-critical probability drops under the mapper's CRITICAL threshold.
- Side effects: list every node whose stress distribution gets WORSE (paired change in P(reach high/critical) with CI), ordered by harm, separating explicit patches from effects propagated through learned edges. Report net benefit = loss reduction minus weighted side-effect harm minus cost penalty (weights in config, documented).
- Per-link effect: for each link of the baseline chain, report how the plan changes its usage probability and timing ("which link does this action break?").
- Result must be deterministic and cached by plan hash + noise key.

5.10 SOLVER (intervene/solver.py)
- Inputs: candidate actions (instantiated per eligible zone/target), resource budgets (vector, optionally time-varying availability), constraints (exclusivity groups, max units, zone caps, earliest starts), objective weights, risk attitude (expected loss or CVaR), horizon, rollout budgets.
- Algorithms: (a) lazy greedy by marginal net benefit per unit of cost (recompute marginals only when needed); (b) beam search of small width; (c) exact brute force for tiny instances (for tests and optimality-gap reporting). All use the SAME NoiseBank. Screening with fewer rollouts (config, e.g. 100) then re-evaluation of the top-k plans with more (config, e.g. 500); report the rollout counts.
- Output: ranked list of feasible plans, each with actions and start times, resource use vs budget, outcome versus do-nothing with paired CIs, side-effect list, robustness summary, and an explanation of why it was chosen (marginal gains in the order actions were added). Always include the do-nothing plan and the best single action for reference.
- Constraints are hard: no plan may exceed any budget or violate exclusivity (test with adversarial inputs, including zero budget and infeasible cases returning an explicit "no feasible plan" record, not an empty crash).
- Respect compute budgets: measure and report solve time; provide a --fast configuration for interactive use.

5.11 ROBUSTNESS AND TIMING (intervene/robust.py, timing.py)
- Effect sensitivity: re-evaluate the top plans while scaling every assumed effect size by factors (default 0.5, 0.75, 1.0, 1.25, 1.5) and report whether plan ranking and the "cascade broken" conclusion survive; flag plans whose benefit depends on optimistic assumptions.
- Model uncertainty: re-evaluate with per-rollout edge weights drawn from their learned uncertainty (EdgeBook confidence / coefficient covariance), so a plan relying on a weak or recent edge is flagged.
- Noise stability: plan ranking stability across independent noise seeds.
- Value of lead time: for the recommended plan, evaluate the same actions started later by 0, 3, 6, 12, 24 hours and report the benefit curve (cost of waiting) and the latest start time that still keeps the benefit above a configured fraction. This connects early warning to action and must be a headline output.

5.12 OUTPUT RECORDS, API, CLI, DEMO BUNDLE
- Schemas (additive, in records.py files): ExplanationRecord (id, issued_at, subject, risk_state_from/to, probability_before/after, drivers[], chain tree, loops[], concurrent_clusters[], confidence, abstentions[], provenance_mix, disclosure strings, template_id, text), ChainLink, Driver, EvidenceReceipt; Action, ActionInstance, InterventionPlan, PlanOutcome, SideEffect, ResourceUse, Assumption. Serialise canonically (sorted keys, rounded floats) so golden hashes work.
- API (additive, default behaviour of existing endpoints unchanged):
    GET  /explain/latest?city=&seed=&zone=          current chain and drivers for a zone or the city
    GET  /explain/changes?city=&seed=&limit=        risk-change log
    GET  /explain/link?u=&v=&city=&seed=            evidence receipt and removal effect for one link
    GET  /intervene/actions?city=                   action library including the Assumptions register
    POST /intervene/plan                            body: budgets, constraints, objective, mode (fast|full) -> ranked plans
    POST /intervene/evaluate                        body: explicit plan -> paired outcomes vs do-nothing
    WS   /ws/stream?...&explain=1&plan=1            adds "explanation" and "plan" message types at forecast cadence (default off)
- CLI: scripts/explain.py (print chain and drivers at a chosen time), scripts/plan_interventions.py (budget flags, prints ranked plans, side-effects, robustness, value-of-lead-time, assumptions banner). Banners always state: downstream streams simulated; action effects assumed; estimates under the learned model.
- Demo bundle: scripts/build_demo_bundle.py produces a deterministic, small, versioned set of JSON files for the Assam hero window (fixed seed, anchor_mode=off): the sequence of forecast snapshots at a coarse cadence, the risk-change explanation records, the chain at key moments (lead, onset, peak), and plan comparisons (do-nothing vs best plan, value-of-lead-time curve), written to frontend/public/phase4/. Include provenance, hashes and the commit. This lets the Phase 5 UI run fully offline.
- scripts/export_schemas.py writes JSON Schemas for all public models to frontend/public/schemas/ and docs/API_CONTRACT.md (generated, not hand-typed).

5.13 PHASE 4 EVALUATION (eval layer; truth allowed; pre-registered per W8)
A. Explanation accuracy (synthetic cities; generator knows the true propagation): for each true cascade-critical episode and each true node crossing, the true dominant parent is derived from the planted graph and latent trajectories (eval/explain_eval.py). Metrics: top-1 dominant-parent accuracy; chain link precision/recall/F1 against true cascade paths; stage-order agreement (rank correlation); ETA error of stages; fraction of true root causes found. Compare with baselines: random topology-respecting path, prior-graph shortest path, correlation-based attribution, and "static" explanation without evidence. Report n and CIs.
B. Faithfulness: deletion test (removing the top-ranked driver by paired re-rollout reduces P(critical) more than removing the lowest-ranked or a random driver; report the rank-vs-effect rank correlation), stability of top-k across noise seeds, and a sufficiency check.
C. Counterfactual fidelity: for scenarios and candidate plans, compare the planner's PREDICTED paired outcomes (learned model) with REALISED outcomes obtained by re-running the generator's latent dynamics with the same patches and the same noise (eval/truth_sim.py). Implement truth_sim by the least invasive route: an additive optional `patches` argument to the generator whose default leaves outputs byte-identical (test), or a minimal latent re-simulation in eval/ if that is cleaner; record the route in docs/PHASE4.md. Metrics: sign agreement of predicted vs realised benefit, rank correlation of plan orderings, calibration of predicted benefit (predicted vs realised with CI), and the realised "cascade broken" rate for plans the system claims break the cascade. Make clear in the report that the truth simulator applies the SAME assumed effect patches, so this tests the learned MODEL's counterfactual fidelity, not the realism of the assumed action effects.
D. Decision quality: regret of the planner's chosen plan vs the best plan in the candidate set under the truth simulator; compare against: do-nothing, random feasible plan, "treat the highest-risk node" heuristic, static priority order (always the same action first), and brute-force optimum on small instances (optimality gap of greedy and beam). Also compare the full planner against a planner that ignores side-effects, to show it avoids net harm. Tune nothing on held-out seeds; each baseline gets the same budget and the same rollout counts.
E. Robustness: repeat A to D on a subset of faulted replays (dropout, spike, feed delay, spam burst) and on north_bank_assam with all settings frozen. Report degradation and whether low-confidence flags fired when they should.
F. Real-scenario illustration (Assam hero window, anchor_mode=off): produce the chain and plans at lead, onset and peak, label them illustrative, and show how the best plan's benefit decays with the start delay. Do not claim real-world validation.
G. Seeds and sizing: dev {31,32,33}, held-out {201..205}; size runs from measured costs; reduce held-out seeds, duration, cadence, rollouts in that order if needed and record it.

5.14 DOCS (generated where possible)
- docs/EXPLAINER.md: method, equations, attribution additivity and its limits, confidence formula, abstention rules, language rules and lints.
- docs/INTERVENTIONS.md: action library, Assumptions register (every number, its provenance and spread), solver, objective weights, robustness analyses, how to change an assumption.
- docs/EVALUATION_P4.md: generated from cached results, with n, CIs, "what this does NOT show" per table, limitations (assumed effects, simulated downstream systems, single real event, circularity between planted graph and learned graph, truth simulator uses the same patch semantics), held-out rerun count, post-hoc corrections.
- Update docs/REQUIREMENTS_MATRIX.md (regenerate): rows 6 and 7 now carry real evidence, headline numbers with n and CI, and honest caveats.

======================================================================
TESTS (hermetic, deterministic; pytest-randomly must still pass)
======================================================================
Trace and chains
 P1  Trace off: rollouts byte-identical to Phase 3; trace on: trajectories identical (no RNG consumption).
 P2  Chain extraction on hand-built graphs (A -> B -> C, branching A -> {B, C}, feedback B <-> C) with known lags: correct order, probabilities, ETAs within tolerance.
 P3  Loops: detected, amplification estimate positive for a reinforcing loop, stress stays within [0,1].
 P4  Simultaneous cascades: two roots converging on a shared node give the expected interaction effect; independent roots give about zero.
 P5  Censoring and conditional/unconditional quantiles are labelled and consistent.
Attribution and evidence
 P6  Additive decomposition sums to the total change in the linear regime; residual reported otherwise.
 P7  Paired re-rollout attribution is deterministic; removing the true driver in a hand-built scenario ranks it first; random drivers rank lower.
 P8  Receipts: every id exists in the ledger with arrival_time <= issued_at; provenance and trust fields correct; simulated parents flagged.
 P9  Confidence falls with evidence quality; abstention rules fire (unidentifiable drivers, no coherent cascade, unstable ranks).
 P10 Text: hedging lint, number-consistency lint, determinism, no real/simulated confusion.
 P11 Risk-change log is bounded and deterministic.
Interventions
 P12 Config validation: bad actions fail with clear errors; missing-system actions are skipped with warnings; both cities load.
 P13 Each patch type changes the targeted quantity in the intended direction in a controlled micro-model; activation delay and duration respected.
 P14 Do-nothing plan reproduces the baseline forecast byte-for-byte; common random numbers give lower paired-difference variance than independent sampling (measure in a test).
 P15 Side effects: an evacuation-like action increases transport stress and the side-effect list reports it, separated into explicit vs propagated.
 P16 Constraints: budgets, exclusivity, max units, zone caps, earliest starts never violated, including adversarial inputs, zero budget and infeasible cases (explicit "no feasible plan").
 P17 Solver: greedy and beam match brute force within a stated gap on tiny instances; the gap is reported; results deterministic.
 P18 Robustness: sensitivity and model-uncertainty runs produce stable, documented outputs; plans that depend on optimistic effects are flagged in a constructed case.
 P19 Value of lead time: benefit is non-increasing with start delay on a clean chain scenario; latest-effective-start computed correctly.
 P20 Plan evaluation is cached and deterministic by plan hash and noise key.
Leakage, isolation, defaults
 P21 Import and file-reference isolation for explain/ and intervene/ (no eval, no truth, no label files).
 P22 Canary: garbage after time T leaves all explanation records and plans issued at or before T byte-identical (both configs).
 P23 With explain/intervene off, Phase 2 and Phase 3 hashes are unchanged; new endpoints and WS types are absent by default.
 P24 The generator patch hook (if added) leaves default outputs byte-identical.
API and contracts
 P25 Endpoint shapes validate against the generated JSON Schemas; error cases (missing results, infeasible plan, bad budget) return clear 4xx/200-with-status as documented.
 P26 Demo bundle is deterministic (hash), small (size budget in config) and loads without network.
 P27 Schema export is stable; docs/API_CONTRACT.md is generated from code.
Evaluation harness (Phase 4)
 P28 truth_sim reproduces the generator's unpatched output exactly; with a patch it changes the intended nodes; the same patch semantics as the planner (shared test vectors).
 P29 Explanation-accuracy metrics on hand-built cases with known answers; regret and rank-correlation metrics on toy plan sets; sanity predictors: a planner that picks the truly best plan has zero regret, a random planner has positive expected regret, a do-nothing planner has regret equal to the best benefit.
 P30 Phase 4 held-out lock behaviour; hygiene test passes; no keys or tokens tracked; suite runs offline.
Report the starting test count, every change with reasons, in tests/PHASE4_TEST_REPORT.md written from real output. Run the full suite twice consecutively and once in random order. Keep heavy sweeps out of the unit suite (tiny scenarios there; full evaluation runs through scripts).

======================================================================
WORK ORDER (tick each in docs/PHASE4.md)
======================================================================
H0  Step 0 verification, branch feat/explain-intervene, measured costs, docs/PHASE4.md.
H1  Additive schemas, configs/interventions.yaml loader and validator, Assumptions register, action library for both cities; tests P12, P24 (schema parts).
H2  forecast/trace.py instrumentation; tests P1.
H3  explain/chains.py (chains, branching, loops, concurrent cascades) with common-random-number link ablation; tests P2 to P5.
H4  explain/attribution.py, receipts.py, confidence.py, text.py, log.py; tests P6 to P11.
H5  intervene/actions.py, patches.py, evaluate.py (paired outcomes, side effects, per-link effects); tests P13 to P15, P20.
H6  intervene/solver.py, robust.py, timing.py; tests P16 to P19.
H7  API, CLI, optional WS types, demo bundle, schema export, API contract; tests P21 to P23, P25 to P27.
H8  Phase 4 evaluation: (a) write and COMMIT docs/EVAL_PROTOCOL_P4.md and the truth_sim route (P28, P24 generator part, P29) before any held-out run; (b) dev runs on seeds {31,32,33}, fix real bugs with failing test first; (c) freeze, write eval/heldout_lock_p4.json, run held-out {201..205} once plus the held-out-topology run; (d) real-scenario illustration.
H9  Generate docs/EVALUATION_P4.md, update docs/REQUIREMENTS_MATRIX.md, docs/EXPLAINER.md, docs/INTERVENTIONS.md, README commands.
H10 Final verification: full suite twice plus random order, tests/PHASE4_TEST_REPORT.md, git status clean, main untouched, focused commits on feat/explain-intervene (suggested grouping: schemas+config; trace; chains; attribution+text; patches+evaluate; solver+robust+timing; API+CLI+bundle; eval+protocol; docs and results).

======================================================================
DEFINITION OF DONE
======================================================================
- For the Assam hero window on both cities, the CLI prints: the current risk state and top drivers for each zone, the predicted failure chain as a tree with probabilities, ETAs, learned lags and weights, evidence receipts, loops and interacting cascades; and a ranked set of intervention plans under a given budget with paired outcomes versus doing nothing, side-effects, robustness to assumed effects and model uncertainty, and the value-of-lead-time curve, all with the honesty banners.
- Explanations and plans degrade gracefully and say so when evidence is poor; they abstain when attribution is not identifiable.
- Pre-registered Phase 4 evaluation exists with n and CIs: explanation accuracy and faithfulness vs baselines, counterfactual fidelity against the truth simulator, planner regret vs baselines and brute force, robustness under faults, held-out topology result, and every result where the system did NOT do well.
- All tests P1 to P30 pass twice in a row and in random order; canary proves no future information; with features off, earlier phases' outputs are byte-identical.
- No ground-truth, label or eval code is reachable from forecast/, explain/ or intervene/. No LLM is needed anywhere.
- The Assumptions register lists every assumed action effect with its provenance; docs state that action effects are assumed and plan outcomes are model estimates.
- The demo bundle, JSON Schemas and docs/API_CONTRACT.md exist so Phase 5 can build the UI offline.
- git status clean on feat/explain-intervene; main untouched; nothing pushed.

FINAL REPORT (in the chat when done)
List: files created or changed; schema and config additions; the assumptions register; measured costs and how sizes were chosen; test count before and after with reasons; the headline tables (explanation accuracy and faithfulness vs baselines; counterfactual fidelity; regret vs baselines; robustness; held-out topology) with n and CIs for dev and held-out; the Assam illustration outputs with caveats; held-out rerun count and any post-hoc corrections; deviations from this prompt and why; disappointing results; and what Phase 5 (UI, demo script, pitch) needs from your interfaces.
```
