"""Command-Line Interface for Counterfactual Interventions & Solvers (Phase 4).

Prints:
  - Budget-constrained ranked intervention plans.
  - Paired outcomes vs doing nothing (delta P(critical), delta zone-hours, broken links).
  - Explicit and propagated harmful side-effects.
  - Robustness to assumed effect scaling and learned model uncertainty.
  - Value of lead time and cost of waiting curve.
  - Mandatory honesty banners: downstream streams simulated; action effects assumed.
"""
from __future__ import annotations

import argparse
from datetime import timedelta
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.city_config import load_city_config
from backend.app.forecast.config import ForecastConfig
from backend.app.forecast.engine import ForecastEngine
from backend.app.intervene.actions import (
    build_assumptions_register,
    filter_actions_for_city,
    load_interventions_config,
)
from backend.app.intervene.robust import (
    evaluate_effect_sensitivity,
    evaluate_model_uncertainty,
)
from backend.app.intervene.solver import generate_candidate_pool, solve_interventions
from backend.app.intervene.timing import evaluate_value_of_lead_time
from backend.app.replay.clock import ReplayClock
from backend.app.replay.stream import ReplayStream, StreamView
from backend.app.synth.generator import generate_city

HONESTY_BANNER = """
================================================================================
THE 72-HOUR WARNING — COUNTERFACTUAL INTERVENTIONS (PHASE 4)
HONESTY DISCLOSURE:
  - There is NO empirical real-world data on intervention effectiveness in this scenario.
  - Every numerical effect size, cost, and delay is an ASSUMPTION or EXPERT ESTIMATE.
  - Downstream systems are SIMULATED; outcomes are ESTIMATED under the learned model.
================================================================================
"""


