"""Ground-truth container for synthetic cities.

Lives in a separate module namespace (``backend.app.synth.ground_truth``) so that
the model packages can be statically verified to never import it. The generator
owns this object; the replay stream only ever sees observations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..schemas import Edge, SourceKind


@dataclass
class CriticalEpisode:
    node_id: str
    start_hour: int
    end_hour: int  # inclusive hour index relative to start_time_utc
    peak_stress: float


@dataclass
class GroundTruth:
    city_id: str
    seed: int
    start_time_utc: datetime
    duration_hours: int
    generator_family: str
    # latent stress series per node id, length duration_hours+1 (hour 0 = start_time)
    stress: dict[str, list[float]] = field(default_factory=dict)
    # per-node rain-driven exogenous input used (mm/h), same length
    rain_input: dict[str, list[float]] = field(default_factory=dict)
    planted_edges: list[Edge] = field(default_factory=list)
    decoy_pairs: list[tuple[str, str]] = field(default_factory=list)
    critical_episodes: list[CriticalEpisode] = field(default_factory=list)
    city_critical_episodes: list[tuple[int, int]] = field(
        default_factory=list,
    )

    def stress_at(self, node_id: str, hour: int) -> float:
        series = self.stress.get(node_id, [])
        if hour < 0 or hour >= len(series):
            raise IndexError(f"hour {hour} out of range for {node_id}")
        return series[hour]

    def is_critical_at(self, node_id: str, hour: int, threshold: float) -> bool:
        return self.stress_at(node_id, hour) >= threshold

    def episodes_for_node(self, node_id: str) -> list[CriticalEpisode]:
        return [e for e in self.critical_episodes if e.node_id == node_id]
