"""Hidden planted dependency graph over (zone, system) nodes.

This module owns GROUND TRUTH. Only the synthetic generator and validation tests
may import it. Replay views, estimators, and learners must NEVER import from
backend.app.synth.

Implements the Assam physical cascade:
  (a) Upstream Nagaland surge -> Upper Assam floodplains (Dikhow, Disang, Dhansiri)
      with realistic lag of ~1.5 - 3.5 hours (report: ~90 min hills to plains).
  (b) Intra-zone physical chain: river_embankment -> transport -> emergency_response -> health.
  (c) Feedback loops (emergency clearance relieves transport; transport delays relief).
  (d) Cross-zone spill-over between neighbours.
  (e) Circularity mitigation (Playbook Sec 8): Planted graph differs from the domain
      prior by at least one removed prior edge (e.g. hospital generator buffering)
      and at least one surprising planted edge (e.g. power grid tripping drainage pumps).
  (f) Decoy pairs: Spurious correlation across non-adjacent zones with no planted edge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..schemas import Edge, SystemSpec, Zone


@dataclass(frozen=True)
class PlantedEdge:
    u: str  # NodeId "zone:system"
    v: str  # NodeId "zone:system"
    lag_hours: float
    weight: float  # signed
    confidence: float
    active_start: Optional[datetime] = None  # None == always active
    active_end: Optional[datetime] = None
    edge_type: str = "planted"  # chain | negative | feedback | cross_zone | river_link | windowed | surprising


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


def _match_system(systems: list[SystemSpec], candidates: list[str]) -> str | None:
    sys_ids = {s.id for s in systems}
    for c in candidates:
        if c in sys_ids:
            return c
    return None


def build_planted_graph(
    zones: list[Zone],
    systems: list[SystemSpec],
    start_time_utc: datetime,
    seed: int,
) -> PlantedGraph:
    import numpy as np

    rng = np.random.default_rng(seed)
    edges: list[PlantedEdge] = []
    zone_by_id = {z.id: z for z in zones}

    river_sys = _match_system(systems, ["river_embankment", "drainage"])
    transport_sys = _match_system(systems, ["transport", "roads"])
    emergency_sys = _match_system(systems, ["emergency_response", "emergency"])
    health_sys = _match_system(systems, ["health", "hospital"])
    power_sys = _match_system(systems, ["power", "electricity"])
    comms_sys = _match_system(systems, ["comms", "telecom"])

    def add(u_zone: str, u_s: str, v_zone: str, v_s: str, lag: float, weight: float,
            etype: str = "planted", start: Optional[datetime] = None, end: Optional[datetime] = None,
            confidence: float = 0.9):
        # Only add edge if both nodes are valid for the respective zones
        uz_obj = zone_by_id.get(u_zone)
        vz_obj = zone_by_id.get(v_zone)
        if uz_obj and vz_obj:
            if uz_obj.systems and u_s not in uz_obj.systems:
                return
            if vz_obj.systems and v_s not in vz_obj.systems:
                return
            edges.append(
                PlantedEdge(
                    u=f"{u_zone}:{u_s}",
                    v=f"{v_zone}:{v_s}",
                    lag_hours=lag,
                    weight=weight,
                    confidence=confidence,
                    active_start=start,
                    active_end=end,
                    edge_type=etype,
                )
            )

    # 1. Documented Hydrological River Links (Nagaland Hills -> Upper Assam Floodplains)
    for z in zones:
        for rlink in getattr(z, "river_links", []):
            target = rlink.get("target")
            if target and target in zone_by_id and river_sys:
                # Disang surge reaches Charaideo within ~1.5 h; Dikhow reaches Sivasagar ~2.5 h
                lag = 1.5 if "charaideo" in target else 2.5
                add(z.id, river_sys, target, river_sys, lag=lag, weight=0.85, etype="river_link")

    # 2. Intra-zone physical cascade
    for z in zones:
        zid = z.id
        if river_sys and transport_sys:
            # Embankment breach/overtopping inundates roads & railway tracks
            add(zid, river_sys, zid, transport_sys, lag=1.5, weight=0.65, etype="chain")
        if transport_sys and emergency_sys:
            # Submerged roads delay NDRF / emergency deployment
            add(zid, transport_sys, zid, emergency_sys, lag=2.0, weight=0.55, etype="chain")
        if emergency_sys and health_sys:
            # Emergency rescue saturation strains medical access
            add(zid, emergency_sys, zid, health_sys, lag=2.5, weight=0.60, etype="chain")
        if power_sys and comms_sys:
            # Substation waterlogging causes telecom BTS battery depletion
            add(zid, power_sys, zid, comms_sys, lag=1.0, weight=0.70, etype="chain")

        # Feedback loop: emergency road clearance relieves transport congestion (negative weight)
        if emergency_sys and transport_sys:
            add(zid, emergency_sys, zid, transport_sys, lag=1.0, weight=-0.40, etype="negative")

    # 3. Cross-zone propagation across neighbours
    for z in zones:
        for n_id in z.neighbours:
            if transport_sys:
                # Road blockages cascade across district borders
                add(z.id, transport_sys, n_id, transport_sys, lag=2.0, weight=0.25, etype="cross_zone")
            if river_sys:
                # Floodwaters spill into adjacent downstream districts
                add(z.id, river_sys, n_id, river_sys, lag=3.0, weight=0.30, etype="cross_zone")

    # 4. Time-windowed edge: extra coupling active inside early surge window (enables drift testing)
    horizon_hint = 720
    window_end = start_time_utc + timedelta(hours=int(horizon_hint * 0.4))
    for z in zones[: max(1, len(zones) // 2)]:
        if river_sys and transport_sys:
            add(z.id, river_sys, z.id, transport_sys, lag=1.0, weight=0.35,
                start=start_time_utc, end=window_end, etype="windowed", confidence=0.6)

    # 5. Circularity Mitigations (Playbook Sec 8):

    # (a) Extra SURPRISING edge absent from domain prior:
    #     Substation failure directly disables electric drainage pumping stations at embankments
    if power_sys and river_sys:
        for z in zones[:3]:
            add(z.id, power_sys, z.id, river_sys, lag=0.5, weight=0.45, etype="surprising")

    # (b) Decoy pairs: Two river nodes driven by monsoon rain but not connected by any edge
    decoy_pairs: list[tuple[str, str]] = []
    zone_ids = [z.id for z in zones]
    for i in range(len(zone_ids)):
        for j in range(i + 1, len(zone_ids)):
            zi, zj = zone_ids[i], zone_ids[j]
            zi_obj = zone_by_id[zi]
            zj_obj = zone_by_id[zj]
            if zj_obj.id in zi_obj.neighbours:
                continue
            if river_sys:
                decoy_pairs.append((f"{zi}:{river_sys}", f"{zj}:{river_sys}"))
                if len(decoy_pairs) >= 3:
                    break
        if len(decoy_pairs) >= 3:
            break

    return PlantedGraph(edges=edges, decoy_pairs=decoy_pairs)


def edges_to_schema(edges: list[PlantedEdge], last_updated: datetime) -> list[Edge]:
    """Convert planted edges to public Edge schema (for test validation only)."""
    return [
        Edge(
            u=e.u,
            v=e.v,
            lag_hours=e.lag_hours,
            weight=e.weight,
            confidence=e.confidence,
            last_updated=last_updated,
        )
        for e in edges
    ]
