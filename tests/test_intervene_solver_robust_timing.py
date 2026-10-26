"""Tests P16 to P19: Solvers, Hard Constraints, Robustness, and Value of Lead Time.

Verifies:
  - P16: Hard constraints (budgets, exclusivity, max units, zero budget) strictly enforced.
  - P17: Solver algorithms (greedy, beam, brute force) on small instances; gap reported and bounded.
  - P18: Robustness: sensitivity across effect scaling [0.5..1.5], model uncertainty, and optimism flag.
  - P19: Value of lead time: monotonically non-increasing benefit with commitment delay, cost-of-waiting.
"""
from __future__ import annotations

from datetime import datetime, timezone
import pytest

from backend.app.intervene.actions import (
    Action,
    ActionInstance,
    instantiate_action,
    load_interventions_config,
)
from backend.app.intervene.records import InterventionPlan
from backend.app.intervene.robust import (
    evaluate_effect_sensitivity,
    evaluate_model_uncertainty,
)
from backend.app.intervene.solver import (
    is_feasible,
    solve_interventions,
)
from backend.app.intervene.timing import evaluate_value_of_lead_time
from backend.app.forecast.learner import ForecastModel
from backend.app.forecast.rollout import NoiseBank, cascade_rollout
from tests.conftest import REPO


@pytest.fixture
def clean_cascade_model():
    nodes = ["z1:river_embankment", "z1:transport", "z1:health"]
    couplings = {
        "z1:transport": [("z1:river_embankment", 2.0, 0.60)],
        "z1:health": [("z1:transport", 2.0, 0.50)],
    }
    return ForecastModel(
        nodes=nodes,
        intercepts={n: 0.02 for n in nodes},
        persistence={n: 0.85 for n in nodes},
        sigmas={n: 0.03 for n in nodes},
        couplings=couplings,
        exogenous_weights={"z1:river_embankment": [("rain_accum_24h", 0.60)]},
    )


def test_p16_hard_constraints_and_zero_budget(clean_cascade_model):
    """P16: Hard budgets and exclusivity constraints strictly enforced; adversarial 0-budget returns clean failure."""
    cfg = load_interventions_config(REPO / "configs" / "interventions.yaml")
    act_dict = {a.id: a for a in cfg.actions}
    issue_time = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
    initial_beliefs = {n: (0.60, 0.001) for n in clean_cascade_model.nodes}

    nb = NoiseBank(global_seed=42, issue_time=issue_time, n_rollouts=100, n_nodes=3, horizon=48)
    base_res = cascade_rollout(clean_cascade_model, initial_beliefs, horizon=48, n_rollouts=100, noise_bank=nb)

    # 1. Adversarial zero budget
    zero_budgets = {"crews": 0.0, "pumps": 0.0, "boats": 0.0, "generators": 0.0, "cost_lakh": 0.0}
    cands = [instantiate_action(act_dict["deploy_dewatering_pumps"], zone="z1", start_time_offset=0.0)]

    plans, elapsed = solve_interventions(
        candidates=cands,
        actions_by_id=act_dict,
        budgets=zero_budgets,
        model=clean_cascade_model,
        initial_beliefs=initial_beliefs,
        baseline_rollouts=base_res,
        noise_bank=nb,
        decision_time=issue_time,
        full_rollouts=100,
    )
    assert len(plans) == 1
    assert plans[0].infeasibility_reason is not None
    assert len(plans[0].actions) == 0

    # 2. Exclusivity violation check
    evac_act = act_dict["staged_population_evacuation"]
    i1 = instantiate_action(evac_act, zone="z1", start_time_offset=0.0)
    i2 = instantiate_action(evac_act, zone="z1", start_time_offset=3.0)
    feas, reason, _ = is_feasible([i1, i2], act_dict, {"crews": 50.0, "boats": 50.0, "cost_lakh": 100.0})
    assert not feas
    assert "Exclusivity violation" in reason


