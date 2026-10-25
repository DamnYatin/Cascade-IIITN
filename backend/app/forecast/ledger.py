"""Evidence ledger: bounded ring buffer tracking observations that moved node states.

API:
  - record_evidence(...)
  - evidence_for(node, t)
  - evidence_ids_for_prediction(node, issued_at)
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, List, Optional


@dataclass(frozen=True)
class EvidenceItem:
    obs_id: str
    source: str
    node: str
    event_time: datetime
    arrival_time: datetime
    trust: float
    weight: float
    gated: bool
    stress_value: float
    normalization: str = "capacity"
    quality_flags: List[str] = field(default_factory=list)


class EvidenceLedger:
    """Bounded, deterministic ledger tracking observations affecting node estimates."""

    def __init__(self, max_hours: float = 48.0, max_items_per_node: int = 500):
        self.max_hours = max_hours
        self.max_items_per_node = max_items_per_node
        # Map node -> deque of EvidenceItem sorted by event_time
        self._buffers: Dict[str, Deque[EvidenceItem]] = {}

    def record_evidence(self, item: EvidenceItem) -> None:
        """Record an evidence item for a node into its bounded buffer."""
        node = item.node
        if node not in self._buffers:
            self._buffers[node] = deque(maxlen=self.max_items_per_node)
        self._buffers[node].append(item)

    def prune(self, current_time: datetime) -> None:
        """Prune items older than max_hours before current_time."""
        cutoff = current_time - timedelta(hours=self.max_hours)
        for node, buf in self._buffers.items():
            while buf and buf[0].event_time < cutoff:
                buf.popleft()

    def evidence_for(
        self,
        node: str,
        t: datetime,
        window_hours: float = 6.0,
    ) -> List[EvidenceItem]:
        """Return all evidence items for node within [t - window_hours, t]."""
        buf = self._buffers.get(node)
        if not buf:
            return []
        start = t - timedelta(hours=window_hours)
        return [item for item in buf if start <= item.event_time <= t]

    def evidence_ids_for_prediction(
        self,
        node: str,
        issued_at: datetime,
        window_hours: float = 24.0,
        max_ids: int = 10,
    ) -> List[str]:
        """Return distinct observation IDs that supported the prediction at issued_at."""
        buf = self._buffers.get(node)
        if not buf:
            return []
        start = issued_at - timedelta(hours=window_hours)
        # Select ungated items within window, ordered from most recent backwards
        candidates = [item for item in buf if start <= item.event_time <= issued_at and not item.gated]
        # Sort descending by event_time, then by weight
        candidates.sort(key=lambda x: (x.event_time, x.weight), reverse=True)

        seen = set()
        result: List[str] = []
        for c in candidates:
            if c.obs_id not in seen:
                seen.add(c.obs_id)
                result.append(c.obs_id)
                if len(result) >= max_ids:
                    break
        return result
