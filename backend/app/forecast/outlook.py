"""Rain outlook models for multi-horizon cascade rollouts.

Rules:
  - R2: Never read observed rain after issue_time to drive rollouts.
  - Causal isolation: PersistenceDecay and BlockBootstrap use only data with arrival_time <= issue_time.
  - OracleOutlook: Strictly locked out unless FORECAST_ALLOW_ORACLE=1 and diagnostic=True.
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Protocol, Tuple
import numpy as np

from backend.app.schemas import Observation


class RainOutlook(Protocol):
    """Protocol for generating probabilistic rain scenario paths without future leakage."""

    def sample(
        self,
        zone: str,
        issue_time: datetime,
        horizon_hours: int,
        n: int,
        rng: np.random.Generator,
    ) -> np.ndarray:
        """Sample n future rainfall paths of length horizon_hours.

        Returns:
            np.ndarray of shape (n, horizon_hours) in mm/h.
        """
        ...


class PersistenceDecayOutlook:
    """Recent rainfall intensity decaying toward climatology with stochastic bursts."""

    def __init__(
        self,
        climatology_mm: float = 2.0,
        decay_half_life_hours: float = 12.0,
        burst_probability: float = 0.15,
        burst_mean_mm: float = 8.0,
    ):
        self.climatology_mm = climatology_mm
        self.decay_rate = np.exp(-np.log(2.0) / max(1.0, decay_half_life_hours))
        self.burst_probability = burst_probability
        self.burst_mean_mm = burst_mean_mm
        # zone -> list of (event_time, arrival_time, value_mm)
        self._history: Dict[str, List[Tuple[datetime, datetime, float]]] = defaultdict(list)

    def ingest(self, obs: Observation) -> None:
        """Ingest rainfall observation."""
        if "rain" in obs.system.lower() or "precip" in obs.system.lower() or "rain" in obs.source.lower():
            self._history[obs.zone].append((obs.event_time, obs.arrival_time, float(obs.value)))

    def sample(
        self,
        zone: str,
        issue_time: datetime,
        horizon_hours: int,
        n: int,
        rng: np.random.Generator,
    ) -> np.ndarray:
        # Strictly filter data with arrival_time <= issue_time and event_time <= issue_time
        records = [
            (ev, val)
            for (ev, arr, val) in self._history.get(zone, [])
            if arr <= issue_time and ev <= issue_time
        ]

        # Recent 6h mean intensity
        t_6h = issue_time - timedelta(hours=6)
        recent_vals = [val for (ev, val) in records if t_6h < ev <= issue_time]
        recent_mean = float(np.mean(recent_vals)) if recent_vals else self.climatology_mm

        samples = np.zeros((n, horizon_hours), dtype=np.float64)
        for h in range(horizon_hours):
            # Mean intensity decaying from recent_mean to climatology
            step = h + 1
            decay = self.decay_rate ** step
            mu = self.climatology_mm + (recent_mean - self.climatology_mm) * decay

            # Base rainfall from gamma distribution around mu
            shape = 2.0
            scale = max(1e-4, mu / shape)
            base = rng.gamma(shape, scale, size=n)

            # Stochastic burst shocks
            bursts = rng.binomial(1, self.burst_probability, size=n) * rng.exponential(
                self.burst_mean_mm, size=n
            )
            samples[:, h] = np.maximum(0.0, base + bursts)

        return samples


class BlockBootstrapOutlook:
    """Block-bootstrap of zone's own historical hourly rainfall observed before issue_time."""

    def __init__(self, block_hours: int = 6):
        self.block_hours = block_hours
        self._history: Dict[str, List[Tuple[datetime, datetime, float]]] = defaultdict(list)
        self._fallback = PersistenceDecayOutlook()

    def ingest(self, obs: Observation) -> None:
        if "rain" in obs.system.lower() or "precip" in obs.system.lower() or "rain" in obs.source.lower():
            self._history[obs.zone].append((obs.event_time, obs.arrival_time, float(obs.value)))
            self._fallback.ingest(obs)

    def sample(
        self,
        zone: str,
        issue_time: datetime,
        horizon_hours: int,
        n: int,
        rng: np.random.Generator,
    ) -> np.ndarray:
        # Valid historical series
        records = [
            (ev, val)
            for (ev, arr, val) in self._history.get(zone, [])
            if arr <= issue_time and ev <= issue_time
        ]
        # Sort chronologically
        records.sort(key=lambda x: x[0])

        if len(records) < 24:
            # Insufficient history: fall back to PersistenceDecay
            return self._fallback.sample(zone, issue_time, horizon_hours, n, rng)

        values = np.array([val for (_, val) in records], dtype=np.float64)
        num_blocks = int(np.ceil(horizon_hours / self.block_hours))
        samples = np.zeros((n, horizon_hours), dtype=np.float64)

        max_start = max(1, len(values) - self.block_hours)
        for i in range(n):
            traj = []
            for _ in range(num_blocks):
                idx = rng.integers(0, max_start)
                traj.extend(values[idx : idx + self.block_hours])
            samples[i, :] = np.array(traj[:horizon_hours], dtype=np.float64)

        return samples


class ForecastProductOutlook:
    """Stub raising NotImplementedError for unconfigured external forecast products."""

    def sample(
        self,
        zone: str,
        issue_time: datetime,
        horizon_hours: int,
        n: int,
        rng: np.random.Generator,
    ) -> np.ndarray:
        raise NotImplementedError(
            "External forecast product without hindsight is not configured. "
            "Use PersistenceDecayOutlook or BlockBootstrapOutlook."
        )


class OracleOutlook:
    """Diagnostic-only oracle outlook returning true future rain.

    Strictly gated by environment variable FORECAST_ALLOW_ORACLE=1 and diagnostic=True.
    """

    def __init__(
        self,
        future_rain_series: Dict[str, Dict[datetime, float]],
        diagnostic: bool = False,
    ):
        allow_env = os.environ.get("FORECAST_ALLOW_ORACLE", "0") == "1"
        if not (allow_env and diagnostic):
            raise PermissionError(
                "OracleOutlook is locked out! Requires environment variable "
                "FORECAST_ALLOW_ORACLE=1 AND diagnostic=True. Never usable in default runs."
            )
        self.future_rain_series = future_rain_series
        self.is_oracle: bool = True

    def sample(
        self,
        zone: str,
        issue_time: datetime,
        horizon_hours: int,
        n: int,
        rng: np.random.Generator,
    ) -> np.ndarray:
        zone_series = self.future_rain_series.get(zone, {})
        truth = []
        for h in range(1, horizon_hours + 1):
            t_step = issue_time + timedelta(hours=h)
            truth.append(zone_series.get(t_step, 0.0))

        arr = np.array(truth, dtype=np.float64)
        # Replicate across rollouts
        return np.tile(arr, (n, 1))
