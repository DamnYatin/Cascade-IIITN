"""Data models and schemas for Counterfactual Interventions and Solvers.

Supports patch application, resource constraints, side-effect accounting,
and canonical serialization for golden hash verification.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


def _round_floats(obj: Any, precision: int = 4) -> Any:
    """Recursively round floats for deterministic canonical serialization."""
    if isinstance(obj, float):
        return round(obj, precision)
    elif isinstance(obj, dict):
        return {k: _round_floats(v, precision) for k, v in sorted(obj.items())}
    elif isinstance(obj, (list, tuple)):
        return [_round_floats(x, precision) for x in obj]
    return obj


class PatchType(str, Enum):
    SCALE_TERM = "scale_term"          # Scale a specific hazard update term (e.g. rain gain)
    ADD_BIAS = "add_bias"              # Add standing bias delta to stress
    SCALE_EDGE = "scale_edge"          # Scale coupling weight between u and v
    ADD_EDGE = "add_edge"              # Introduce new coupling edge (e.g. evacuation -> transport load)
    CAP_STRESS = "cap_stress"          # Impose maximum stress ceiling (e.g. medical surge capacity)
    EXPOSURE_CHANGE = "exposure_change" # Scale demand or vulnerability factor for a zone


class ProvenanceType(str, Enum):
    ASSUMED = "assumed"
    EXPERT_ESTIMATE_NEEDED = "expert_estimate_needed"
    GROUNDED_CATEGORY = "grounded_category"


class EffectPatch(BaseModel):
    """Specification of a single parameter perturbation applied inside Monte Carlo rollouts."""
    patch_type: PatchType = Field(..., description="Type of structural or parameter intervention")
    target: str = Field(..., description="Target node identifier, system name, or zone")
    term: Optional[str] = Field(default=None, description="Specific hazard update term for scale_term")
    u: Optional[str] = Field(default=None, description="Source node for scale_edge or add_edge")
    v: Optional[str] = Field(default=None, description="Target node for scale_edge or add_edge")
    param_value: float = Field(..., description="Nominal perturbation magnitude (e.g. multiplier or delta)")
    distribution: str = Field(default="constant", description="'constant' | 'triangular' | 'beta'")
    uncertainty_spread: float = Field(default=0.0, description="Fractional dispersion around nominal value in [0, 1]")
    lag: Optional[float] = Field(default=None, description="Propagation lag in hours if adding an edge")

    def canonical_dict(self) -> Dict[str, Any]:
        d = self.model_dump()
        d["patch_type"] = self.patch_type.value
        return _round_floats(d)


class Action(BaseModel):
    """Definition of an intervention category in the action library."""
    id: str = Field(..., description="Unique action identifier")
    name: str = Field(..., description="Human-readable action title")
    systems: List[str] = Field(..., description="Target city infrastructure systems")
    scope: str = Field(..., description="Application scope: 'zone' | 'node' | 'city'")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Tunable parameters")
    benefit_patches: List[EffectPatch] = Field(..., description="Intended positive intervention effects")
    side_effect_patches: List[EffectPatch] = Field(default_factory=list, description="Direct negative side-effects")
    resource_costs: Dict[str, float] = Field(..., description="Resource requirements per unit deployed")
    earliest_start_offset: float = Field(default=0.0, description="Hours after decision time before action can start")
    activation_delay: float = Field(default=0.0, description="Hours required for action to take physical effect")
    duration: float = Field(default=72.0, description="Duration in hours over which action remains active")
    max_units: int = Field(default=1, description="Maximum units deployable simultaneously")
    exclusivity_group: Optional[str] = Field(default=None, description="Mutually exclusive group identifier")
    availability_by_zone: Optional[List[str]] = Field(default=None, description="Eligible zones (None = all zones)")
    provenance: ProvenanceType = Field(default=ProvenanceType.ASSUMED, description="Provenance classification")
    grounded_in: List[str] = Field(default_factory=list, description="Source tags from historical flood reports")

    def canonical_dict(self) -> Dict[str, Any]:
        d = self.model_dump()
        d["provenance"] = self.provenance.value
        d["benefit_patches"] = [p.canonical_dict() for p in self.benefit_patches]
        d["side_effect_patches"] = [p.canonical_dict() for p in self.side_effect_patches]
        return _round_floats(d)


class ActionInstance(BaseModel):
    """A concrete instantiated action assigned to a specific target and start time."""
    instance_id: str = Field(..., description="Unique instance identifier")
    action_id: str = Field(..., description="Reference to parent Action ID")
    zone: Optional[str] = Field(default=None, description="Assigned zone identifier")
    target_node: Optional[str] = Field(default=None, description="Assigned target node identifier")
    start_time_offset: float = Field(..., description="Commitment time offset in hours from decision point")
    units: int = Field(default=1, description="Number of units deployed")
    resource_costs: Dict[str, float] = Field(default_factory=dict, description="Total resource costs for this instance")

    def canonical_dict(self) -> Dict[str, Any]:
        return _round_floats(self.model_dump())


class SideEffect(BaseModel):
    """An adverse impact on infrastructure stress caused by an action or propagated cascade."""
    node: str = Field(..., description="Affected infrastructure node")
    effect_type: str = Field(..., description="'explicit_patch' | 'propagated_cascade'")
    delta_p_critical: float = Field(..., description="Increase in P(critical) induced by action")
    delta_p_high: float = Field(..., description="Increase in P(high_risk) induced by action")
    description: str = Field(..., description="Description of the adverse side-effect mechanism")
    harm_score: float = Field(..., description="Harm score used in net benefit objective penalty")

    def canonical_dict(self) -> Dict[str, Any]:
        return _round_floats(self.model_dump())


class ResourceUse(BaseModel):
    """Accounting of a single resource budget category."""
    budget_type: str = Field(..., description="Resource name (e.g. 'crews', 'boats', 'pumps')")
    used: float = Field(..., description="Amount consumed by the plan")
    capacity: float = Field(..., description="Total available budget limit")
    utilization: float = Field(..., description="Ratio of used / capacity")

    def canonical_dict(self) -> Dict[str, Any]:
        return _round_floats(self.model_dump())


class Assumption(BaseModel):
    """Auditable record in the Assumptions Register for sensitivity and transparency."""
    parameter_id: str = Field(..., description="Unique parameter name")
    action_id: str = Field(..., description="Associated action id")
    description: str = Field(..., description="What physical property this parameter models")
    assumed_value: float = Field(..., description="Nominal assumed numerical value")
    uncertainty_range: Tuple[float, float] = Field(..., description="(lower_bound, upper_bound) spread")
    provenance: ProvenanceType = Field(..., description="Provenance level")
    grounded_in: List[str] = Field(default_factory=list, description="Literature or report citations")
    sensitivity_notes: str = Field(default="", description="Observed sensitivity behavior under scaling")

    def canonical_dict(self) -> Dict[str, Any]:
        d = self.model_dump()
        d["provenance"] = self.provenance.value
        return _round_floats(d)


class PlanOutcome(BaseModel):
    """Paired evaluation outcomes of an intervention plan versus doing nothing."""
    plan_id: str = Field(..., description="Associated plan identifier")
    p_critical_24h_before: float = Field(..., description="Baseline P(critical within 24h)")
    p_critical_24h_after: float = Field(..., description="Intervention P(critical within 24h)")
    delta_p_critical_24h: float = Field(..., description="Reduction in 24h critical risk (positive = benefit)")
    p_critical_72h_before: float = Field(..., description="Baseline P(critical within 72h)")
    p_critical_72h_after: float = Field(..., description="Intervention P(critical within 72h)")
    delta_p_critical_72h: float = Field(..., description="Reduction in 72h critical risk (positive = benefit)")
    expected_critical_zone_hours_before: float = Field(..., description="Baseline expected cascade-critical zone-hours")
    expected_critical_zone_hours_after: float = Field(..., description="Intervention expected cascade-critical zone-hours")
    delta_critical_zone_hours: float = Field(..., description="Saved cascade-critical zone-hours (primary loss reduction)")
    cvar_critical_zone_hours: float = Field(..., description="90th percentile tail risk of critical zone-hours")
    cascade_broken: bool = Field(..., description="True if critical risk drops below threshold or key link broken")
    broken_links: List[Tuple[str, str]] = Field(default_factory=list, description="Baseline chain links disrupted by plan")
    side_effects: List[SideEffect] = Field(default_factory=list, description="Identified harmful side-effects")
    net_benefit: float = Field(..., description="Loss reduction minus weighted side-effects minus cost penalties")
    ci_lower: float = Field(default=0.0, description="Bootstrap 95% CI lower bound of net benefit")
    ci_upper: float = Field(default=0.0, description="Bootstrap 95% CI upper bound of net benefit")

    def canonical_dict(self) -> Dict[str, Any]:
        d = self.model_dump()
        d["side_effects"] = [s.canonical_dict() for s in self.side_effects]
        return _round_floats(d)


class InterventionPlan(BaseModel):
    """A ranked, budget-feasible intervention schedule with paired counterfactual outcomes."""
    plan_id: str = Field(..., description="Deterministic plan identifier")
    decision_time: datetime = Field(..., description="Decision timestamp in UTC")
    actions: List[ActionInstance] = Field(default_factory=list, description="Scheduled actions")
    total_cost: Dict[str, float] = Field(default_factory=dict, description="Aggregate resource consumption")
    resource_use: List[ResourceUse] = Field(default_factory=list, description="Budget utilization by resource")
    outcome: Optional[PlanOutcome] = Field(default=None, description="Paired counterfactual outcome vs do-nothing")
    selection_rank: int = Field(default=0, description="Rank assigned by solver (1 = recommended best plan)")
    selection_rationale: str = Field(default="", description="Marginal gain explanations for actions added")
    feasibility: bool = Field(default=True, description="Whether plan satisfies all constraints")
    infeasibility_reason: Optional[str] = Field(default=None, description="Reason if infeasible")
    provenance_banner: str = Field(
        default="ESTIMATES UNDER LEARNED MODEL WITH ASSUMED ACTION EFFECTS. DOWNSTREAM STREAMS ARE SIMULATED.",
        description="Mandatory honesty disclosure banner"
    )

    def canonical_dict(self) -> Dict[str, Any]:
        d = self.model_dump()
        d["decision_time"] = self.decision_time.isoformat()
        d["actions"] = [a.canonical_dict() for a in self.actions]
        d["resource_use"] = [r.canonical_dict() for r in self.resource_use]
        if self.outcome:
            d["outcome"] = self.outcome.canonical_dict()
        return _round_floats(d)

    def canonical_json(self) -> str:
        return json.dumps(self.canonical_dict(), sort_keys=True)

    def compute_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()
