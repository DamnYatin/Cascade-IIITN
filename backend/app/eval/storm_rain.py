"""Stochastic multi-storm rainfall generator.

Generates hourly, spatially correlated rainfall across city zones with:
  - Poisson storm arrivals with random duration and intensity
  - Spatial footprint and upstream-to-downstream lag
  - Non-negative, bell-shaped temporal profiles
  - Optional quiet/control low-rain profiles
  - Fully deterministic with SeedSequence-derived NumPy generators

MODIFICATION / MODELLING NOTE:
  The mathematical form of this synthetic storm generator is a modelling choice
  designed to simulate the orographic storm bursts observed in the Nagaland hills
  flowing into Upper Assam lowlands. Evaluation numbers on synthetic scenarios
  are conditioned on this model family.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from backend.app.schemas import CityConfig, Zone


class StochasticStormRainGenerator:
    """Generates synthetic hourly rainfall series across zones with upstream lag."""

    def __init__(
        self,
        arrival_rate: float = 0.04,  # Mean storms per hour (~1 storm every 25 hours)
        min_intensity_mm: float = 15.0,
        max_intensity_mm: float = 60.0,
        min_duration_hours: int = 4,
        max_duration_hours: int = 14,
        upstream_lag_hours: float = 3.0,
        diurnal_amplitude: float = 0.15,
    ):
        self.arrival_rate = arrival_rate
        self.min_intensity_mm = min_intensity_mm
        self.max_intensity_mm = max_intensity_mm
        self.min_duration_hours = min_duration_hours
        self.max_duration_hours = max_duration_hours
        self.upstream_lag_hours = upstream_lag_hours
        self.diurnal_amplitude = diurnal_amplitude

    def _zone_lag(self, zone: Zone, upstream_zones: List[str]) -> float:
        """Compute lag relative to upstream drivers."""
        if zone.id in upstream_zones or getattr(zone, "role", "") == "upstream_driver":
            return 0.0

        # If river link directly targets this zone, apply standard lag
        for u in upstream_zones:
            if hasattr(zone, "river_links"):
                for rl in getattr(zone, "river_links", []):
                    if isinstance(rl, dict) and rl.get("target") == zone.id:
                        return self.upstream_lag_hours
            if hasattr(zone, "neighbours") and u in getattr(zone, "neighbours", []):
                return self.upstream_lag_hours

        # Farther downstream zones get larger lag
        return self.upstream_lag_hours * 1.8

    def generate(
        self,
        zones: List[Zone],
        duration_hours: int,
        seed: int = 42,
    ) -> Dict[str, Dict[int, float]]:
        """Generate spatially correlated hourly rainfall per zone.

        Returns:
            dict[zone_id, dict[hour_int, mm_rainfall]]
        """
        rng = np.random.default_rng(seed)
        zone_ids = [z.id for z in zones]
        rain: Dict[str, Dict[int, float]] = {z: {h: 0.0 for h in range(duration_hours + 1)} for z in zone_ids}

        # Identify upstream driver zones
        upstream_zones = [
            z.id for z in zones
            if getattr(z, "role", "") == "upstream_driver"
            or "nl" in z.id.lower()
            or "mon" in z.id.lower()
        ]
        if not upstream_zones and zones:
            upstream_zones = [zones[0].id]

        zone_lags = {z.id: self._zone_lag(z, upstream_zones) for z in zones}

        # Sample storm arrival times using Poisson process
        t = 2
        while t < duration_hours - self.min_duration_hours:
            # Poisson arrival check: P(arrival in hour) = 1 - exp(-rate)
            p_arrival = 1.0 - math.exp(-self.arrival_rate)
            if rng.random() < p_arrival:
                storm_dur = int(rng.integers(self.min_duration_hours, self.max_duration_hours + 1))
                peak_intensity = float(rng.uniform(self.min_intensity_mm, self.max_intensity_mm))
                spatial_coverage = rng.choice([0.6, 0.8, 1.0], p=[0.2, 0.5, 0.3])

                # Upstream zones always get hit
                hit_zones = set(upstream_zones)
                for z in zones:
                    if z.id not in hit_zones and rng.random() < spatial_coverage:
                        hit_zones.add(z.id)

                for z_id in hit_zones:
                    lag = zone_lags[z_id]
                    z_start = t + int(round(lag))
                    # Spatial variance in intensity
                    z_peak = peak_intensity * float(rng.uniform(0.75, 1.25))

                    for step in range(storm_dur):
                        h = z_start + step
                        if h > duration_hours:
                            break
                        # Smooth bell-curve temporal profile: sin^2(pi * step / dur)
                        frac = float(step + 0.5) / float(storm_dur)
                        profile = math.sin(math.pi * frac) ** 2
                        # Optional diurnal modulation: slightly heavier in late afternoon
                        diurnal = 1.0 + self.diurnal_amplitude * math.sin(2.0 * math.pi * (h % 24) / 24.0)
                        mm = z_peak * profile * diurnal
                        rain[z_id][h] = round(rain[z_id][h] + max(0.0, mm), 2)

                # Skip past this storm duration
                t += max(3, storm_dur // 2)
            else:
                t += 1

        return rain

    def generate_quiet(
        self,
        zones: List[Zone],
        duration_hours: int,
        seed: int = 42,
    ) -> Dict[str, Dict[int, float]]:
        """Generate low-rain negative control: minimal background drizzle, 0 critical storms."""
        rng = np.random.default_rng(seed)
        zone_ids = [z.id for z in zones]
        rain: Dict[str, Dict[int, float]] = {z: {} for z in zone_ids}

        for z in zone_ids:
            for h in range(duration_hours + 1):
                # Light drizzle <= 1.0 mm/h
                drizzle = float(rng.uniform(0.0, 0.8)) if rng.random() < 0.15 else 0.0
                rain[z][h] = round(drizzle, 2)

        return rain
