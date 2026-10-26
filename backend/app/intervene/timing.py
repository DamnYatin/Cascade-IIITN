"""Value of Lead Time & Cost-of-Waiting Analysis.

Evaluates:
  - Benefit decay curve when committing to the recommended plan with start delays [0, 3, 6, 12, 24] hours.
  - Cost of waiting: lost cascade-critical zone-hours per hour of decision hesitation.
  - Latest Effective Start Time: latest start offset that preserves >= min_benefit_fraction (e.g. 50%) of initial benefit.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.app.intervene.actions import Action, ActionInstance
from backend.app.intervene.evaluate import evaluate_plan
from backend.app.intervene.records import InterventionPlan, PlanOutcome
from backend.app.forecast.learner import ForecastModel
from backend.app.forecast.rollout import NoiseBank, RolloutResults


def evaluate_value_of_lead_time(
    plan: InterventionPlan,
    model: ForecastModel,
    initial_beliefs: Dict[str, Tuple[float, float]],
    baseline_rollouts: RolloutResults,
    actions_by_id: Dict[str, Action],
    noise_bank: Optional[NoiseBank] = None,
    delay_hours: List[float] = [0.0, 3.0, 6.0, 12.0, 24.0],
    min_benefit_fraction: float = 0.50,
    horizon: int = 48,
    n_rollouts: int = 150,
) -> Dict[str, Any]:
    """Compute benefit decay curve and latest effective start time as a function of commitment delay."""
    curve: List[Dict[str, Any]] = []

    # Evaluate at 0 delay first to establish maximum benefit
    delayed_instances_0 = [
        deepcopy(inst) for inst in plan.actions
    ]
    p0 = InterventionPlan(plan_id="p_delay_0", decision_time=plan.decision_time, actions=delayed_instances_0)
    out0 = evaluate_plan(
        p0, model, initial_beliefs, baseline_rollouts, actions_by_id,
        noise_bank=noise_bank, horizon=horizon, n_rollouts=n_rollouts,
    )
    initial_benefit = max(0.001, out0.net_benefit)
    target_benefit = initial_benefit * min_benefit_fraction

    latest_effective_delay = 0.0

    for d in delay_hours:
        delayed_instances = []
        for inst in plan.actions:
            d_inst = deepcopy(inst)
            d_inst.start_time_offset = inst.start_time_offset + d
            delayed_instances.append(d_inst)

        temp_plan = InterventionPlan(
            plan_id=f"plan_delayed_{d:.0f}h",
            decision_time=plan.decision_time,
            actions=delayed_instances,
        )
        out = evaluate_plan(
            temp_plan, model, initial_beliefs, baseline_rollouts, actions_by_id,
            noise_bank=noise_bank, horizon=horizon, n_rollouts=n_rollouts,
        )
        curve.append({
            "delay_hours": d,
            "net_benefit": out.net_benefit,
            "delta_hours": out.delta_critical_zone_hours,
            "p_critical_72h": out.p_critical_72h_after,
            "cascade_broken": out.cascade_broken,
        })
        if out.net_benefit >= target_benefit:
            latest_effective_delay = max(latest_effective_delay, d)

    # Cost of waiting: average benefit loss per hour over the first 12 hours
    b0 = curve[0]["net_benefit"]
    b12 = next(c["net_benefit"] for c in curve if c["delay_hours"] >= 12.0)
    cost_of_waiting_per_hour = round(max(0.0, (b0 - b12) / 12.0), 3)

    return {
        "plan_id": plan.plan_id,
        "initial_benefit": round(initial_benefit, 3),
        "target_threshold_benefit": round(target_benefit, 3),
        "latest_effective_start_delay_hours": latest_effective_delay,
        "cost_of_waiting_per_hour": cost_of_waiting_per_hour,
        "delay_curve": curve,
    }
