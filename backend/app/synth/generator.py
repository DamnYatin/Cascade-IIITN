"""Synthetic city generator with a hidden planted dependency graph.

This module owns ground truth: it simulates latent stress across (zone, system) nodes
driven by exogenous real rain or synthetic storms, computes CRITICAL episodes, and
derives observation streams.

Ground truth is NEVER placed on the replay stream view -- only Observation objects are.
Future model code must never import from this package.

Honesty rule:
  `anchor_mode: "off" | "on"` (default "off").
  When "on", outputs carry `QualityFlag.ANCHORED` / "anchored=true" with explicit disclosure.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple, Union

import numpy as np

from ..schemas import (
    CityConfig,
    Observation,
    QualityFlag,
    SourceKind,
    StreamSpec,
)
from .ground_truth import CriticalEpisode, GroundTruth
from .planted_graph import build_planted_graph, edges_to_schema

# Per-system physical dynamics
_SYSTEM_PARAMS = {
    "river_embankment": {"bias": 0.02, "decay": 0.94, "rain_sensitivity": 0.65, "scale": 100.0},
    "drainage": {"bias": 0.02, "decay": 0.94, "rain_sensitivity": 0.60, "scale": 100.0},
    "transport": {"bias": 0.01, "decay": 0.90, "rain_sensitivity": 0.0, "scale": 100.0},
    "roads": {"bias": 0.01, "decay": 0.90, "rain_sensitivity": 0.0, "scale": 100.0},
    "emergency_response": {"bias": 0.008, "decay": 0.92, "rain_sensitivity": 0.0, "scale": 80.0},
    "health": {"bias": 0.005, "decay": 0.93, "rain_sensitivity": 0.0, "scale": 100.0},
    "hospital": {"bias": 0.005, "decay": 0.93, "rain_sensitivity": 0.0, "scale": 100.0},
    "power": {"bias": 0.006, "decay": 0.96, "rain_sensitivity": 0.0, "scale": 100.0},
    "comms": {"bias": 0.004, "decay": 0.95, "rain_sensitivity": 0.0, "scale": 100.0},
}


def _system_params(sys_id: str) -> dict:
    return _SYSTEM_PARAMS.get(
        sys_id, {"bias": 0.01, "decay": 0.90, "rain_sensitivity": 0.0, "scale": 100.0}
    )


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))


def _parent_influence(edge, stress: dict[str, list[float]], t: int) -> float:
    lag = int(round(edge.lag_hours))
    src_t = t - lag
    if src_t < 0 or edge.u not in stress:
        return 0.0
    return stress[edge.u][src_t]


def _edge_active(edge, start_time_utc: datetime, t: int) -> bool:
    if edge.active_start is None and edge.active_end is None:
        return True
    hour_dt = start_time_utc + timedelta(hours=t)
    if edge.active_start is not None and hour_dt < edge.active_start:
        return False
    if edge.active_end is not None and hour_dt > edge.active_end:
        return False
    return True


def _simulate_stress(
    config: CityConfig,
    graph,
    nodes: list[str],
    rain_by_zone_hour: dict[str, dict[int, float]],
    duration_hours: int,
    family: str,
    anchor_mode: str,
    rng: np.random.Generator,
    patches: Optional[list[Any]] = None,
) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    """Run latent stress simulation hour by hour."""
    params = {s.id: _system_params(s.id) for s in config.systems}
    stress: dict[str, list[float]] = {n: [0.08] * (duration_hours + 1) for n in nodes}
    rain_input: dict[str, list[float]] = {n: [0.0] * (duration_hours + 1) for n in nodes}

    parents: dict[str, list] = {}
    for e in graph.edges:
        parents.setdefault(e.v, []).append(e)

    start_time_utc = config.start_time_utc
    is_anchored = anchor_mode.lower() == "on"

    for t in range(1, duration_hours + 1):
        for n in nodes:
            zone, sysid = n.split(":")
            p = params[sysid]

            # Exogenous rain drives river_embankment / drainage
            rain_mm = rain_by_zone_hour.get(zone, {}).get(t, 0.0)
            rain_in = 0.0
            if sysid in ("river_embankment", "drainage"):
                # Scale real mm/h to latent stress contribution
                scale_mult = 1.6 if is_anchored else 1.0
                rain_in = rain_mm * p["rain_sensitivity"] * 0.10 * scale_mult
            rain_input[n][t] = rain_in

            if family == "logistic_hazard":
                z = p["bias"] + rain_in
                for e in parents.get(n, []):
                    if not _edge_active(e, start_time_utc, t):
                        continue
                    z += e.weight * _parent_influence(e, stress, t)
                hazard = _sigmoid(z - 2.2)
                new_s = p["decay"] * stress[n][t - 1] + (1.0 - p["decay"]) * hazard


            else:
                # threshold_nonlinear
                z = p["bias"] + rain_in
                for e in parents.get(n, []):
                    if not _edge_active(e, start_time_utc, t):
                        continue
                    su = _parent_influence(e, stress, t)
                    if su > 0.45:
                        z += e.weight * (su - 0.45)
                hazard = math.tanh(z) * 0.5
                new_s = p["decay"] * stress[n][t - 1] + hazard

            # Process noise
            new_s += rng.normal(0.0, 0.015)

            # Apply latent patches (counterfactual intervention execution)
            if patches:
                step_hour = float(t)
                for p in patches:
                    if p.start_hour <= step_hour <= p.end_hour:
                        ptype = getattr(p, "patch_type", None)
                        ptype_val = ptype.value if hasattr(ptype, "value") else str(ptype)
                        nom_val = getattr(p, "nominal_value", 0.0)

                        if ptype_val == "add_bias" and p.target == n:
                            new_s += nom_val
                        elif ptype_val == "cap_stress" and p.target == n:
                            new_s = min(new_s, nom_val)
                        elif ptype_val == "add_edge" and getattr(p, "v", None) == n:
                            lag = int(round(getattr(p, "lag", 1.0) or 1.0))
                            src_t = t - lag
                            u_node = getattr(p, "u", None)
                            u_val = stress[u_node][src_t] if (u_node and src_t >= 0 and u_node in stress) else 0.0
                            new_s += nom_val * u_val
                        elif ptype_val == "exposure_change":
                            target_zone = getattr(p, "target", "")
                            if n.startswith(f"{target_zone}:") and ("health" in n or "emergency_response" in n):
                                new_s = 0.10 + (new_s - 0.10) * nom_val

            stress[n][t] = max(0.0, min(1.0, new_s))

    return stress, rain_input


def _critical_episodes(
    stress: dict[str, list[float]], threshold: float
) -> tuple[list[CriticalEpisode], list[tuple[int, int]]]:
    """Detect contiguous CRITICAL runs per node and city-wide."""
    episodes: list[CriticalEpisode] = []
    city_critical_hours: set[int] = set()

    for node_id, series in stress.items():
        in_ep = False
        start_h = 0
        peak = 0.0
        for h, val in enumerate(series):
            if val >= threshold:
                city_critical_hours.add(h)
                if not in_ep:
                    in_ep = True
                    start_h = h
                    peak = val
                else:
                    peak = max(peak, val)
            else:
                if in_ep:
                    episodes.append(CriticalEpisode(node_id, start_h, h - 1, peak))
                    in_ep = False
                    peak = 0.0
        if in_ep:
            episodes.append(CriticalEpisode(node_id, start_h, len(series) - 1, peak))

    city_ranges: list[tuple[int, int]] = []
    sorted_hours = sorted(city_critical_hours)
    if sorted_hours:
        run_start = sorted_hours[0]
        prev = sorted_hours[0]
        for h in sorted_hours[1:]:
            if h == prev + 1:
                prev = h
            else:
                city_ranges.append((run_start, prev))
                run_start = h
                prev = h
        city_ranges.append((run_start, prev))

    return episodes, city_ranges


def _build_observations(
    config: CityConfig,
    stress: dict[str, list[float]],
    start_time_utc: datetime,
    duration_hours: int,
    anchor_mode: str,
    rain_driver_label: str,
    rng: np.random.Generator,
) -> list[Observation]:
    """Derive observations from stress according to StreamSpec."""
    observations: list[Observation] = []

    def hour_of(t: datetime) -> int:
        return int((t - start_time_utc).total_seconds() // 3600)

    obs_counter = 0
    is_anchored = anchor_mode.lower() == "on"

    for stream in config.streams:
        sys_scale = _system_params(stream.system)["scale"]

        k = 0
        while True:
            event_time = start_time_utc + timedelta(hours=k * stream.cadence_hours)
            h = hour_of(event_time)
            if h > duration_hours:
                break

            for zone in config.zones:
                if zone.systems and stream.system not in zone.systems:
                    continue

                node_id = f"{zone.id}:{stream.system}"
                base_value = stress.get(node_id, [0.1] * (duration_hours + 1))[h]
                value = base_value * sys_scale

                # Measurement noise
                value += rng.normal(0.0, stream.noise_level * sys_scale * 0.1)
                value = max(0.0, value)

                flags: list[QualityFlag | str] = []

                if stream.source_kind == SourceKind.SIMULATED:
                    flags.append(QualityFlag.SIMULATED)
                    flags.append(f"driver={rain_driver_label}")
                elif stream.source_kind == SourceKind.REAL:
                    flags.append(QualityFlag.REAL)

                if is_anchored:
                    flags.append(QualityFlag.ANCHORED)
                    flags.append("anchored=true:calibrated_to_historical_outcomes")

                is_citizen = stream.source == "citizen_report"
                if is_citizen:
                    flags.append(QualityFlag.CITIZEN_REPORT)
                    frr = getattr(stream, "false_report_rate", 0.1)
                    if rng.random() < frr:
                        value = float(rng.uniform(0.0, sys_scale))
                        flags.append(QualityFlag.LOW_CONFIDENCE)

                delay_hours = float(
                    stream.typical_delay_hours
                    + rng.uniform(0.0, max(stream.typical_delay_hours, 0.5) * 0.5)
                )
                arrival_time = event_time + timedelta(hours=delay_hours)

                observations.append(
                    Observation(
                        obs_id=f"sim:{obs_counter}",
                        source=stream.source,
                        source_kind=stream.source_kind,
                        zone=zone.id,
                        system=stream.system,
                        value=round(float(value), 4),
                        event_time=event_time,
                        arrival_time=arrival_time,
                        quality_flags=flags,
                        node_id=node_id,
                    )
                )
                obs_counter += 1
            k += 1

    observations.sort(key=lambda o: (o.arrival_time, o.event_time, o.obs_id))
    return observations


def generate_city(
    config: CityConfig,
    seed: int,
    duration_hours: int,
    rain_series: Optional[Union[dict[int, float], dict[str, dict[int, float]]]] = None,
    generator_family: str = "logistic_hazard",
    anchor_mode: str = "off",
    rain_driver_label: str = "real_rain:openmeteo",
    patches: Optional[list[Any]] = None,
) -> tuple[list[Observation], GroundTruth]:
    """Generate deterministic synthetic city stream and isolated ground truth."""
    if generator_family not in ("logistic_hazard", "threshold_nonlinear"):
        raise ValueError(f"unknown generator_family {generator_family!r}")

    rng = np.random.default_rng(seed)
    start_time_utc = config.start_time_utc

    # Normalise rain_series to per-zone dict[zone, dict[hour, mm]]
    rain_by_zone_hour: dict[str, dict[int, float]] = {}

    if rain_series is None:
        rain_driver_label = "synthetic_storm"
        # Synthetic storms
        for z in config.zones:
            z_rain: dict[int, float] = {}
            t = 0
            while t <= duration_hours:
                if rng.random() < 1.0 / 24.0:
                    dur = int(rng.integers(3, 8))
                    intensity = float(rng.uniform(5.0, 35.0))
                    for hh in range(dur):
                        if t + hh <= duration_hours:
                            z_rain[t + hh] = z_rain.get(t + hh, 0.0) + intensity
                t += 1
            rain_by_zone_hour[z.id] = z_rain
    elif all(isinstance(v, dict) for v in rain_series.values()):
        # Already keyed by zone_id
        rain_by_zone_hour = rain_series  # type: ignore
    else:
        # Single series provided for all zones
        for z in config.zones:
            rain_by_zone_hour[z.id] = dict(rain_series)  # type: ignore

    graph = build_planted_graph(config.zones, config.systems, start_time_utc, seed)

    nodes = []
    for z in config.zones:
        for s in config.systems:
            if not z.systems or s.id in z.systems:
                nodes.append(f"{z.id}:{s.id}")

    stress, rain_input = _simulate_stress(
        config, graph, nodes, rain_by_zone_hour, duration_hours,
        generator_family, anchor_mode, rng, patches=patches,
    )

    episodes, city_ranges = _critical_episodes(
        stress, config.critical_stress_threshold
    )

    observations = _build_observations(
        config, stress, start_time_utc, duration_hours,
        anchor_mode, rain_driver_label, rng
    )

    planted_edges_schema = edges_to_schema(graph.edges, start_time_utc)

    ground_truth = GroundTruth(
        city_id=config.city_id,
        seed=seed,
        start_time_utc=start_time_utc,
        duration_hours=duration_hours,
        generator_family=generator_family,
        stress=stress,
        rain_input=rain_input,
        planted_edges=planted_edges_schema,
        decoy_pairs=list(graph.decoy_pairs),
        critical_episodes=episodes,
        city_critical_episodes=city_ranges,
    )

    return observations, ground_truth
