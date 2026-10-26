"""Evidence Receipts: Auditable provenance chains for links and causal drivers.

Extracts:
  - Observation IDs strictly from EvidenceLedger with arrival_time <= issued_at.
  - Sensor sources, reliability trust scores, and quality flags (gated, flatline, late).
  - EdgeBook history: first_seen timestamp, weight, confidence, recursive updates, and drift events.
  - Transparent provenance disclosures distinguishing real meteorological inputs from simulated infrastructure.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from backend.app.explain.records import EvidenceReceipt
from backend.app.forecast.ledger import EvidenceLedger


def build_evidence_receipt(
    node: str,
    issued_at: datetime,
    ledger: Optional[EvidenceLedger] = None,
    parent_node: Optional[str] = None,
    edge_book: Optional[Any] = None,
    window_hours: float = 24.0,
    max_observations: int = 10,
    paired_removal_effect: Optional[Dict[str, Any]] = None,
) -> EvidenceReceipt:
    """Build an audit receipt proving observations and edge history behind a node or link."""
    # Determine which node to query for observations (parent if link, else node)
    target_obs_node = parent_node if parent_node is not None else node

    obs_ids: List[str] = []
    sources: List[str] = []
    source_kinds: List[str] = []
    trusts: List[float] = []
    quality_flags: List[str] = []
    arrival_times: List[str] = []

    if ledger is not None:
        raw_items = ledger.evidence_for(target_obs_node, t=issued_at, window_hours=window_hours)
        # Filter strictly arrival_time <= issued_at
        valid_items = [
            it for it in raw_items
            if it.arrival_time <= issued_at
        ]
        # Sort by arrival_time descending (most recent first)
        valid_items.sort(key=lambda x: x.arrival_time, reverse=True)

        for item in valid_items[:max_observations]:
            obs_ids.append(item.obs_id)
            sources.append(item.source)
            trusts.append(round(float(item.trust), 4))
            flags = list(item.quality_flags)
            if item.gated:
                flags.append("gated")
            quality_flags.extend(flags)
            arrival_times.append(item.arrival_time.isoformat())

            # Classify source kind
            s_lower = item.source.lower()
            if "open_meteo" in s_lower or "imd" in s_lower or "satellite" in s_lower or "rain" in s_lower or "soil" in s_lower:
                source_kinds.append("real")
            else:
                source_kinds.append("simulated")

    # EdgeBook metadata
    first_seen: Optional[str] = None
    edge_w: Optional[float] = None
    edge_conf: Optional[float] = None
    update_count: Optional[int] = None
    drift_events: List[Dict[str, Any]] = []

    if parent_node is not None and edge_book is not None:
        if hasattr(edge_book, "get_edge"):
            edge = edge_book.get_edge(parent_node, node)
            if edge is not None:
                edge_w = round(float(edge.weight), 4)
                edge_conf = round(float(edge.confidence), 4)
                if hasattr(edge, "first_seen_utc") and edge.first_seen_utc:
                    first_seen = edge.first_seen_utc.isoformat()
                if hasattr(edge, "update_count"):
                    update_count = int(edge.update_count)
                if hasattr(edge, "recent_drifts"):
                    drift_events = list(edge.recent_drifts)

    # Determine simulated parent status
    simulated_parent = False
    system_part = (parent_node or node).split(":")[-1]
    if system_part not in ("rain", "soil_moisture", "cwc_gauge"):
        simulated_parent = True

    provenance_note = (
        "Real meteorological observation input (Open-Meteo rainfall / satellite reanalysis)."
        if not simulated_parent
        else "Parent stream is a synthetic infrastructure simulation; estimates under the learned model."
    )

    return EvidenceReceipt(
        node=node,
        parent_node=parent_node,
        observation_ids=obs_ids,
        sources=sources,
        source_kinds=source_kinds,
        trusts=trusts,
        quality_flags=list(set(quality_flags)),
        arrival_times=arrival_times,
        edge_first_seen=first_seen,
        edge_weight=edge_w,
        edge_confidence=edge_conf,
        edge_update_count=update_count,
        drift_events=drift_events,
        paired_removal_effect=paired_removal_effect,
        simulated_parent_flag=simulated_parent,
        provenance_note=provenance_note,
    )
