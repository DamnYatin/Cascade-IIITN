"""Truth Simulator: Counterfactual Re-simulation of Latent Dynamics under Interventions.

Re-simulates the generator's true latent dynamics under identical exogenous inputs
and process noise (Common Random Numbers) with intervention patches applied.

Used exclusively in the evaluation layer (eval/) to measure:
  - Counterfactual fidelity of the learned model's predicted benefit
  - Planner regret vs best possible plan under true latent dynamics
  - Cascade-breaking verification in ground truth
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from ..city_config import CityConfig
from ..intervene.actions import Action, load_interventions_config, filter_actions_for_city
from ..intervene.patches import ScheduledPatch, compile_scheduled_patches
from ..intervene.records import InterventionPlan
from ..synth.generator import generate_city
from ..synth.ground_truth import GroundTruth


@dataclass
class TruthSimResult:
    """Realised counterfactual outcomes under the true latent generator."""
    city_id: str
    seed: int
    duration_hours: int
    plan_id: str
    unperturbed_critical_hours: float
    realised_critical_hours: float
    realised_benefit_hours: float
    realised_broken_episodes: int
    unperturbed_peak_stress: float
    realised_peak_stress: float
    realised_stress_delta: float
    ground_truth_unperturbed: GroundTruth
    ground_truth_realised: GroundTruth


def run_truth_sim(
    config: CityConfig,
    seed: int,
    duration_hours: int = 72,
    plan: Optional[InterventionPlan] = None,
    actions_by_id: Optional[Dict[str, Action]] = None,
    rain_series: Optional[Union[dict[int, float], dict[str, dict[int, float]]]] = None,
    generator_family: str = "logistic_hazard",
    anchor_mode: str = "off",
    decision_hour: float = 24.0,
) -> TruthSimResult:
    """Re-simulate latent dynamics with identical noise under an intervention plan."""
    if actions_by_id is None:
        icfg = load_interventions_config()
        filtered = filter_actions_for_city(icfg.actions, config)
        actions_by_id = {a.id: a for a in filtered}

    # 1. Unperturbed baseline run (do-nothing)
    obs_0, gt_0 = generate_city(
        config=config,
        seed=seed,
        duration_hours=duration_hours,
        rain_series=rain_series,
        generator_family=generator_family,
        anchor_mode=anchor_mode,
        patches=None,
    )

    crit_thresh = config.critical_stress_threshold
    unperturbed_crit_hours = sum(
        1.0 for n, s_series in gt_0.stress.items() for v in s_series if v >= crit_thresh
    )
    unperturbed_peak = max(
        max(s_series) for s_series in gt_0.stress.values()
    )

    if plan is None or not plan.actions:
        return TruthSimResult(
            city_id=config.city_id,
            seed=seed,
            duration_hours=duration_hours,
            plan_id="do_nothing",
            unperturbed_critical_hours=unperturbed_crit_hours,
            realised_critical_hours=unperturbed_crit_hours,
            realised_benefit_hours=0.0,
            realised_broken_episodes=0,
            unperturbed_peak_stress=unperturbed_peak,
            realised_peak_stress=unperturbed_peak,
            realised_stress_delta=0.0,
            ground_truth_unperturbed=gt_0,
            ground_truth_realised=gt_0,
        )

    # 2. Compile patches for the plan
    issue_dt = config.start_time_utc + timedelta(hours=decision_hour)
    patches = compile_scheduled_patches(
        actions_by_id=actions_by_id,
        action_instances=plan.actions,
        n_rollouts=1,
        global_seed=seed,
        issue_time=issue_dt,
    )

    # 3. Realised counterfactual run with patches
    obs_p, gt_p = generate_city(
        config=config,
        seed=seed,
        duration_hours=duration_hours,
        rain_series=rain_series,
        generator_family=generator_family,
        anchor_mode=anchor_mode,
        patches=patches,
    )

    realised_crit_hours = sum(
        1.0 for n, s_series in gt_p.stress.items() for v in s_series if v >= crit_thresh
    )
    realised_benefit = unperturbed_crit_hours - realised_crit_hours
    realised_peak = max(
        max(s_series) for s_series in gt_p.stress.values()
    )
    stress_delta = unperturbed_peak - realised_peak

    # Count broken critical episodes
    unperturbed_n_eps = len(gt_0.critical_episodes)
    realised_n_eps = len(gt_p.critical_episodes)
    broken_eps = max(0, unperturbed_n_eps - realised_n_eps)

    return TruthSimResult(
        city_id=config.city_id,
        seed=seed,
        duration_hours=duration_hours,
        plan_id=plan.plan_id,
        unperturbed_critical_hours=unperturbed_crit_hours,
        realised_critical_hours=realised_crit_hours,
        realised_benefit_hours=float(realised_benefit),
        realised_broken_episodes=broken_eps,
        unperturbed_peak_stress=unperturbed_peak,
        realised_peak_stress=realised_peak,
        realised_stress_delta=float(stress_delta),
        ground_truth_unperturbed=gt_0,
        ground_truth_realised=gt_p,
    )
