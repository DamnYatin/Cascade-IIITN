"""Forecast snapshot and record models with canonical serialization.

Guarantees:
  - Deterministic serialization (sorted keys, fixed decimal rounding).
  - Provenance mix disclosure (real rain/soil vs simulated systems).
  - Explicit calibrated=false and burn_in flags.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from backend.app.schemas import Edge, NodeId, RiskState


class ForecastSnapshot(BaseModel):
    """Canonical multi-horizon forecast snapshot issued at a replay clock tick."""

    issued_at: datetime
    city_id: str
    city_risk_state: RiskState
    # horizon -> {state_name: probability}
    city_probabilities: Dict[str, Dict[str, float]]
    # zone_id -> RiskState
    zone_risk_states: Dict[str, RiskState]
    # zone_id -> horizon -> {state_name: probability}
    zone_probabilities: Dict[str, Dict[str, Dict[str, float]]]
    # zone_id / "city" -> evidence quality score in [0, 1]
    evidence_quality: Dict[str, float]
    # Learned edges with confidence
    top_edges: List[Dict[str, Any]] = Field(default_factory=list)
    # Recent edge changes from EdgeBook
    edge_changes: List[Dict[str, Any]] = Field(default_factory=list)
    # Drift events
    drift_events: List[Dict[str, Any]] = Field(default_factory=list)
    # Ordered cascade failure stages
    cascade_summary: List[Dict[str, Any]] = Field(default_factory=list)
    # Provenance mix breakdown
    provenance_mix: Dict[str, Any] = Field(default_factory=dict)
    # Explicit disclosure string
    disclosure_string: str = ""
    # System flags
    burn_in: bool = False
    calibrated: bool = False
    calibration_source: str = "none"
    oracle: bool = False
    config_hash: str = ""

    def to_canonical_dict(self) -> Dict[str, Any]:
        """Convert snapshot to canonical dict with fixed float precision and sorted structures."""
        raw = self.model_dump(mode="json")

        def _canonicalize(obj: Any) -> Any:
            if isinstance(obj, float):
                return round(obj, 4)
            if isinstance(obj, dict):
                return {k: _canonicalize(obj[k]) for k in sorted(obj.keys())}
            if isinstance(obj, list):
                return [_canonicalize(v) for v in obj]
            return obj

        return _canonicalize(raw)

    def to_canonical_json(self) -> str:
        """Return deterministic canonical JSON string."""
        data = self.to_canonical_dict()
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def compute_forecast_hash(self) -> str:
        """Return SHA-256 hash of canonical JSON."""
        canon = self.to_canonical_json()
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()
