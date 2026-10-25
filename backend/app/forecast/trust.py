"""Source trust tracking, outlier gating, flatline detection, and evidence quality.

Formulas & Rules:
  - Trust: Beta(alpha, beta) posterior per source. Updated only when peer corroboration exists.
  - Tempered variance: variance_tempered = base_var / max(trust, 0.01).
  - Outlier gate: standardized residual > outlier_z vs prior/model AND peers.
  - Flatline detector: zero variance across flatline_hours indicates sensor failure (not true 0).
  - Citizen reports: requires min corroboration; downweighted or rejected when sensors disagree.
  - Evidence Quality: EQ = 0.40 * freshness + 0.35 * mean_trust + 0.25 * agreement in [0, 1].
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import numpy as np

from backend.app.forecast.config import TrustConfig
from backend.app.schemas import Observation


class SourceTrustManager:
    """Tracks source trust via Beta posteriors, gates outliers, and checks flatlines."""

    def __init__(self, config: TrustConfig):
        self.config = config
        self.prior_alpha = config.prior_alpha
        self.prior_beta = config.prior_beta
        # source -> [alpha, beta]
        self._source_betas: Dict[str, List[float]] = defaultdict(
            lambda: [self.prior_alpha, self.prior_beta]
        )
        # Flatline tracking: node:source -> deque of (arrival_time, value)
        self._flatline_history: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=config.flatline_hours * 2)
        )
        # Outlier rejection counts for logging
        self.gated_outliers_count: int = 0

    def get_trust(self, source: str) -> float:
        """Return expected trust score in [0, 1] for a source."""
        ab = self._source_betas[source]
        return float(ab[0] / (ab[0] + ab[1]))

    def update_trust(
        self,
        source: str,
        agreed: bool,
        weight: float = 1.0,
    ) -> None:
        """Update Beta posterior based on agreement with independent observations."""
        ab = self._source_betas[source]
        if agreed:
            ab[0] += weight
        else:
            ab[1] += weight

    def check_flatline(
        self,
        node: str,
        source: str,
        val: float,
        clock_time: datetime,
    ) -> bool:
        """Return True if sensor has been flatlining for >= flatline_hours."""
        key = f"{node}:{source}"
        hist = self._flatline_history[key]
        hist.append((clock_time, val))

        cutoff = clock_time - timedelta(hours=self.config.flatline_hours)
        recent_vals = [v for (t, v) in hist if t >= cutoff]

        if len(recent_vals) >= self.config.flatline_hours:
            # Check if all values are identical or variance is near zero
            if max(recent_vals) - min(recent_vals) < 1e-6:
                return True
        return False

    def is_outlier(
        self,
        val: float,
        predicted_mean: float,
        predicted_std: float,
        peer_values: List[float],
    ) -> bool:
        """Outlier gate: check if standardized residual exceeds outlier_z vs prediction AND peers."""
        std = max(predicted_std, 1e-4)
        z_model = abs(val - predicted_mean) / std
        if z_model <= self.config.outlier_z:
            return False

        if peer_values and len(peer_values) > 1:
            other_peers = [p for p in peer_values if abs(p - val) > 1e-6]
            if other_peers:
                peer_med = float(np.median(other_peers))
                z_peer = abs(val - peer_med) / std
                if z_peer <= self.config.outlier_z:
                    return False

        self.gated_outliers_count += 1
        return True

    def process_citizen_reports(
        self,
        reports: List[Observation],
        sensor_stress: Optional[float] = None,
    ) -> Tuple[Optional[float], float, bool]:
        """Aggregate citizen reports for a node/zone and assess credibility.

        Returns:
            (effective_stress, effective_weight, is_admitted)
        """
        if not reports:
            return None, 0.0, False

        # Count distinct reporters (from obs_id or source suffix)
        reporters = {r.source for r in reports}
        num_reporters = len(reports)  # Each observation is a report

        mean_val = float(np.mean([r.value for r in reports]))

        # Condition 1: Minimum corroborators required
        if num_reporters < self.config.min_corroborators_for_reports:
            # Weak evidence, strictly capped
            return mean_val, min(0.10, self.config.report_weight_cap), True

        # Condition 2: Sensor consistency check
        if sensor_stress is not None:
            diff = abs(mean_val - sensor_stress)
            # If sensors disagree strongly (> 0.40 stress difference), downweight heavily
            if diff > 0.40:
                # Downweight to avoid spam pushing node to CRITICAL
                return mean_val, 0.02, False

        # Valid corroborated cluster
        weight = min(0.30, self.config.report_weight_cap)
        return mean_val, weight, True


def compute_evidence_quality(
    freshness: float,
    mean_trust: float,
    agreement: float,
    unobserved: bool = False,
) -> float:
    """Compute evidence quality in [0, 1].

    Formula:
      EQ = 0.40 * freshness + 0.35 * mean_trust + 0.25 * agreement
    If unobserved=True, returns 0.0.
    """
    if unobserved:
        return 0.0

    f = max(0.0, min(1.0, freshness))
    t = max(0.0, min(1.0, mean_trust))
    a = max(0.0, min(1.0, agreement))

    eq = 0.40 * f + 0.35 * t + 0.25 * a
    return float(max(0.0, min(1.0, eq)))
