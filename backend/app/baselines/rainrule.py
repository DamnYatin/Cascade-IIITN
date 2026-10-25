"""B2: Rain-Rule Baseline and B3: Climatology/Persistence Baseline.

Rule V1:
  - Consumes STRICTLY StreamView.
  - B2: Alert when causal rolling rainfall (local 24h, 72h, upstream rain) and soil moisture
    breach empirical thresholds.
  - B3: Causal running event frequency blended with current state persistence.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set
import numpy as np

from backend.app.replay.stream import StreamView
from backend.app.schemas import CityConfig, Observation


class RainRuleBaseline:
    """B2 Rain-threshold rule baseline using causal rolling rainfall and soil moisture."""

    def __init__(
        self,
        city_config: CityConfig,
        thresh_24h_mm: float = 70.0,
        thresh_72h_mm: float = 180.0,
        thresh_soil: float = 0.80,
    ):
        self.city_config = city_config
        self.thresh_24h_mm = thresh_24h_mm
        self.thresh_72h_mm = thresh_72h_mm
        self.thresh_soil = thresh_soil

        # zone -> list of (timestamp, mm)
        self._rain_history: Dict[str, List[tuple[datetime, float]]] = {z.id: [] for z in city_config.zones}
        self._latest_soil: Dict[str, float] = {z.id: 0.35 for z in city_config.zones}
        self._ingested_ids: Set[str] = set()

        # Identify upstream driver zones
        self._upstream_zones = [
            z.id for z in city_config.zones
            if getattr(z, "role", "") == "upstream_driver" or "nl" in z.id.lower()
        ]

    def step(self, clock_time: datetime, stream_view: StreamView) -> Dict[str, float]:
        """Compute zone-level cascade risk scores based on causal rainfall totals."""
        obs = stream_view.released()
        new_obs = [o for o in obs if o.obs_id not in self._ingested_ids]

        for o in new_obs:
            self._ingested_ids.add(o.obs_id)
            z = o.zone
            if not z or z not in self._rain_history:
                continue

            if "rain" in o.source or "rain" in o.system or "precip" in str(o.quality_flags):
                self._rain_history[z].append((o.event_time, float(o.value)))
            elif "soil" in o.source or "soil" in o.system:
                self._latest_soil[z] = min(1.0, max(0.0, float(o.value)))

        cutoff_24 = clock_time - timedelta(hours=24)
        cutoff_72 = clock_time - timedelta(hours=72)

        # Average upstream rainfall in last 24h
        upstream_24h_vals = []
        for uz in self._upstream_zones:
            tot = sum(v for t, v in self._rain_history[uz] if t >= cutoff_24)
            upstream_24h_vals.append(tot)
        mean_upstream_24 = float(np.mean(upstream_24h_vals)) if upstream_24h_vals else 0.0

        zone_scores: Dict[str, float] = {}
        for z in self.city_config.zones:
            hist = self._rain_history[z.id]
            r24 = sum(v for t, v in hist if t >= cutoff_24)
            r72 = sum(v for t, v in hist if t >= cutoff_72)
            soil = self._latest_soil[z.id]

            # Linear score components
            score_local = (r24 / max(1.0, self.thresh_24h_mm)) * 0.45 + (r72 / max(1.0, self.thresh_72h_mm)) * 0.35
            score_soil = (soil / max(0.1, self.thresh_soil)) * 0.20
            score_upstream = (mean_upstream_24 / max(1.0, self.thresh_24h_mm)) * 0.25 if z.id not in self._upstream_zones else 0.0

            total_idx = score_local + score_soil + score_upstream
            # Sigmoid response centered at 1.0 index
            prob = 1.0 / (1.0 + math.exp(-3.5 * (total_idx - 1.0)))
            zone_scores[z.id] = round(float(max(0.0, min(1.0, prob))), 4)

        return zone_scores


class ClimatologyPersistenceBaseline:
    """B3: Causal running event frequency blended with current state persistence."""

    def __init__(
        self,
        city_config: CityConfig,
        persistence_weight: float = 0.60,
    ):
        self.city_config = city_config
        self.persistence_weight = persistence_weight

        # zone -> count of hours in high/critical, total hours
        self._hours_high_crit: Dict[str, int] = {z.id: 0 for z in city_config.zones}
        self._total_steps: Dict[str, int] = {z.id: 0 for z in city_config.zones}
        self._latest_stress: Dict[str, float] = {z.id: 0.10 for z in city_config.zones}
        self._ingested_ids: Set[str] = set()

    def step(self, clock_time: datetime, stream_view: StreamView) -> Dict[str, float]:
        """Compute blended climatology-persistence risk scores."""
        obs = stream_view.released()
        new_obs = [o for o in obs if o.obs_id not in self._ingested_ids]

        for o in new_obs:
            self._ingested_ids.add(o.obs_id)
            z = o.zone
            if z in self._latest_stress:
                norm_v = min(1.0, max(0.0, float(o.value) / 100.0 if float(o.value) > 1.0 else float(o.value)))
                if norm_v > self._latest_stress[z]:
                    self._latest_stress[z] = norm_v

        zone_scores: Dict[str, float] = {}
        for z in self.city_config.zones:
            curr_s = self._latest_stress[z.id]
            self._total_steps[z.id] += 1
            if curr_s >= 0.60:
                self._hours_high_crit[z.id] += 1

            clim_freq = self._hours_high_crit[z.id] / max(1, self._total_steps[z.id])
            pers_score = curr_s

            blended = self.persistence_weight * pers_score + (1.0 - self.persistence_weight) * clim_freq
            zone_scores[z.id] = round(float(max(0.0, min(1.0, blended))), 4)

        return zone_scores
