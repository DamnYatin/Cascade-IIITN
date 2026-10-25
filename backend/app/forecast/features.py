"""Causal feature builder and stress normalisation.

Rules:
  - Causal normalisation: never fit scalers on full dataset. Only use data with arrival_time <= now.
  - No zero-filling of missing data; maintain missing value masks.
  - Zero hardcoded geography or system names.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import math
import numpy as np

from backend.app.schemas import CityConfig, Observation, QualityFlag


class CausalStressNormalizer:
    """Causally normalizes raw sensor readings into stress s in [0, 1].

    Uses system capacity or critical threshold from CityConfig when defined.
    If neither is defined, uses causal robust scaling (running median and IQR)
    computed strictly from past observations (arrival_time <= now).
    """

    def __init__(self, city_config: CityConfig, min_history_adaptive: int = 5):
        self.city_config = city_config
        self.min_history_adaptive = min_history_adaptive
        self._system_specs = {s.id: s for s in city_config.systems}
        # History per node for adaptive scaling: list of (arrival_time, value)
        self._history: Dict[str, List[Tuple[datetime, float]]] = defaultdict(list)

    def update_history(self, obs: Observation) -> None:
        """Record an observation in historical memory for adaptive scaling."""
        node = obs.node_id or f"{obs.zone}:{obs.system}"
        self._history[node].append((obs.arrival_time, float(obs.value)))

    def normalize(
        self,
        obs: Observation,
        clock_time: datetime,
    ) -> Tuple[float, str]:
        """Normalize an observation into stress s in [0, 1].

        Returns:
            (stress, method) where method is 'capacity', 'critical_threshold',
            'adaptive', or 'passthrough'.
        """
        system = obs.system
        val = float(obs.value)
        spec = self._system_specs.get(system)

        # 1. System capacity
        if spec and spec.capacity is not None and spec.capacity > 0:
            stress = max(0.0, min(1.0, val / float(spec.capacity)))
            return float(stress), "capacity"

        # 2. Critical threshold (default critical stress is 0.80)
        if spec and spec.critical_threshold is not None and spec.critical_threshold > 0:
            crit = float(spec.critical_threshold)
            # Map val == crit -> 0.80 stress
            # Using logistic or proportional mapping:
            # When val == 0 -> 0.0, val == crit -> 0.80, capped at 1.0
            stress = max(0.0, min(1.0, (val / crit) * 0.80))
            return float(stress), "critical_threshold"

        # 3. Adaptive causal robust scaling using strictly data with arrival_time <= clock_time
        node = obs.node_id or f"{obs.zone}:{obs.system}"
        past_values = [v for (arr, v) in self._history[node] if arr <= clock_time]
        if len(past_values) >= self.min_history_adaptive:
            med = float(np.median(past_values))
            q75, q25 = np.percentile(past_values, [75, 25])
            iqr = float(q75 - q25)
            denom = 1.349 * iqr if iqr > 1e-6 else 1.0
            z = (val - med) / denom
            # Sigmoid mapping to [0, 1]
            stress = 1.0 / (1.0 + math.exp(-max(-10.0, min(10.0, z))))
            return float(stress), "adaptive"

        # Fallback if insufficient history
        clamped = max(0.0, min(1.0, val if 0.0 <= val <= 1.0 else (val / 100.0 if val > 0 else 0.0)))
        return float(clamped), "passthrough"


class CausalExogenousFeatureBuilder:
    """Builds causal rainfall, soil moisture, and saturation features per zone.

    Features:
      - rain_1h: sum of rainfall in (clock_time - 1h, clock_time]
      - rain_6h: rolling sum in (clock_time - 6h, clock_time]
      - rain_24h: rolling sum in (clock_time - 24h, clock_time]
      - rain_72h: rolling sum in (clock_time - 72h, clock_time]
      - rain_168h: rolling sum in (clock_time - 168h, clock_time]
      - soil_moisture: most recent valid soil moisture observation <= clock_time
      - saturation_gain: rain_1h * soil_moisture (if both present)

    Causality guarantee:
      Only observations with arrival_time <= clock_time and event_time <= clock_time
      are ever considered.
    """

    def __init__(self, city_config: CityConfig):
        self.city_config = city_config
        # Store observations per zone:
        # rain: list of (event_time, arrival_time, value_mm)
        # soil: list of (event_time, arrival_time, value_fraction)
        self._rain_records: Dict[str, List[Tuple[datetime, datetime, float]]] = defaultdict(list)
        self._soil_records: Dict[str, List[Tuple[datetime, datetime, float]]] = defaultdict(list)

    def ingest(self, obs: Observation) -> None:
        """Ingest a new observation into internal store."""
        # Detect rainfall or soil moisture by system/source name
        sys_lower = obs.system.lower()
        src_lower = obs.source.lower()

        is_rain = "rain" in sys_lower or "precip" in sys_lower or "rain" in src_lower
        is_soil = "soil" in sys_lower or "moist" in sys_lower or "soil" in src_lower

        if is_rain:
            self._rain_records[obs.zone].append((obs.event_time, obs.arrival_time, float(obs.value)))
        elif is_soil:
            self._soil_records[obs.zone].append((obs.event_time, obs.arrival_time, float(obs.value)))

    def get_features(
        self,
        zone: str,
        clock_time: datetime,
    ) -> Tuple[Dict[str, float], Dict[str, bool]]:
        """Compute causal features at clock_time for zone.

        Returns:
            (features_dict, mask_dict)
            features_dict: feature name -> float (or NaN if missing)
            mask_dict: feature name -> bool (True if valid, False if missing)
        """
        # Filter available rain observations: arrival_time <= clock_time and event_time <= clock_time
        valid_rain = [
            (ev, val)
            for (ev, arr, val) in self._rain_records.get(zone, [])
            if arr <= clock_time and ev <= clock_time
        ]

        def rolling_sum(hours: float) -> Optional[float]:
            cutoff = clock_time - timedelta(hours=hours)
            sub = [val for (ev, val) in valid_rain if cutoff < ev <= clock_time]
            if not sub and not valid_rain:
                return None
            return float(sum(sub))

        rain_1h = rolling_sum(1.0)
        rain_6h = rolling_sum(6.0)
        rain_24h = rolling_sum(24.0)
        rain_72h = rolling_sum(72.0)
        rain_168h = rolling_sum(168.0)

        # Soil moisture: latest available <= clock_time
        valid_soil = [
            (ev, val)
            for (ev, arr, val) in self._soil_records.get(zone, [])
            if arr <= clock_time and ev <= clock_time
        ]
        soil_moisture: Optional[float] = None
        if valid_soil:
            # Sort by event_time ascending and take latest
            valid_soil.sort(key=lambda x: x[0])
            soil_moisture = valid_soil[-1][1]

        # Saturation gain
        saturation_gain: Optional[float] = None
        if rain_1h is not None and soil_moisture is not None:
            saturation_gain = rain_1h * soil_moisture

        feats: Dict[str, float] = {}
        masks: Dict[str, bool] = {}

        for k, v in [
            ("rain_1h", rain_1h),
            ("rain_6h", rain_6h),
            ("rain_24h", rain_24h),
            ("rain_72h", rain_72h),
            ("rain_168h", rain_168h),
            ("soil_moisture", soil_moisture),
            ("saturation_gain", saturation_gain),
        ]:
            if v is not None:
                feats[k] = float(v)
                masks[k] = True
            else:
                feats[k] = float("nan")
                masks[k] = False

        return feats, masks


def get_city_nodes(city_config: CityConfig) -> List[str]:
    """Return all valid 'zone_id:system_id' node IDs for the city."""
    nodes: List[str] = []
    system_ids = [s.id for s in city_config.systems]
    for zone in city_config.zones:
        # If zone defines a specific subset of systems, use it, else all systems
        zone_systems = zone.systems if zone.systems is not None else system_ids
        for sys_id in zone_systems:
            nodes.append(f"{zone.id}:{sys_id}")
    return sorted(nodes)


def is_upstream_driver(zone_id: str, city_config: CityConfig) -> bool:
    """Return True if zone is an upstream driver (e.g. Nagaland hills)."""
    for z in city_config.zones:
        if z.id == zone_id and z.role == "upstream_driver":
            return True
    return False
