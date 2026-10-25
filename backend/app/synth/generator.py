"""Synthetic city generator with a hidden planted dependency graph.

This module owns the ground truth: it builds a planted directed lagged graph
over ``(zone, system)`` nodes, simulates latent stress per node per hour,
detects CRITICAL episodes, and derives noisy observation streams from the
latent stress.

The ``GroundTruth`` object is produced here but is NEVER placed on the replay
stream -- only ``Observation`` objects are. Future model code must never import
from this package (see ``backend/app/replay/stream.py`` and the import-isolation
test).
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np

from ..schemas import (
    CityConfig,
    Observation,
    QualityFlag,
    StreamSpec,
)
from .ground_truth import CriticalEpisode, GroundTruth
from .planted_graph import build_planted_graph, edges_to_schema


# Per-system physical parameters used by both generator families.
_SYSTEM_PARAMS = {
    "drainage": {"bias": 0.02, "decay": 0.94, "rain_sensitivity": 0.6, "scale": 100.0},
    "roads": {"bias": 0.01, "decay": 0.90, "rain_sensitivity": 0.0, "scale": 100.0},
    "emergency_response": {
        "bias": 0.008,
        "decay": 0.92,
        "rain_sensitivity": 0.0,
        "scale": 60.0,
    },
    "hospital": {"bias": 0.005, "decay": 0.93, "rain_sensitivity": 0.0, "scale": 100.0},
    "power": {"bias": 0.006, "decay": 0.96, "rain_sensitivity": 0.0, "scale": 100.0},
    "comms": {"bias": 0.004, "decay": 0.95, "rain_sensitivity": 0.0, "scale": 100.0},
}


def _system_params(sys_id: str) -> dict:
    return _SYSTEM_PARAMS.get(
        sys_id, {"bias": 0.01, "decay": 0.9, "rain_sensitivity": 0.0, "scale": 100.0}
    )


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _parent_influence(edge, stress: dict[str, list[float]], t: int) -> float:
    """Stress contributed by parent node at the edge's lag, 0 if not yet valid."""
    lag = int(round(edge.lag_hours))
    src_t = t - lag
    if src_t < 0:
        return 0.0
    return stress[edge.u][src_t]


