"""Data models and schemas for Causal Explainability.

All schemas are additive and support canonical serialization (sorted keys, rounded floats)
to guarantee deterministic golden hashing.
"""
from __future__ import annotations

from datetime import datetime, timezone
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


class ChainLink(BaseModel):
    """A directed dependency link in a predicted failure chain."""
    u: str = Field(..., description="Source node id (e.g. 'zone:system')")
    v: str = Field(..., description="Target node id (e.g. 'zone:system')")
    lag_hours: float = Field(..., description="Estimated physical or learned propagation lag in hours")
    weight: float = Field(..., description="Learned dependency coupling weight (signed)")
    confidence: float = Field(..., description="Statistical confidence of the learned edge in [0, 1]")
    p_link: float = Field(..., description="Empirical usage probability P(u was dominant trigger | v crossed)")
    active_hours: float = Field(default=0.0, description="Hours the edge has been active in EdgeBook")
    parent_stress: float = Field(default=0.0, description="Parent's current estimated latent stress in [0, 1]")
    parent_variance: float = Field(default=0.0, description="Variance of parent's current stress estimate")
    paired_removal_delta_p: Optional[float] = Field(default=None, description="Paired change in P(critical) when link is removed")
    paired_removal_delta_ttc: Optional[float] = Field(default=None, description="Paired change in median time-to-critical when link is removed")

    def canonical_dict(self) -> Dict[str, Any]:
        return _round_floats(self.model_dump())


class EvidenceReceipt(BaseModel):
    """Audit receipt proving the physical observations and learning history behind an edge or driver."""
    node: str = Field(..., description="Target node receiving the influence")
    parent_node: Optional[str] = Field(default=None, description="Parent node providing the influence")
    observation_ids: List[str] = Field(default_factory=list, description="IDs of observations in the ledger within window")
    sources: List[str] = Field(default_factory=list, description="Sensor/stream source identifiers")
    source_kinds: List[str] = Field(default_factory=list, description="Source classification: real | simulated | disaggregated")
    trusts: List[float] = Field(default_factory=list, description="Source reliability score in [0, 1] at arrival time")
    quality_flags: List[str] = Field(default_factory=list, description="Data quality flags (e.g. gated, flatline, late)")
    arrival_times: List[str] = Field(default_factory=list, description="ISO arrival timestamps (enforcing <= issued_at)")
    edge_first_seen: Optional[str] = Field(default=None, description="ISO timestamp when edge first appeared in EdgeBook")
    edge_weight: Optional[float] = Field(default=None, description="Current weight in EdgeBook")
    edge_confidence: Optional[float] = Field(default=None, description="Current confidence in EdgeBook")
    edge_update_count: Optional[int] = Field(default=None, description="Number of online recursive updates")
    drift_events: List[Dict[str, Any]] = Field(default_factory=list, description="Recent drift detections touching this edge")
    paired_removal_effect: Optional[Dict[str, Any]] = Field(default=None, description="Lazy-computed paired removal counterfactual")
    simulated_parent_flag: bool = Field(default=False, description="Explicit flag indicating parent stream is simulated")
    provenance_note: str = Field(default="", description="Human-readable provenance and simulation disclosure")

    def canonical_dict(self) -> Dict[str, Any]:
        return _round_floats(self.model_dump())


class DriverRecord(BaseModel):
    """An identified causal candidate driver of a risk change."""
    driver_id: str = Field(..., description="Unique identifier for the candidate driver")
    driver_type: str = Field(
        ...,
        description="Type: observation_group | learned_edge | precursor_feature | outlook | uncertainty"
    )
    contribution: float = Field(..., description="Estimated contribution to delta stress or delta P(critical)")
    ci_lower: float = Field(default=0.0, description="Bootstrap 95% CI lower bound")
    ci_upper: float = Field(default=0.0, description="Bootstrap 95% CI upper bound")
    direction: str = Field(..., description="Direction: increases_risk | decreases_risk | neutral")
    evidence_receipt: Optional[EvidenceReceipt] = Field(default=None, description="Audit receipt behind this driver")
    label: str = Field(..., description="Plain-language description using hedged phrasing")

    def canonical_dict(self) -> Dict[str, Any]:
        return _round_floats(self.model_dump())


