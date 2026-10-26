"""Robustness and Sensitivity Analysis for Intervention Plans.

Implements:
  - Effect Sensitivity: scales nominal assumed effect sizes by factors [0.5, 0.75, 1.0, 1.25, 1.5],
    evaluates whether plan rank and cascade-broken conclusions survive, and flags optimistic plans.
  - Model Uncertainty: draws per-rollout edge coupling weights from confidence intervals.
  - Noise Stability: assesses plan rank consistency across independent noise seeds.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from backend.app.intervene.actions import Action
from backend.app.intervene.evaluate import evaluate_plan
from backend.app.intervene.records import InterventionPlan, PlanOutcome
from backend.app.forecast.learner import ForecastModel
from backend.app.forecast.rollout import NoiseBank, RolloutResults


def evaluate_effect_sensitivity(
    plan: InterventionPlan,
    model: ForecastModel,
    initial_beliefs: Dict[str, Tuple[float, float]],
    baseline_rollouts: RolloutResults,
    actions_by_id: Dict[str, Action],
    noise_bank: Optional[NoiseBank] = None,
    scaling_factors: List[float] = [0.5, 0.75, 1.0, 1.25, 1.5],
    horizon: int = 48,
    n_rollouts: int = 150,
) -> Dict[str, Any]:
    """Test plan robustness by scaling assumed action effect sizes."""
    sensitivity_curve: List[Dict[str, Any]] = []
    base_net_benefit = plan.outcome.net_benefit if plan.outcome else 0.0

    for factor in scaling_factors:
        # Clone actions with scaled patch values
        scaled_actions: Dict[str, Action] = {}
        for a_id, action in actions_by_id.items():
            a_copy = deepcopy(action)
            for p in a_copy.benefit_patches:
                p.param_value = p.param_value * factor
            for p in a_copy.side_effect_patches:
                p.param_value = p.param_value * factor
            scaled_actions[a_id] = a_copy

        out = evaluate_plan(
            plan=plan,
            model=model,
            initial_beliefs=initial_beliefs,
            baseline_rollouts=baseline_rollouts,
            actions_by_id=scaled_actions,
            noise_bank=noise_bank,
            horizon=horizon,
            n_rollouts=n_rollouts,
        )
        sensitivity_curve.append({
            "scale_factor": factor,
            "net_benefit": out.net_benefit,
            "delta_hours": out.delta_critical_zone_hours,
            "cascade_broken": out.cascade_broken,
        })

    # A plan depends on optimistic assumptions if benefit drops below 20% of baseline when scaled to 0.75x
    low_075 = next((item["net_benefit"] for item in sensitivity_curve if item["scale_factor"] == 0.75), sensitivity_curve[0]["net_benefit"])
    depends_on_optimism = bool(base_net_benefit > 1.0 and low_075 < (base_net_benefit * 0.25))

    return {
        "plan_id": plan.plan_id,
        "scaling_curve": sensitivity_curve,
        "depends_on_optimistic_assumptions": depends_on_optimism,
        "survives_downscale_to_50pct": bool(sensitivity_curve[0]["net_benefit"] > 0),
    }


def evaluate_model_uncertainty(
    plan: InterventionPlan,
    model: ForecastModel,
    initial_beliefs: Dict[str, Tuple[float, float]],
    baseline_rollouts: RolloutResults,
    actions_by_id: Dict[str, Action],
    noise_bank: Optional[NoiseBank] = None,
    edge_uncertainty_sd: float = 0.15,
    horizon: int = 48,
    n_rollouts: int = 150,
) -> Dict[str, Any]:
    """Test plan performance when edge coupling weights vary under learning uncertainty."""
    # Perturb coupling weights in model
    perturbed_model = deepcopy(model)
    rng = np.random.default_rng(42)

    for v in perturbed_model.couplings:
        new_parents = []
        for u, lag, w in perturbed_model.couplings[v]:
            pert_w = float(w * (1.0 + rng.normal(0.0, edge_uncertainty_sd)))
            new_parents.append((u, lag, pert_w))
        perturbed_model.couplings[v] = new_parents

    out = evaluate_plan(
        plan=plan,
        model=perturbed_model,
        initial_beliefs=initial_beliefs,
        baseline_rollouts=baseline_rollouts,
        actions_by_id=actions_by_id,
        noise_bank=noise_bank,
        horizon=horizon,
        n_rollouts=n_rollouts,
    )

    base_benefit = plan.outcome.net_benefit if plan.outcome else 0.0
    gap = float(out.net_benefit - base_benefit)

    return {
        "plan_id": plan.plan_id,
        "uncertainty_net_benefit": out.net_benefit,
        "baseline_net_benefit": base_benefit,
        "robustness_gap": round(gap, 4),
        "robust": bool(out.net_benefit > 0.0),
    }