def _edge_active(edge, start_time_utc: datetime, t: int) -> bool:
    """A time-windowed edge only transmits inside [active_start, active_end]."""
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
    rain_by_hour: dict[int, float],
    duration_hours: int,
    family: str,
    rng: np.random.Generator,
) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    """Run the latent-stress simulation hour by hour.

    Returns ``(stress, rain_input)`` where each maps node id -> list of length
    ``duration_hours + 1`` (hour 0 is the initial state at ``start_time_utc``).
    """
    params = {s.id: _system_params(s.id) for s in config.systems}

    stress: dict[str, list[float]] = {n: [0.1] * (duration_hours + 1) for n in nodes}
    rain_input: dict[str, list[float]] = {n: [0.0] * (duration_hours + 1) for n in nodes}

    # parents[v] = list of planted edges pointing into v
    parents: dict[str, list] = {}
    for e in graph.edges:
        parents.setdefault(e.v, []).append(e)

    start_time_utc = config.start_time_utc

    for t in range(1, duration_hours + 1):
        rain_mm = rain_by_hour.get(t, 0.0)
        for n in nodes:
            zone, sysid = n.split(":")
            p = params[sysid]

            # Exogenous rain drives drainage nodes directly.
            rain_in = 0.0
            if sysid == "drainage":
                rain_in = rain_mm * p["rain_sensitivity"] * 0.02
            rain_input[n][t] = rain_in

            if family == "logistic_hazard":
                # Smooth, differentiable hazard: sigmoid of bias + rain +
                # weighted lagged parent stresses.
                z = p["bias"] + rain_in
                for e in parents.get(n, []):
                    if not _edge_active(e, start_time_utc, t):
                        continue
                    z += e.weight * _parent_influence(e, stress, t)
                hazard = _sigmoid(z)
                new_s = p["decay"] * stress[n][t - 1] + (1.0 - p["decay"]) * hazard
            else:
                # threshold_nonlinear: piecewise response -- a parent only
                # transmits when its own stress exceeds 0.5, combined with tanh.
                z = p["bias"] + rain_in
                for e in parents.get(n, []):
                    if not _edge_active(e, start_time_utc, t):
                        continue
                    su = _parent_influence(e, stress, t)
                    if su > 0.5:
                        z += e.weight * (su - 0.5)
                hazard = math.tanh(z) * 0.5
                new_s = p["decay"] * stress[n][t - 1] + hazard

            # Process noise (isolated RNG -- never global).
            new_s += rng.normal(0.0, 0.02)
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
            episodes.append(
                CriticalEpisode(node_id, start_h, len(series) - 1, peak)
            )

    # Merge city-wide critical hours into contiguous ranges.
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
    generator_family: str,
    rng: np.random.Generator,
) -> list[Observation]:
    """Derive noisy observations from latent stress per StreamSpec."""
    observations: list[Observation] = []

    def hour_of(t: datetime) -> int:
        return int((t - start_time_utc).total_seconds() // 3600)

    obs_counter = 0

    for stream in config.streams:
        sys_scale = _system_params(stream.system)["scale"]

        k = 0
        while True:
            event_time = start_time_utc + timedelta(hours=k * stream.cadence_hours)
            h = hour_of(event_time)
            if h > duration_hours:
                break

            for zone in config.zones:
                node_id = f"{zone.id}:{stream.system}"
                base_value = stress.get(node_id, [0.1] * (duration_hours + 1))[h]
                value = base_value * sys_scale

                # Stream-level noise.
                value += rng.normal(0.0, stream.noise_level * sys_scale * 0.1)
                value = max(0.0, value)

                flags: list[QualityFlag] = []
                is_citizen = stream.source == "citizen_report"

                if is_citizen:
                    flags.append(QualityFlag.CITIZEN_REPORT)
                    frr = getattr(stream, "false_report_rate", 0.0)
                    if rng.random() < frr:
                        # False report: value unrelated to latent stress.
                        value = float(rng.uniform(0.0, sys_scale))
                        flags.append(QualityFlag.LOW_CONFIDENCE)

                # Random transport delay so arrival_time > event_time and the
                # arrival order can differ from the event order.
                delay_hours = float(
                    stream.typical_delay_hours
                    + rng.uniform(
                        0.0, max(stream.typical_delay_hours, 0.5) * 0.5
                    )
                )
                arrival_time = event_time + timedelta(hours=delay_hours)

                observations.append(
                    Observation(
                        obs_id=f"obs:{obs_counter}",
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

    # Deterministic release order regardless of generation order.
    observations.sort(key=lambda o: (o.arrival_time, o.event_time, o.obs_id))
    return observations


def generate_city(
    config: CityConfig,
    seed: int,
    duration_hours: int,
    rain_series: Optional[dict[int, float]] = None,
    generator_family: str = "logistic_hazard",
) -> tuple[list[Observation], GroundTruth]:
    """Generate a deterministic synthetic city stream and its ground truth.

    Parameters
    ----------
    config:
        Frozen city configuration (zones, systems, streams, thresholds).
    seed:
        Master seed. Every random draw uses ``np.random.default_rng(seed)``
        derived from this, so the same seed yields byte-identical output.
    duration_hours:
        Number of simulated hours (step = 1 hour).
    rain_series:
        Exogenous rainfall mm per hour offset from ``start_time_utc``. If None,
        a synthetic storm series is generated.
    generator_family:
        ``"logistic_hazard"`` or ``"threshold_nonlinear"`` -- different
        functional forms so a later learner cannot simply match the generator.

    Returns
    -------
    (observations, ground_truth)
        ``observations`` is what goes on the replay stream. ``ground_truth``
        contains the hidden planted graph, latent stress, and CRITICAL episodes
        and must never be released to the model.
    """
    if generator_family not in ("logistic_hazard", "threshold_nonlinear"):
        raise ValueError(
            f"unknown generator_family {generator_family!r}; "
            "use 'logistic_hazard' or 'threshold_nonlinear'"
        )

    rng = np.random.default_rng(seed)
    start_time_utc = config.start_time_utc

    # Exogenous rainfall: synthetic storms if none supplied.
    if rain_series is None:
        rain_series = {}
        t = 0
        while t <= duration_hours:
            if rng.random() < 1.0 / 24.0:  # ~1 storm start per day
                storm_dur = int(rng.integers(3, 9))
                intensity = float(rng.uniform(5.0, 40.0))
                for hh in range(storm_dur):
                    ht = t + hh
                    if ht <= duration_hours:
                        rain_series[ht] = rain_series.get(ht, 0.0) + intensity
            t += 1

    graph = build_planted_graph(config.zones, config.systems, start_time_utc, seed)

    nodes = [f"{z.id}:{s.id}" for z in config.zones for s in config.systems]

    stress, rain_input = _simulate_stress(
        config, graph, nodes, rain_series, duration_hours, generator_family, rng
    )

    episodes, city_ranges = _critical_episodes(
        stress, config.critical_stress_threshold
    )

    observations = _build_observations(
        config, stress, start_time_utc, duration_hours, generator_family, rng
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
