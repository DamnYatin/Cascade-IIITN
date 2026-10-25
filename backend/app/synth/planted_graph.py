"""Hidden planted dependency graph over ``(zone, system)`` nodes.

This module is GROUND TRUTH. Only the synthetic generator and the validation
suite may import it. Future model packages (replay/view/estimator/learner) must
never import anything from ``backend.app.synth``.

The graph implements the required planted structure:
  (a) a physical chain  rainfall -> drainage -> roads -> emergency_response -> hospital
  (b) at least one signed negative edge
  (c) at least one feedback loop
  (d) cross-zone propagation via zone neighbours
  (e) edges present only in certain time windows (drift testing)
  (f) decoy node pairs with spurious correlation but no planted edge
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..schemas import Edge, SystemSpec, Zone


REQUIRED_SYSTEMS = ("drainage", "roads", "emergency_response", "hospital")


@dataclass(frozen=True)
class PlantedEdge:
    u: str  # NodeId "zone:system"
    v: str  # NodeId "zone:system"
    lag_hours: float
    weight: float  # signed
    confidence: float
    active_start: Optional[datetime] = None  # None == always active
    active_end: Optional[datetime] = None
    edge_type: str = "planted"  # chain | negative | feedback | cross_zone | windowed


@dataclass
class PlantedGraph:
    edges: list[PlantedEdge] = field(default_factory=list)
    decoy_pairs: list[tuple[str, str]] = field(default_factory=list)

    def adjacency(self) -> dict[str, list[PlantedEdge]]:
        adj: dict[str, list[PlantedEdge]] = {}
        for e in self.edges:
            adj.setdefault(e.u, []).append(e)
        return adj

    def has_edge(self, u: str, v: str) -> bool:
        return any(e.u == u and e.v == v for e in self.edges)


def _system_id(systems, wanted: str) -> str:
    ids = {s.id for s in systems}
    if wanted not in ids:
        raise ValueError(f"planted graph requires system '{wanted}', got {sorted(ids)}")
    return wanted


def build_planted_graph(
    zones: list[Zone],
    systems: list[SystemSpec],
    start_time_utc: datetime,
    seed: int,
) -> PlantedGraph:
    import numpy as np

    rng = np.random.default_rng(seed)
    drainage = _system_id(systems, "drainage")
    roads = _system_id(systems, "roads")
    emergency = _system_id(systems, "emergency_response")
    hospital = _system_id(systems, "hospital")

    edges: list[PlantedEdge] = []

    zone_by_id = {z.id: z for z in zones}

    def add(u_zone, u_sys, v_zone, v_sys, lag, weight, etype="planted",
            start=None, end=None, confidence=0.9):
        edges.append(PlantedEdge(
            u=f"{u_zone}:{u_sys}",
            v=f"{v_zone}:{v_sys}",
            lag_hours=lag,
            weight=weight,
            confidence=confidence,
            active_start=start,
            active_end=end,
            edge_type=etype,
        ))

    # (a) Physical chain per zone: drainage -> roads -> emergency_response -> hospital.
    #     Rainfall is exogenous (drives drainage directly inside the generator).
    for z in zones:
        add(z.id, drainage, z.id, roads, lag=1.5, weight=0.6, etype="chain")
        add(z.id, roads, z.id, emergency, lag=2.0, weight=0.5, etype="chain")
        add(z.id, emergency, z.id, hospital, lag=2.5, weight=0.7, etype="chain")

    # (b) Signed negative edge: incident-clearance by emergency_response relieves
    #     road congestion (negative weight) -- mirrors (c) to form a feedback loop.
    # (c) Feedback loop: roads <-> emergency_response.
    for z in zones:
        add(z.id, roads, z.id, emergency, lag=2.0, weight=0.5, etype="chain")  # congestion delays response
        add(z.id, emergency, z.id, roads, lag=1.0, weight=-0.4, etype="negative")  # clearance relieves congestion

    # (d) Cross-zone propagation via neighbours.
    for z in zones:
        for n_id in z.neighbours:
            n = zone_by_id[n_id]
            # road congestion spills into neighbouring zones
            add(z.id, roads, n.id, roads, lag=2.0, weight=0.25, etype="cross_zone")
            # drainage loading spills downstream into neighbours
            add(z.id, drainage, n.id, drainage, lag=3.0, weight=0.2, etype="cross_zone")

    # (e) Time-windowed edge: an extra drainage->roads coupling active only inside
    #     a monsoon-looking window (first 40% of the horizon). Enables drift tests.
    horizon_hint = 720  # 30 days default; actual horizon set by generator
    window_end = start_time_utc + timedelta(hours=int(horizon_hint * 0.4))
    for z in zones[: max(1, len(zones) // 2)]:
        add(z.id, drainage, z.id, roads, lag=1.0, weight=0.35,
            start=start_time_utc, end=window_end, etype="windowed", confidence=0.6)

    decoy_pairs: list[tuple[str, str]] = []
    # (f) Decoy pairs: two drainage nodes driven by the same rain but NOT neighbours,
    #     so no planted edge connects them -- a learner may infer a spurious edge.
    zone_ids = [z.id for z in zones]
    for i in range(len(zone_ids)):
        for j in range(i + 1, len(zone_ids)):
            zi, zj = zone_ids[i], zone_ids[j]
            zi_obj = next(z for z in zones if z.id == zi)
            zj_obj = next(z for z in zones if z.id == zj)
            if zj_obj.id in zi_obj.neighbours:
                continue  # neighbours already have a real cross-zone edge
            decoy_pairs.append((f"{zi}:{drainage}", f"{zj}:{drainage}"))
            if len(decoy_pairs) >= 3:
                break
        if len(decoy_pairs) >= 3:
            break

    return PlantedGraph(edges=edges, decoy_pairs=decoy_pairs)


def edges_to_schema(edges: list[PlantedEdge], last_updated: datetime) -> list[Edge]:
    """Convert planted edges to the public Edge schema (for test inspection only)."""
    out = []
    for e in edges:
        out.append(Edge(
            u=e.u, v=e.v, lag_hours=e.lag_hours, weight=e.weight,
            confidence=e.confidence, last_updated=last_updated,
        ))
    return out