def main():
    parser = argparse.ArgumentParser(description="Solve and evaluate counterfactual interventions.")
    parser.add_argument("--city", default="upper_assam", help="City configuration identifier")
    parser.add_argument("--seed", type=int, default=1, help="Simulation seed")
    parser.add_argument("--rain-window", default="peak", help="Rain window scenario (lead|onset|peak)")
    parser.add_argument("--anchor", default="off", help="Anchor mode (off|on)")
    parser.add_argument("--hour", type=float, default=24.0, help="Replay clock hour (decision time)")
    parser.add_argument("--budget-crews", type=float, default=None, help="Crews budget limit")
    parser.add_argument("--budget-boats", type=float, default=None, help="Boats budget limit")
    parser.add_argument("--budget-pumps", type=float, default=None, help="Pumps budget limit")
    parser.add_argument("--budget-generators", type=float, default=None, help="Generators budget limit")
    parser.add_argument("--budget-cost", type=float, default=None, help="Financial cap in Lakhs")
    parser.add_argument("--method", default="greedy", choices=["greedy", "beam", "brute_force"], help="Solver method")
    parser.add_argument("--fast", action="store_true", help="Run with reduced screening rollouts for interactive speed")
    parser.add_argument("--output", default=None, help="Optional JSON output filepath")
    args = parser.parse_args()

    cfg_path = REPO_ROOT / "configs" / f"{args.city}.yaml"
    if not cfg_path.exists():
        print(f"Error: City config not found at {cfg_path}", file=sys.stderr)
        sys.exit(1)

    city_cfg = load_city_config(cfg_path)
    obs, _ = generate_city(
        city_cfg,
        args.seed,
        max(72, int(args.hour + 24)),
        anchor_mode=args.anchor,
    )
    stream = ReplayStream(obs)
    clock = ReplayClock(city_cfg.start_time_utc)
    clock.advance(args.hour)
    view = StreamView(stream, clock.now)

    engine = ForecastEngine(
        city_config=city_cfg,
        forecast_config=ForecastConfig(rollouts=150),
        global_seed=args.seed,
        anchor_mode=args.anchor,
    )
    _ = engine.step(clock.now, view, enable_trace=True)

    icfg = load_interventions_config()
    budgets = dict(icfg.default_budgets)
    if args.budget_crews is not None:
        budgets["crews"] = args.budget_crews
    if args.budget_boats is not None:
        budgets["boats"] = args.budget_boats
    if args.budget_pumps is not None:
        budgets["pumps"] = args.budget_pumps
    if args.budget_generators is not None:
        budgets["generators"] = args.budget_generators
    if args.budget_cost is not None:
        budgets["cost_lakh"] = args.budget_cost

    acts = filter_actions_for_city(icfg.actions, city_cfg)
    acts_by_id = {a.id: a for a in acts}
    zone_ids = [z.id for z in city_cfg.zones]
    candidates = generate_candidate_pool(acts, zone_ids=zone_ids)

    screening_n = 50 if args.fast else 100
    full_n = 100 if args.fast else 300

    plans, elapsed = solve_interventions(
        candidates=candidates,
        actions_by_id=acts_by_id,
        budgets=budgets,
        model=engine.learner.get_model(),
        initial_beliefs={n: (st.mean, st.variance) for n, st in engine.estimator.states.items()},
        baseline_rollouts=engine.last_rollout_results,
        noise_bank=engine.last_noise_bank,
        decision_time=clock.now,
        method=args.method,
        screening_rollouts=screening_n,
        full_rollouts=full_n,
        horizon=48,
    )

    best_plan = next((p for p in plans if p.actions), plans[0] if plans else None)

    print(HONESTY_BANNER)
    print(f"Decision Time:   {clock.now.isoformat()} (+{args.hour:.1f}h into scenario)")
    print(f"City Config:     {args.city} (Seed {args.seed})")
    print(f"Solver Method:   {args.method} ({'fast' if args.fast else 'full'} mode, {elapsed:.2f}s)")
    print(f"Budgets:         {budgets}")

    print("\n--- Ranked Intervention Plans ---")
    for idx, p in enumerate(plans[:3], 1):
        status = "FEASIBLE" if p.feasibility else f"INFEASIBLE ({p.infeasibility_reason})"
        print(f"\n[Rank {p.selection_rank}] {p.plan_id} — {status}")
        print(f"  Rationale: {p.selection_rationale}")
        print(f"  Actions ({len(p.actions)}):")
        for act in p.actions:
            print(f"    - {act.action_id} in {act.zone or 'city'} (offset: +{act.start_time_offset:.1f}h, units: {act.units})")
        print(f"  Cost: {p.total_cost}")
        if p.outcome:
            out = p.outcome
            print(f"  Outcome: Net Benefit: {out.net_benefit:+.2f} (95% CI: [{out.ci_lower:+.2f}, {out.ci_upper:+.2f}])")
            print(f"    P(Critical 72h): {out.p_critical_72h_before*100.0:.1f}% -> {out.p_critical_72h_after*100.0:.1f}% (Delta: {out.delta_p_critical_72h*100.0:+.1f}%)")
            print(f"    Saved Zone-Hours: {out.delta_critical_zone_hours:+.1f}h (Tail CVaR: {out.cvar_critical_zone_hours:.1f}h)")
            print(f"    Cascade Broken: {out.cascade_broken} (Disrupted Links: {out.broken_links})")
            if out.side_effects:
                print(f"    Side Effects ({len(out.side_effects)}):")
                for se in out.side_effects[:3]:
                    print(f"      * [{se.effect_type}] {se.node}: +{se.delta_p_critical*100.0:.1f}% critical ({se.description})")

    # Robustness and Value of Lead Time for best feasible plan
    robustness_data = {}
    lead_time_data = {}
    if best_plan and best_plan.feasibility and best_plan.actions:
        print("\n--- Robustness & Sensitivity Analysis ---")
        sens = evaluate_effect_sensitivity(
            plan=best_plan,
            model=engine.learner.get_model(),
            initial_beliefs={n: (st.mean, st.variance) for n, st in engine.estimator.states.items()},
            baseline_rollouts=engine.last_rollout_results,
            actions_by_id=acts_by_id,
            noise_bank=engine.last_noise_bank,
            n_rollouts=100,
        )
        robustness_data["sensitivity"] = sens
        print(f"  Depends on Optimistic Effects: {sens['depends_on_optimistic_assumptions']}")
        sens_strs = [f"{pt['scaling_factor']}x: {pt['net_benefit']:+.2f}" for pt in sens["scaling_curve"]]
        print(f"  Net Benefit Scaling Curve: {sens_strs}")

        unc = evaluate_model_uncertainty(
            plan=best_plan,
            model=engine.learner.get_model(),
            initial_beliefs={n: (st.mean, st.variance) for n, st in engine.estimator.states.items()},
            baseline_rollouts=engine.last_rollout_results,
            actions_by_id=acts_by_id,
            noise_bank=engine.last_noise_bank,
            n_rollouts=100,
        )
        robustness_data["model_uncertainty"] = unc
        print(f"  Model Uncertainty Gap: {unc['robustness_gap']:+.2f} (Robust: {unc['robust']})")

        print("\n--- Value of Lead Time & Cost of Waiting ---")
        lead_analysis = evaluate_value_of_lead_time(
            plan=best_plan,
            model=engine.learner.get_model(),
            initial_beliefs={n: (st.mean, st.variance) for n, st in engine.estimator.states.items()},
            baseline_rollouts=engine.last_rollout_results,
            actions_by_id=acts_by_id,
            noise_bank=engine.last_noise_bank,
            delay_hours=[0.0, 3.0, 6.0, 12.0, 24.0],
            n_rollouts=100,
        )
        lead_time_data = lead_analysis
        print(f"  Cost of Waiting: {lead_analysis['cost_of_waiting_per_hour']:.2f} loss/hour")
        print(f"  Latest Effective Start Delay: +{lead_analysis['latest_effective_start_delay_hours']:.1f}h")
        lead_strs = [f"+{pt['delay_hours']}h: {pt['net_benefit']:+.2f}" for pt in lead_analysis["delay_curve"]]
        print(f"  Benefit Curve by Delay: {lead_strs}")

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        export_payload = {
            "city": args.city,
            "decision_time": clock.now.isoformat(),
            "budgets": budgets,
            "plans": [p.canonical_dict() for p in plans],
            "robustness": robustness_data,
            "value_of_lead_time": lead_time_data,
        }
        out_path.write_text(json.dumps(export_payload, indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nSaved plans and analyses to {out_path}")


if __name__ == "__main__":
    main()
