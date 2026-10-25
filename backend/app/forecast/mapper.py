"""Risk-state mapper and alert evaluation with hysteresis.

Rules:
  - Immediate escalation when higher risk threshold is breached.
  - Delayed de-escalation: requires min_dwell_steps consecutive steps below threshold.
  - Alerts: P(critical within 72h) above alert_tau for alert_k consecutive steps.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from backend.app.forecast.calibrate import Calibrator, IdentityCalibrator
from backend.app.forecast.config import MapperConfig
from backend.app.schemas import RiskState


@dataclass
class EntityHysteresisState:
    current_state: RiskState = RiskState.NORMAL
    dwell_counter: int = 0
    candidate_lower_state: Optional[RiskState] = None
    alert_counter: int = 0
    is_alert: bool = False


class RiskStateMapper:
    """Maps calibrated probabilities and time-to-critical into RiskState with hysteresis."""

    def __init__(
        self,
        config: MapperConfig,
        calibrator: Optional[Calibrator] = None,
    ):
        self.config = config
        self.calibrator = calibrator or IdentityCalibrator()
        # entity_id (zone_id or "city") -> EntityHysteresisState
        self._states: Dict[str, EntityHysteresisState] = {}

    def _get_entity_state(self, entity_id: str) -> EntityHysteresisState:
        if entity_id not in self._states:
            self._states[entity_id] = EntityHysteresisState()
        return self._states[entity_id]

    def raw_map(
        self,
        p_crit_72: float,
        p_crit_12: float,
        median_ttc: Optional[float] = None,
        hard_breached: bool = False,
    ) -> RiskState:
        """Evaluate raw instantaneous risk state before hysteresis."""
        if hard_breached or p_crit_12 >= self.config.p_crit12_critical:
            return RiskState.CRITICAL

        if (
            p_crit_72 >= self.config.p_crit72_high
            or (median_ttc is not None and median_ttc < self.config.ttc_high_hours)
        ):
            return RiskState.HIGH_RISK

        if p_crit_72 >= self.config.p_crit72_watch:
            return RiskState.WATCH

        return RiskState.NORMAL

    def update(
        self,
        entity_id: str,
        raw_p_crit_72: float,
        raw_p_crit_12: float,
        median_ttc: Optional[float] = None,
        hard_breached: bool = False,
    ) -> Tuple[RiskState, bool]:
        """Update risk state for entity using hysteresis and check alert condition.

        Returns:
            (effective_risk_state, is_alert_active)
        """
        entity = self._get_entity_state(entity_id)

        # Calibrate probabilities
        p_crit_72 = self.calibrator.calibrate(raw_p_crit_72)
        p_crit_12 = self.calibrator.calibrate(raw_p_crit_12)

        raw_state = self.raw_map(p_crit_72, p_crit_12, median_ttc, hard_breached)

        # State rank ordering
        state_ranks = {
            RiskState.NORMAL: 0,
            RiskState.WATCH: 1,
            RiskState.HIGH_RISK: 2,
            RiskState.CRITICAL: 3,
        }

        current_rank = state_ranks[entity.current_state]
        raw_rank = state_ranks[raw_state]

        if raw_rank > current_rank:
            # Escalation: immediate
            entity.current_state = raw_state
            entity.dwell_counter = 0
            entity.candidate_lower_state = None
        elif raw_rank < current_rank:
            # De-escalation: requires min_dwell_steps consecutive steps
            if entity.candidate_lower_state == raw_state:
                entity.dwell_counter += 1
                if entity.dwell_counter >= self.config.min_dwell_steps:
                    entity.current_state = raw_state
                    entity.dwell_counter = 0
                    entity.candidate_lower_state = None
            else:
                entity.candidate_lower_state = raw_state
                entity.dwell_counter = 1
        else:
            # Steady state: reset candidate de-escalation
            entity.dwell_counter = 0
            entity.candidate_lower_state = None

        # Alert evaluation: p_crit_72 >= alert_tau for alert_k consecutive steps
        if p_crit_72 >= self.config.alert_tau:
            entity.alert_counter += 1
            if entity.alert_counter >= self.config.alert_k:
                entity.is_alert = True
        else:
            entity.alert_counter = 0
            entity.is_alert = False

        return entity.current_state, entity.is_alert
