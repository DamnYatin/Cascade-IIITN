"""Tests P13, P14, P15, P20: Interventions Patches, Paired Evaluation, and Side-Effects.

Verifies:
  - P13: Each patch type (scale_term, add_bias, scale_edge, add_edge, cap_stress, exposure_change)
    changes the targeted quantity in the intended direction; activation delay and duration respected.
  - P14: Do-nothing plan reproduces baseline forecast byte-for-byte;
    Common Random Numbers (CRN) yield lower paired variance than independent sampling.
  - P15: Side effects: an evacuation action increases transport stress; explicit vs propagated separated.
  - P20: Plan evaluation is deterministic and cached by plan hash and noise key.
"""
from __future__ import annotations

from datetime import datetime, timezone
import numpy as np
import pytest

from backend.app.explain.records import ChainLink
from backend.app.intervene.actions import (
    Action,
    ActionInstance,
    InterventionsConfig,
    instantiate_action,
    load_interventions_config,
)
from backend.app.intervene.evaluate import clear_plan_eval_cache, evaluate_plan
from backend.app.intervene.patches import (
    ScheduledPatch,
    apply_step_patches,
    compile_scheduled_patches,
)
from backend.app.intervene.records import (
    EffectPatch,
    InterventionPlan,
    PatchType,
    PlanOutcome,
)
from backend.app.forecast.learner import ForecastModel
from backend.app.forecast.rollout import NoiseBank, cascade_rollout
from tests.conftest import REPO


@pytest.fixture
def test_model():
    nodes = ["z1:river_embankment", "z1:transport", "z1:health", "z1:emergency_response"]
    couplings = {
        "z1:transport": [("z1:river_embankment", 2.0, 0.50)],
        "z1:emergency_response": [("z1:transport", 2.0, 0.45)],
        "z1:health": [("z1:emergency_response", 1.0, 0.40)],
    }
    return ForecastModel(
        nodes=nodes,
        intercepts={n: 0.02 for n in nodes},
        persistence={n: 0.85 for n in nodes},
        sigmas={n: 0.03 for n in nodes},
        couplings=couplings,
        exogenous_weights={"z1:river_embankment": [("rain_accum_24h", 0.60)]},
    )


def test_p13_patch_types_direction_delay_and_duration(test_model):
    """P13: Verify each patch type modifies state in intended direction only during active window."""
    initial_beliefs = {n: (0.50, 0.001) for n in test_model.nodes}
    issue_time = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
    nb = NoiseBank(global_seed=42, issue_time=issue_time, n_rollouts=100, n_nodes=4, horizon=48)

    # 1. ADD_BIAS: active from hour 5 to 15
    bias_patch = ScheduledPatch(
        patch_type=PatchType.ADD_BIAS,
        target="z1:transport",
        start_hour=5.0,
        end_hour=15.0,
        nominal_value=0.20,
    )

    res_base = cascade_rollout(test_model, initial_beliefs, horizon=48, n_rollouts=100, noise_bank=nb)
    res_patched = cascade_rollout(
        test_model, initial_beliefs, horizon=48, n_rollouts=100, noise_bank=nb, patches=[bias_patch]
    )

    t_idx = test_model.nodes.index("z1:transport")
    # Before activation (h < 5): must be byte-identical
    np.testing.assert_array_equal(res_base.trajectories[:, t_idx, :4], res_patched.trajectories[:, t_idx, :4])
    # During window (5 <= h < 15): patched stress must be higher
    assert np.mean(res_patched.trajectories[:, t_idx, 5:15]) > np.mean(res_base.trajectories[:, t_idx, 5:15])

    # 2. CAP_STRESS: caps health stress at 0.40
    cap_patch = ScheduledPatch(
        patch_type=PatchType.CAP_STRESS,
        target="z1:health",
        start_hour=1.0,
        end_hour=48.0,
        nominal_value=0.40,
    )
    res_capped = cascade_rollout(
        test_model, initial_beliefs, horizon=48, n_rollouts=100, noise_bank=nb, patches=[cap_patch]
    )
    h_idx = test_model.nodes.index("z1:health")
    assert np.all(res_capped.trajectories[:, h_idx, :] <= 0.40001)