class CascadeLoop(BaseModel):
    """A detected feedback loop in the cascade graph."""
    loop_id: str = Field(..., description="Unique loop identifier")
    nodes: List[str] = Field(..., description="Ordered nodes participating in the cycle")
    links: List[Tuple[str, str]] = Field(..., description="Directed edges forming the feedback cycle")
    amplification_factor: float = Field(..., description="Estimated stress amplification factor from paired rollouts")
    weakest_link: Tuple[str, str] = Field(..., description="Link whose removal yields largest attenuation")
    is_reinforcing: bool = Field(default=True, description="Whether feedback reinforces (positive) or damps (negative)")

    def canonical_dict(self) -> Dict[str, Any]:
        return _round_floats(self.model_dump())


class ConcurrentCluster(BaseModel):
    """Interacting simultaneous cascades originating from distinct root clusters."""
    cluster_id: str = Field(..., description="Unique cluster identifier")
    root_nodes: List[str] = Field(..., description="Root trigger nodes in this cluster")
    converging_nodes: List[str] = Field(..., description="Downstream nodes where multiple chains converge")
    joint_p_critical: float = Field(..., description="Joint probability P(critical) with all roots active")
    independent_p_critical: float = Field(..., description="Independent baseline probability implied without interaction")
    interaction_delta: float = Field(..., description="Amplification delta: joint_p - independent_p")
    ci_lower: float = Field(default=0.0, description="95% CI lower bound")
    ci_upper: float = Field(default=0.0, description="95% CI upper bound")
    rollout_count: int = Field(default=300, description="Number of rollouts evaluating interaction")

    def canonical_dict(self) -> Dict[str, Any]:
        return _round_floats(self.model_dump())


class ExplanationRecord(BaseModel):
    """Complete causal explanation for a risk state transition or forecast probability change."""
    id: str = Field(..., description="Deterministic record ID (hash of issued_at + subject + risk_state_to)")
    issued_at: datetime = Field(..., description="Timestamp when explanation was generated (UTC)")
    subject: str = Field(..., description="Subject of the explanation (city id or zone id or node id)")
    subject_kind: str = Field(..., description="Kind: 'city' | 'zone' | 'node'")
    risk_state_from: str = Field(..., description="Prior risk state (NORMAL, WATCH, HIGH_RISK, CRITICAL)")
    risk_state_to: str = Field(..., description="Current risk state (NORMAL, WATCH, HIGH_RISK, CRITICAL)")
    probability_before: float = Field(..., description="Prior P(cascade-critical within 72h)")
    probability_after: float = Field(..., description="Current P(cascade-critical within 72h)")
    drivers: List[DriverRecord] = Field(default_factory=list, description="Ranked causal candidate drivers")
    chain_tree: Dict[str, Any] = Field(default_factory=dict, description="Hierarchical failure chain tree with ETAs")
    loops: List[CascadeLoop] = Field(default_factory=list, description="Detected reinforcing feedback loops")
    concurrent_clusters: List[ConcurrentCluster] = Field(default_factory=list, description="Interacting concurrent clusters")
    confidence: float = Field(..., description="Overall explanation confidence score in [0, 1]")
    confidence_category: str = Field(..., description="'high' | 'medium' | 'low'")
    abstentions: List[str] = Field(default_factory=list, description="Reasons for model abstention or degraded confidence")
    provenance_mix: Dict[str, Any] = Field(default_factory=dict, description="Share of real vs simulated vs disaggregated data")
    disclosure_strings: List[str] = Field(default_factory=list, description="Honesty disclosures regarding simulated streams and models")
    template_id: str = Field(default="", description="ID of text template used")
    text: str = Field(default="", description="Hedged, deterministic plain-language explanation")

    def canonical_dict(self) -> Dict[str, Any]:
        d = self.model_dump()
        d["issued_at"] = self.issued_at.isoformat()
        return _round_floats(d)

    def canonical_json(self) -> str:
        return json.dumps(self.canonical_dict(), sort_keys=True)

    def compute_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()
