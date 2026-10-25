"""B1: Isolated Monitoring Baseline.

Rule V1:
  - Consumes STRICTLY StreamView.
  - No dependency modelling (siloed system).
  - Each node tracks its own stress and extrapolates short-term linear trend.
  - Zone alert score is the maximum of isolated node stresses in that zone.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set
import numpy as np

from backend.app.replay.stream import StreamView
from backend.app.schemas import CityConfig, Observation


class IsolatedMonitoringBaseline:
    """Isolated per-node monitoring baseline without cross-system dependency modeling."""

    def __init__(
        self,
        city_config: CityConfig,
        trend_lookback_hours: float = 6.0,
        projection_horizon_hours: float = 6.0,
    ):
        self.city_config = city_config
        self.trend_lookback_hours = trend_lookback_hours
        self.projection_horizon_hours = projection_horizon_hours

        # node -> list of (timestamp, stress)
        self._history: Dict[str, List[tuple[datetime, float]]] = {}
        self._latest_stress: Dict[str, float] = {}
        self._ingested_ids: Set[str] = set()

        for z in city_config.zones:
            for s in city_config.systems:
                if not z.systems or s.id in z.systems:
                    node = f"{z.id}:{s.id}"
                    self._history[node] = []
                    self._latest_stress[node] = 0.08  # Baseline resting stress

    def step(self, clock_time: datetime, stream_view: StreamView) -> Dict[str, float]:
        """Process observations released up to clock_time and return zone scores in [0, 1]."""
        obs = stream_view.released()
        new_obs = [o for o in obs if o.obs_id not in self._ingested_ids]
        for o in new_obs:
            self._ingested_ids.add(o.obs_id)

            node = f"{o.zone}:{o.system}"
            if node in self._latest_stress:
                # Normalise raw sensor value to [0, 1] stress estimate
                raw_v = float(o.value)
                norm_v = min(1.0, max(0.0, raw_v / 100.0 if raw_v > 1.0 else raw_v))
                self._latest_stress[node] = norm_v
                self._history[node].append((o.event_time, norm_v))

        # Zone scores: max projected stress across nodes in that zone
        zone_scores: Dict[str, float] = {}
        cutoff = clock_time - timedelta(hours=self.trend_lookback_hours)

        for z in self.city_config.zones:
            z_max_score = 0.0
            for s in self.city_config.systems:
                node = f"{z.id}:{s.id}"
                if node not in self._latest_stress:
                    continue

                curr_s = self._latest_stress[node]
                hist = [item for item in self._history[node] if item[0] >= cutoff]

                if len(hist) >= 2:
                    t_first, s_first = hist[0]
                    t_last, s_last = hist[-1]
                    dt_hours = (t_last - t_first).total_seconds() / 3600.0
                    if dt_hours > 0.5:
                        slope = (s_last - s_first) / dt_hours
                        projected = curr_s + slope * self.projection_horizon_hours
                    else:
                        projected = curr_s
                else:
                    projected = curr_s

                proj_bounded = float(max(0.0, min(1.0, projected)))
                if proj_bounded > z_max_score:
                    z_max_score = proj_bounded

            zone_scores[z.id] = round(z_max_score, 4)

        return zone_scores
