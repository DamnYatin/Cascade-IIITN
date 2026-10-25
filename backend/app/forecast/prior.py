"""Coarse population domain prior for network edges.

Stores typical strengths and lags of edge types (e.g. river_embankment -> transport)
fitted across independent runs, serving as a weak starting prior for DependencyLearner.
"""
from __future__ import annotations

from typing import Dict, Tuple

# Edge type (system_u, system_v, spatial_relation) -> (lag_hours, weight, confidence)
POPULATION_PRIOR_EDGES: Dict[Tuple[str, str, str], Tuple[float, float, float]] = {
    ("river_embankment", "transport", "same_zone"): (2.0, 0.45, 0.60),
    ("transport", "emergency_response", "same_zone"): (2.5, 0.40, 0.60),
    ("emergency_response", "health", "same_zone"): (3.0, 0.50, 0.60),
    ("power", "health", "same_zone"): (1.0, 0.40, 0.55),
    ("river_embankment", "river_embankment", "adjacent"): (4.0, 0.30, 0.50),
    ("river_embankment", "river_embankment", "upstream_river"): (4.0, 0.50, 0.70),
}


def get_population_prior_edge(
    sys_u: str,
    sys_v: str,
    spatial_relation: str = "same_zone",
) -> Tuple[float, float, float]:
    """Return (lag_hours, weight, confidence) for an edge type, or default (1.0, 0.1, 0.3)."""
    return POPULATION_PRIOR_EDGES.get((sys_u, sys_v, spatial_relation), (1.0, 0.10, 0.30))
