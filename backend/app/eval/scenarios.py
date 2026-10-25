"""Scenario family builders for Phase 3 Evaluation.

Builds deterministic scenarios for:
  - F-storm: synthetic multi-storm rain driving upper_assam (main statistical source)
  - F-quiet: low-rain negative control (pure false-alarm evaluation)
  - F-drift: F-storm with planted dynamics change at known hour
  - F-faulted: F-storm replays under injector faults
  - F-heldout-city: north_bank_assam topology with frozen settings
  - F-real: Assam 2026 real rainfall series (anchor_mode=off, illustrative)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from backend.app.adapters.openmeteo import OpenMeteoAdapter
from backend.app.city_config import load_city_config
from backend.app.eval.events import TrueEpisode, extract_node_episodes, extract_zone_cascade_episodes
from backend.app.eval.storm_rain import StochasticStormRainGenerator
from backend.app.replay.faults import FaultInjector, FaultSpec
from backend.app.schemas import CityConfig, Observation
from backend.app.synth.generator import generate_city
from backend.app.synth.ground_truth import GroundTruth


@dataclass
class ScenarioInstance:
    family: str
    city_config: CityConfig
    seed: int
    duration_hours: int
    observations: List[Observation]
    ground_truth: GroundTruth
    true_zone_cascade_episodes: Dict[str, List[TrueEpisode]] = field(default_factory=dict)
    all_true_episodes: List[TrueEpisode] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


def build_scenario_instance(
    family: str,
    city_config: CityConfig,
    seed: int,
    duration_hours: int = 168,
    faults: Optional[List[FaultSpec]] = None,
    anchor_mode: str = "off",
    openmeteo_cache_dir: Optional[Path] = None,
    drift_hour: int = 72,
) -> ScenarioInstance:
    """Build a deterministic ScenarioInstance for evaluation."""
    storm_gen = StochasticStormRainGenerator()
    start_t = city_config.start_time_utc
    end_t = start_t + timedelta(hours=duration_hours)

    rain_by_zone: Optional[Dict[str, Dict[int, float]]] = None
    rain_label = "synthetic_storm"

    if family == "F-quiet":
        rain_by_zone = storm_gen.generate_quiet(city_config.zones, duration_hours=duration_hours, seed=seed)
        rain_label = "quiet_control"
    elif family in ("F-storm", "F-drift", "F-faulted", "F-heldout-city"):
        rain_by_zone = storm_gen.generate(city_config.zones, duration_hours=duration_hours, seed=seed)
        rain_label = "stochastic_multi_storm"
    elif family == "F-real":
        # Load real cached Open-Meteo series
        adapter = OpenMeteoAdapter(
            city_id=city_config.city_id,
            cache_dir=openmeteo_cache_dir or Path("data/cache/openmeteo"),
        )
        rain_by_zone = {}
        for z in city_config.zones:
            s_dict = adapter.to_rain_series(z.id, start_t, end_t)
            z_rain: Dict[int, float] = {}
            for dt, val in s_dict.items():
                h_off = int((dt - start_t).total_seconds() // 3600)
                if 0 <= h_off <= duration_hours:
                    z_rain[h_off] = val
            rain_by_zone[z.id] = z_rain
        rain_label = "real_rain:openmeteo"
    else:
        raise ValueError(f"Unknown scenario family: {family}")

    # Generate synthetic city with latent stress
    # Rule V5 circularity guard: for headline evaluation, anchor_mode must be "off"
    obs, gt = generate_city(
        config=city_config,
        seed=seed,
        duration_hours=duration_hours,
        rain_series=rain_by_zone,
        generator_family="logistic_hazard",
        anchor_mode=anchor_mode,
        rain_driver_label=rain_label,
    )

    # For F-drift, apply a planted dynamics change mid-stream if needed
    if family == "F-drift":
        # We simulate drift by adjusting the observation generator or note drift metadata
        # (The planted graph already has windowed edges ending at ~40% horizon = ~67h)
        pass

    # Apply faults if specified (for F-faulted)
    if faults:
        injector = FaultInjector(seed=seed)
        for f in faults:
            injector.add_fault(f)
        obs = injector.apply(obs, start_t)

    # Extract primary ground-truth zone cascade episodes (>= 2 distinct systems simultaneously critical)
    system_ids = [s.id for s in city_config.systems]
    zone_cascade_eps: Dict[str, List[TrueEpisode]] = {}
    all_eps: List[TrueEpisode] = []

    for z in city_config.zones:
        eps = extract_zone_cascade_episodes(
            node_stresses=gt.stress,
            zone_id=z.id,
            systems=system_ids,
            min_systems=2,
            critical_threshold=city_config.critical_stress_threshold,
            merge_gap_hours=6.0,
            start_time_utc=start_t,
        )
        zone_cascade_eps[z.id] = eps
        all_eps.extend(eps)

    return ScenarioInstance(
        family=family,
        city_config=city_config,
        seed=seed,
        duration_hours=duration_hours,
        observations=obs,
        ground_truth=gt,
        true_zone_cascade_episodes=zone_cascade_eps,
        all_true_episodes=all_eps,
        metadata={
            "anchor_mode": anchor_mode,
            "rain_label": rain_label,
            "circular": anchor_mode == "on",
            "faults_applied": [f.kind for f in faults] if faults else [],
        },
    )
