"""Observed-outcome tracker for online calibration.

Rules (V1, V2):
  - Belongs strictly in backend/app/forecast/ (NO import of ground truth or eval).
  - Tracks predictions and labels derived solely from the system's own filtered
    stress trajectory.
  - Labels mature ONLY when issued_at + horizon_hours <= clock_time.
  - Updating before label maturity is strictly prevented.
  - Maintains an auditable maturity log verifying update_time >= issued_at + horizon.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class PendingPrediction:
    issued_at: datetime
    horizon_hours: int
    entity_id: str
    level: str
    p_predicted: float
    evidence_quality: float = 1.0


@dataclass
class MaturedOutcome:
    issued_at: datetime
    horizon_hours: int
    mature_time: datetime
    observed_at: datetime
    entity_id: str
    level: str
    p_predicted: float
    outcome: float  # 1.0 if reached level by issued_at + h, else 0.0
    weight: float = 1.0


class ObservedOutcomeTracker:
    """Tracks forecaster predictions and evaluates outcomes from filtered beliefs when matured."""

    def __init__(
        self,
        stress_thresholds: Optional[Dict[str, float]] = None,
        min_evidence_quality: float = 0.20,
    ):
        self.stress_thresholds = stress_thresholds or {
            "WATCH": 0.40,
            "HIGH_RISK": 0.60,
            "CRITICAL": 0.80,
        }
        self.min_evidence_quality = min_evidence_quality
        self._pending: List[PendingPrediction] = []
        # entity_id -> datetime -> (filtered_stress, evidence_quality)
        self._belief_history: Dict[str, Dict[datetime, Tuple[float, float]]] = {}
        # Audit log of matured outcomes
        self.maturity_audit_log: List[Dict[str, Any]] = []

    def record_prediction(
        self,
        issued_at: datetime,
        horizon_hours: int,
        entity_id: str,
        level: str,
        p_predicted: float,
        evidence_quality: float = 1.0,
    ) -> None:
        """Record a forecast prediction to await outcome maturity."""
        if issued_at.tzinfo is None:
            raise ValueError("issued_at must be timezone-aware (UTC)")
        self._pending.append(
            PendingPrediction(
                issued_at=issued_at,
                horizon_hours=horizon_hours,
                entity_id=entity_id,
                level=level,
                p_predicted=float(p_predicted),
                evidence_quality=float(evidence_quality),
            )
        )

    def record_observed_state(
        self,
        entity_id: str,
        clock_time: datetime,
        filtered_stress: float,
        evidence_quality: float = 1.0,
    ) -> None:
        """Record filtered stress belief from state estimator at clock_time."""
        if clock_time.tzinfo is None:
            raise ValueError("clock_time must be timezone-aware (UTC)")
        if entity_id not in self._belief_history:
            self._belief_history[entity_id] = {}
        self._belief_history[entity_id][clock_time] = (float(filtered_stress), float(evidence_quality))

    def mature_outcomes(self, clock_time: datetime) -> List[MaturedOutcome]:
        """Harvest matured predictions where issued_at + horizon <= clock_time."""
        if clock_time.tzinfo is None:
            raise ValueError("clock_time must be timezone-aware (UTC)")

        matured: List[MaturedOutcome] = []
        remaining: List[PendingPrediction] = []

        for pred in self._pending:
            mat_time = pred.issued_at + timedelta(hours=pred.horizon_hours)
            if mat_time <= clock_time:
                # Prediction has matured!
                # Audit check: clock_time must strictly be >= mature_time
                assert clock_time >= mat_time, f"Future leakage: {clock_time} < {mat_time}"

                thresh = self.stress_thresholds.get(pred.level, 0.80)
                # Check whether filtered stress exceeded threshold during (issued_at, mat_time]
                entity_history = self._belief_history.get(pred.entity_id, {})
                window_stresses = [
                    val[0]
                    for t, val in entity_history.items()
                    if pred.issued_at < t <= mat_time
                ]

                if window_stresses:
                    max_stress = max(window_stresses)
                    y = 1.0 if max_stress >= thresh else 0.0
                else:
                    # If no observations in window, check endpoint or mark unobserved
                    endpoint = entity_history.get(mat_time)
                    y = 1.0 if (endpoint and endpoint[0] >= thresh) else 0.0

                # Down-weight low evidence quality
                weight = max(0.1, pred.evidence_quality)

                out_obj = MaturedOutcome(
                    issued_at=pred.issued_at,
                    horizon_hours=pred.horizon_hours,
                    mature_time=mat_time,
                    observed_at=clock_time,
                    entity_id=pred.entity_id,
                    level=pred.level,
                    p_predicted=pred.p_predicted,
                    outcome=y,
                    weight=weight,
                )
                matured.append(out_obj)

                self.maturity_audit_log.append(
                    {
                        "issued_at": pred.issued_at.isoformat(),
                        "horizon": pred.horizon_hours,
                        "mature_time": mat_time.isoformat(),
                        "clock_time": clock_time.isoformat(),
                        "entity_id": pred.entity_id,
                        "level": pred.level,
                        "p": round(pred.p_predicted, 4),
                        "y": y,
                    }
                )
            else:
                remaining.append(pred)

        self._pending = remaining
        return matured
