"""Intervention Solvers: Lazy Greedy, Beam Search, and Brute Force under Hard Constraints.

Enforces:
  - Strict resource budget compliance (crews, boats, pumps, generators, financial caps).
  - Exclusivity group enforcement (e.g. only 1 evacuation plan or 1 traffic protocol per zone).
  - Unit caps, zone caps, and earliest start time constraints.
  - Multi-tier rollout budgeting: fast screening (N=100) and top-k re-evaluation (N=300).
  - Explicit 'no feasible plan' handling for adversarial zero-budget cases.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import numpy as np

from backend.app.explain.records import ChainLink
from backend.app.intervene.actions import Action, ActionInstance, instantiate_action
from backend.app.intervene.evaluate import evaluate_plan
from backend.app.intervene.records import (
    InterventionPlan,
    PlanOutcome,
    ResourceUse,
)
from backend.app.forecast.learner import ForecastModel
from backend.app.forecast.rollout import NoiseBank, RolloutResults


def is_feasible(
    candidate_instances: List[ActionInstance],
    actions_by_id: Dict[str, Action],
    budgets: Dict[str, float],
    zone_caps: Optional[Dict[str, int]] = None,
) -> Tuple[bool, Optional[str], Dict[str, float]]:
    """Verify that a set of action instances strictly satisfies all constraints."""
    total_costs: Dict[str, float] = {}
    exclusivity_seen: Set[str] = set()
    units_by_action: Dict[str, int] = {}
    actions_per_zone: Dict[str, int] = {}

    for inst in candidate_instances:
        if inst.action_id not in actions_by_id:
            return False, f"Unknown action id {inst.action_id}", {}
        action = actions_by_id[inst.action_id]

        # 1. Exclusivity group
        if action.exclusivity_group:
            grp_key = f"{action.exclusivity_group}:{inst.zone}"
            if grp_key in exclusivity_seen:
                return False, f"Exclusivity violation in group '{action.exclusivity_group}' for zone {inst.zone}", {}
            exclusivity_seen.add(grp_key)

        # 2. Max units per action
        units_by_action[action.id] = units_by_action.get(action.id, 0) + inst.units
        if units_by_action[action.id] > action.max_units:
            return False, f"Max units exceeded for action {action.id} ({units_by_action[action.id]} > {action.max_units})", {}

        # 3. Zone caps
        if inst.zone:
            actions_per_zone[inst.zone] = actions_per_zone.get(inst.zone, 0) + 1
            if zone_caps and inst.zone in zone_caps and actions_per_zone[inst.zone] > zone_caps[inst.zone]:
                return False, f"Zone cap exceeded for zone {inst.zone}", {}

        # 4. Resource accumulation
        for r_name, r_cost in inst.resource_costs.items():
            total_costs[r_name] = total_costs.get(r_name, 0.0) + r_cost

    # 5. Check budgets
    for r_name, r_used in total_costs.items():
        limit = budgets.get(r_name, 0.0)
        if r_used > limit + 1e-6:
            return False, f"Budget exceeded for '{r_name}': used {r_used:.1f} > limit {limit:.1f}", total_costs

    return True, None, total_costs


def compute_resource_use(
    total_costs: Dict[str, float],
    budgets: Dict[str, float],
) -> List[ResourceUse]:
    """Format resource consumption table."""
    records: List[ResourceUse] = []
    all_keys = sorted(list(set(budgets.keys()) | set(total_costs.keys())))
    for k in all_keys:
        used = float(total_costs.get(k, 0.0))
        cap = float(budgets.get(k, 0.0))
        util = float(used / cap) if cap > 0 else (1.0 if used > 0 else 0.0)
        records.append(
            ResourceUse(
                budget_type=k,
                used=round(used, 2),
                capacity=round(cap, 2),
                utilization=round(util, 4),
            )
        )
    return records


def generate_candidate_pool(
    actions: List[Action],
    zones: Optional[List[str]] = None,
    start_offsets: List[float] = [0.0, 3.0],
    zone_ids: Optional[List[str]] = None,
) -> List[ActionInstance]:
    """Generate all permissible ActionInstances across zones and start offsets."""
    target_zones = zones if zones is not None else (zone_ids or [])
    candidates: List[ActionInstance] = []
    for action in actions:
        eligible_zones = [z for z in target_zones if action.availability_by_zone is None or z in action.availability_by_zone]
        for z in eligible_zones:
            for offset in start_offsets:
                if offset >= action.earliest_start_offset:
                    candidates.append(
                        instantiate_action(action, zone=z, start_time_offset=offset, units=1)
                    )
    return candidates


def solve_interventions(
    candidates: List[ActionInstance],
    actions_by_id: Dict[str, Action],
    budgets: Dict[str, float],
    model: ForecastModel,
    initial_beliefs: Dict[str, Tuple[float, float]],
    baseline_rollouts: RolloutResults,
    noise_bank: Optional[NoiseBank] = None,
    decision_time: Optional[datetime] = None,
    method: str = "greedy",  # 'greedy' | 'beam' | 'brute_force'
    beam_width: int = 3,
    max_actions_in_plan: int = 4,
    screening_rollouts: int = 100,
    full_rollouts: int = 300,
    horizon: int = 48,
    global_seed: int = 42,
    baseline_links: Optional[List[ChainLink]] = None,
) -> Tuple[List[InterventionPlan], float]:
    """Solve for ranked feasible intervention plans under hard resource constraints.

    Returns:
        (ranked_plans, elapsed_seconds)
    """
    t0 = time.perf_counter()
    if decision_time is None:
        decision_time = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)

    # 1. Do-nothing baseline reference plan
    empty_plan = InterventionPlan(
        plan_id="plan_do_nothing",
        decision_time=decision_time,
        actions=[],
        total_cost={},
        resource_use=compute_resource_use({}, budgets),
        selection_rank=0,
        selection_rationale="Baseline reference (do nothing)",
    )
    empty_plan.outcome = evaluate_plan(
        plan=empty_plan,
        model=model,
        initial_beliefs=initial_beliefs,
        baseline_rollouts=baseline_rollouts,
        actions_by_id=actions_by_id,
        noise_bank=noise_bank,
        global_seed=global_seed,
        horizon=horizon,
        n_rollouts=full_rollouts,
        baseline_links=baseline_links,
        budgets=budgets,
    )

    # 2. Check adversarial zero-budget or empty candidates
    affordable_candidates = []
    for c in candidates:
        feas, _, _ = is_feasible([c], actions_by_id, budgets)
        if feas:
            affordable_candidates.append(c)

    if not affordable_candidates:
        empty_plan.infeasibility_reason = "Zero budget or all actions exceed budget limits."
        empty_plan.selection_rank = 1
        elapsed = time.perf_counter() - t0
        return [empty_plan], elapsed

    # 3. Solver Algorithm
    discovered_plan_actions: List[List[ActionInstance]] = []

    if method == "brute_force" or len(affordable_candidates) <= 6:
        # Exact combinatorial enumeration
        from itertools import combinations
        for k in range(1, min(len(affordable_candidates) + 1, max_actions_in_plan + 1)):
            for comb in combinations(affordable_candidates, k):
                feas, _, _ = is_feasible(list(comb), actions_by_id, budgets)
                if feas:
                    discovered_plan_actions.append(list(comb))

    elif method == "beam":
        # Beam search
        current_beam: List[List[ActionInstance]] = [[]]
        for depth in range(max_actions_in_plan):
            next_candidates = []
            for plan_acts in current_beam:
                for c in affordable_candidates:
                    if any(c.instance_id == existing.instance_id for existing in plan_acts):
                        continue
                    new_set = plan_acts + [c]
                    feas, _, _ = is_feasible(new_set, actions_by_id, budgets)
                    if feas:
                        # Quick screen
                        temp_plan = InterventionPlan(plan_id="temp", decision_time=decision_time, actions=new_set)
                        out = evaluate_plan(
                            temp_plan, model, initial_beliefs, baseline_rollouts, actions_by_id,
                            noise_bank=noise_bank, global_seed=global_seed, horizon=horizon,
                            n_rollouts=screening_rollouts, budgets=budgets,
                        )
                        next_candidates.append((out.net_benefit, new_set))

            if not next_candidates:
                break
            next_candidates.sort(key=lambda x: x[0], reverse=True)
            current_beam = [acts for _, acts in next_candidates[:beam_width]]
            for _, acts in next_candidates[:beam_width]:
                discovered_plan_actions.append(acts)

    else:
        # Lazy Greedy: iteratively pick candidate with highest marginal net benefit per cost
        current_actions: List[ActionInstance] = []
        for step_idx in range(max_actions_in_plan):
            best_cand = None
            best_gain = -999.0
            for c in affordable_candidates:
                if any(c.instance_id == ex.instance_id for ex in current_actions):
                    continue
                test_set = current_actions + [c]
                feas, _, _ = is_feasible(test_set, actions_by_id, budgets)
                if feas:
                    temp_plan = InterventionPlan(plan_id="temp", decision_time=decision_time, actions=test_set)
                    out = evaluate_plan(
                        temp_plan, model, initial_beliefs, baseline_rollouts, actions_by_id,
                        noise_bank=noise_bank, global_seed=global_seed, horizon=horizon,
                        n_rollouts=screening_rollouts, budgets=budgets,
                    )
                    cost_denom = max(1.0, sum(c.resource_costs.values()))
                    marginal_metric = out.net_benefit / cost_denom
                    if marginal_metric > best_gain:
                        best_gain = marginal_metric
                        best_cand = c

            if best_cand is not None and best_gain > 0:
                current_actions.append(best_cand)
                discovered_plan_actions.append(list(current_actions))
            else:
                break

    # 4. High-Precision Evaluation of Top Candidate Plans
    candidate_plans: List[InterventionPlan] = []
    # Deduplicate plans
    seen_hashes = set()

    for idx, acts in enumerate(discovered_plan_actions):
        feas, reason, costs = is_feasible(acts, actions_by_id, budgets)
        plan_id = f"plan_{hashlib.md5('_'.join(sorted(a.instance_id for a in acts)).encode()).hexdigest()[:8]}"
        if plan_id in seen_hashes:
            continue
        seen_hashes.add(plan_id)

        p = InterventionPlan(
            plan_id=plan_id,
            decision_time=decision_time,
            actions=acts,
            total_cost=costs,
            resource_use=compute_resource_use(costs, budgets),
            feasibility=feas,
            infeasibility_reason=reason,
        )
        p.outcome = evaluate_plan(
            plan=p,
            model=model,
            initial_beliefs=initial_beliefs,
            baseline_rollouts=baseline_rollouts,
            actions_by_id=actions_by_id,
            noise_bank=noise_bank,
            global_seed=global_seed,
            horizon=horizon,
            n_rollouts=full_rollouts,
            baseline_links=baseline_links,
            budgets=budgets,
        )
        candidate_plans.append(p)

    # Sort plans descending by net benefit
    candidate_plans.sort(key=lambda p: p.outcome.net_benefit if p.outcome else -999.0, reverse=True)

    # Assign ranks and rationale
    ranked_results: List[InterventionPlan] = []
    for rank, p in enumerate(candidate_plans, start=1):
        p.selection_rank = rank
        act_names = ", ".join(actions_by_id[a.action_id].name for a in p.actions)
        p.selection_rationale = (
            f"Rank {rank}: Net benefit {p.outcome.net_benefit:.2f} "
            f"({p.outcome.delta_critical_zone_hours:.1f} saved critical zone-hours, "
            f"{len(p.outcome.side_effects)} side-effects). Actions: {act_names}."
        )
        ranked_results.append(p)

    # Always ensure baseline do-nothing is in the return set
    all_output_plans = [empty_plan] + ranked_results
    elapsed = time.perf_counter() - t0
    return all_output_plans, elapsed