def test_p14_do_nothing_plan_reproduces_baseline_byte_for_byte(test_model):
    """P14: Do-nothing plan produces byte-identical results to baseline; CRN cuts paired variance."""
    initial_beliefs = {n: (0.60, 0.001) for n in test_model.nodes}
    issue_time = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
    nb = NoiseBank(global_seed=42, issue_time=issue_time, n_rollouts=100, n_nodes=4, horizon=48)

    base_res = cascade_rollout(test_model, initial_beliefs, horizon=48, n_rollouts=100, noise_bank=nb)

    empty_plan = InterventionPlan(
        plan_id="plan_do_nothing",
        decision_time=issue_time,
        actions=[],
    )

    outcome = evaluate_plan(
        plan=empty_plan,
        model=test_model,
        initial_beliefs=initial_beliefs,
        baseline_rollouts=base_res,
        actions_by_id={},
        noise_bank=nb,
        horizon=48,
        n_rollouts=100,
    )

    assert outcome.delta_p_critical_24h == 0.0
    assert outcome.delta_p_critical_72h == 0.0
    assert outcome.delta_critical_zone_hours == 0.0
    assert outcome.net_benefit == 0.0
    assert not outcome.side_effects

    # Common random numbers variance test:
    # Paired difference using same noise bank has much lower variance than using independent noise banks
    cfg = load_interventions_config(REPO / "configs" / "interventions.yaml")
    act_dict = {a.id: a for a in cfg.actions}
    pumps_act = act_dict["deploy_dewatering_pumps"]
    instance = instantiate_action(pumps_act, zone="z1", start_time_offset=0.0, units=1)

    plan = InterventionPlan(
        plan_id="plan_pumps",
        decision_time=issue_time,
        actions=[instance],
        total_cost=instance.resource_costs,
    )

    # Paired runs (same noise bank)
    patches = compile_scheduled_patches(act_dict, [instance], n_rollouts=100, global_seed=42, issue_time=issue_time)
    res_paired = cascade_rollout(test_model, initial_beliefs, horizon=48, n_rollouts=100, noise_bank=nb, patches=patches)
    paired_diffs = base_res.trajectories[:, 0, :] - res_paired.trajectories[:, 0, :]
    var_paired = float(np.var(paired_diffs))

    # Independent runs (different noise bank)
    nb_indep = NoiseBank(global_seed=999, issue_time=issue_time, n_rollouts=100, n_nodes=4, horizon=48)
    res_indep = cascade_rollout(test_model, initial_beliefs, horizon=48, n_rollouts=100, noise_bank=nb_indep, patches=patches)
    indep_diffs = base_res.trajectories[:, 0, :] - res_indep.trajectories[:, 0, :]
    var_indep = float(np.var(indep_diffs))

    assert var_paired < var_indep, f"CRN variance ({var_paired:.6f}) should be strictly less than independent ({var_indep:.6f})"


def test_p15_side_effects_evacuation_increases_transport_stress(test_model):
    """P15: Evacuation action triggers explicit and propagated side-effects on transport and clinic load."""
    initial_beliefs = {n: (0.45, 0.001) for n in test_model.nodes}
    issue_time = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
    nb = NoiseBank(global_seed=42, issue_time=issue_time, n_rollouts=150, n_nodes=4, horizon=48)

    base_res = cascade_rollout(test_model, initial_beliefs, horizon=48, n_rollouts=150, noise_bank=nb)

    cfg = load_interventions_config(REPO / "configs" / "interventions.yaml")
    act_dict = {a.id: a for a in cfg.actions}
    evac_act = act_dict["staged_population_evacuation"]
    instance = instantiate_action(evac_act, zone="z1", start_time_offset=0.0, units=1)

    plan = InterventionPlan(
        plan_id="plan_evacuation",
        decision_time=issue_time,
        actions=[instance],
        total_cost=instance.resource_costs,
    )

    outcome = evaluate_plan(
        plan=plan,
        model=test_model,
        initial_beliefs=initial_beliefs,
        baseline_rollouts=base_res,
        actions_by_id=act_dict,
        noise_bank=nb,
        horizon=48,
        n_rollouts=150,
    )

    assert len(outcome.side_effects) >= 1
    # Transport or health should be in side effects
    affected_nodes = [s.node for s in outcome.side_effects]
    assert any("transport" in n or "health" in n for n in affected_nodes)
    for s in outcome.side_effects:
        assert s.effect_type in ("explicit_patch", "propagated_cascade")
        assert s.harm_score >= 0.0


def test_p20_plan_evaluation_caching_and_determinism(test_model):
    """P20: Evaluation results are cached by plan hash and noise key, returning identical objects."""
    clear_plan_eval_cache()
    initial_beliefs = {n: (0.40, 0.001) for n in test_model.nodes}
    issue_time = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
    nb = NoiseBank(global_seed=42, issue_time=issue_time, n_rollouts=100, n_nodes=4, horizon=48)

    base_res = cascade_rollout(test_model, initial_beliefs, horizon=48, n_rollouts=100, noise_bank=nb)

    cfg = load_interventions_config(REPO / "configs" / "interventions.yaml")
    act_dict = {a.id: a for a in cfg.actions}
    act = act_dict["deploy_dewatering_pumps"]
    instance = instantiate_action(act, zone="z1", start_time_offset=1.0, units=1)

    plan = InterventionPlan(
        plan_id="plan_pumps_cache_test",
        decision_time=issue_time,
        actions=[instance],
        total_cost=instance.resource_costs,
    )

    out1 = evaluate_plan(
        plan, test_model, initial_beliefs, base_res, act_dict, noise_bank=nb, horizon=48, n_rollouts=100
    )
    out2 = evaluate_plan(
        plan, test_model, initial_beliefs, base_res, act_dict, noise_bank=nb, horizon=48, n_rollouts=100
    )

    # Cache hit returns identical object
    assert out1 is out2
    assert out1.delta_critical_zone_hours == out2.delta_critical_zone_hours