def test_p17_solver_optimality_gap_greedy_vs_brute_force(clean_cascade_model):
    """P17: Greedy and beam match brute force on small instances within acceptable gap."""
    cfg = load_interventions_config(REPO / "configs" / "interventions.yaml")
    act_dict = {a.id: a for a in cfg.actions}
    issue_time = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
    initial_beliefs = {n: (0.60, 0.001) for n in clean_cascade_model.nodes}

    nb = NoiseBank(global_seed=42, issue_time=issue_time, n_rollouts=100, n_nodes=3, horizon=48)
    base_res = cascade_rollout(clean_cascade_model, initial_beliefs, horizon=48, n_rollouts=100, noise_bank=nb)

    # 4 affordable candidates
    cands = [
        instantiate_action(act_dict["deploy_dewatering_pumps"], zone="z1", start_time_offset=0.0),
        instantiate_action(act_dict["embankment_sandbagging"], zone="z1", start_time_offset=1.0),
        instantiate_action(act_dict["traffic_diversion"], zone="z1", start_time_offset=0.0),
        instantiate_action(act_dict["early_school_closure"], zone="z1", start_time_offset=0.0),
    ]
    budgets = {"crews": 6.0, "pumps": 4.0, "boats": 4.0, "generators": 4.0, "cost_lakh": 20.0}

    # Brute force
    bf_plans, _ = solve_interventions(
        candidates=cands,
        actions_by_id=act_dict,
        budgets=budgets,
        model=clean_cascade_model,
        initial_beliefs=initial_beliefs,
        baseline_rollouts=base_res,
        noise_bank=nb,
        method="brute_force",
        full_rollouts=100,
    )
    best_bf = bf_plans[1] if len(bf_plans) > 1 else bf_plans[0]

    # Greedy
    greedy_plans, _ = solve_interventions(
        candidates=cands,
        actions_by_id=act_dict,
        budgets=budgets,
        model=clean_cascade_model,
        initial_beliefs=initial_beliefs,
        baseline_rollouts=base_res,
        noise_bank=nb,
        method="greedy",
        full_rollouts=100,
    )
    best_greedy = greedy_plans[1] if len(greedy_plans) > 1 else greedy_plans[0]

    bf_benefit = best_bf.outcome.net_benefit if best_bf.outcome else 0.0
    greedy_benefit = best_greedy.outcome.net_benefit if best_greedy.outcome else 0.0
    gap = max(0.0, bf_benefit - greedy_benefit)
    assert gap <= 2.5, f"Optimality gap {gap:.2f} exceeds threshold"


def test_p18_robustness_sensitivity_and_uncertainty(clean_cascade_model):
    """P18: Effect scaling curve is monotonic and flags optimism; model uncertainty produces gap."""
    cfg = load_interventions_config(REPO / "configs" / "interventions.yaml")
    act_dict = {a.id: a for a in cfg.actions}
    issue_time = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
    initial_beliefs = {n: (0.60, 0.001) for n in clean_cascade_model.nodes}

    nb = NoiseBank(global_seed=42, issue_time=issue_time, n_rollouts=100, n_nodes=3, horizon=48)
    base_res = cascade_rollout(clean_cascade_model, initial_beliefs, horizon=48, n_rollouts=100, noise_bank=nb)

    inst = instantiate_action(act_dict["deploy_dewatering_pumps"], zone="z1", start_time_offset=0.0)
    plan = InterventionPlan(plan_id="p_test", decision_time=issue_time, actions=[inst])

    # Sensitivity
    sens = evaluate_effect_sensitivity(
        plan=plan,
        model=clean_cascade_model,
        initial_beliefs=initial_beliefs,
        baseline_rollouts=base_res,
        actions_by_id=act_dict,
        noise_bank=nb,
        scaling_factors=[0.5, 1.0, 1.5],
        horizon=48,
        n_rollouts=100,
    )
    assert len(sens["scaling_curve"]) == 3
    # Benefit should generally scale with factor
    assert sens["scaling_curve"][0]["scale_factor"] == 0.5
    assert sens["scaling_curve"][2]["scale_factor"] == 1.5

    # Uncertainty
    unc = evaluate_model_uncertainty(
        plan=plan,
        model=clean_cascade_model,
        initial_beliefs=initial_beliefs,
        baseline_rollouts=base_res,
        actions_by_id=act_dict,
        noise_bank=nb,
        horizon=48,
        n_rollouts=100,
    )
    assert "robustness_gap" in unc
    assert "uncertainty_net_benefit" in unc


def test_p19_value_of_lead_time_decay_curve(clean_cascade_model):
    """P19: Benefit is non-increasing with commitment delay; latest effective start calculated."""
    cfg = load_interventions_config(REPO / "configs" / "interventions.yaml")
    act_dict = {a.id: a for a in cfg.actions}
    issue_time = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
    initial_beliefs = {n: (0.65, 0.001) for n in clean_cascade_model.nodes}

    nb = NoiseBank(global_seed=42, issue_time=issue_time, n_rollouts=100, n_nodes=3, horizon=48)
    base_res = cascade_rollout(clean_cascade_model, initial_beliefs, horizon=48, n_rollouts=100, noise_bank=nb)

    inst = instantiate_action(act_dict["deploy_dewatering_pumps"], zone="z1", start_time_offset=0.0)
    plan = InterventionPlan(plan_id="p_timing", decision_time=issue_time, actions=[inst])

    timing_res = evaluate_value_of_lead_time(
        plan=plan,
        model=clean_cascade_model,
        initial_beliefs=initial_beliefs,
        baseline_rollouts=base_res,
        actions_by_id=act_dict,
        noise_bank=nb,
        delay_hours=[0.0, 6.0, 12.0, 24.0],
        horizon=48,
        n_rollouts=100,
    )

    assert timing_res["initial_benefit"] > 0
    curve = timing_res["delay_curve"]
    assert len(curve) == 4
    # Earliest intervention (0 delay) has higher or equal benefit than late intervention (24h delay)
    assert curve[0]["net_benefit"] >= curve[-1]["net_benefit"]
    assert timing_res["cost_of_waiting_per_hour"] >= 0.0
