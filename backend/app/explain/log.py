"""Bounded, deterministic risk-change log recording causal explanation records.

Logs transitions whenever:
  - Risk state changes (e.g. WATCH -> HIGH_RISK or HIGH_RISK -> CRITICAL).
  - Or P(cascade-critical within 72h) moves by more than min_delta_p (default 0.05).
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Deque, List, Optional
from backend.app.explain.records import ExplanationRecord


class RiskChangeLog:
    """Bounded, deterministic FIFO ring buffer of ExplanationRecord entries."""

    def __init__(self, max_entries: int = 200, min_delta_p: float = 0.05):
        self.max_entries = max_entries
        self.min_delta_p = min_delta_p
        self._buffer: Deque[ExplanationRecord] = deque(maxlen=max_entries)

    def should_record(
        self,
        risk_from: str,
        risk_to: str,
        p_from: float,
        p_to: float,
    ) -> bool:
        """Evaluate whether transition warrants a new ExplanationRecord."""
        if risk_from != risk_to:
            return True
        if abs(p_to - p_from) >= self.min_delta_p:
            return True
        return False

    def append(self, record: ExplanationRecord) -> None:
        """Append an explanation record to the bounded log."""
        self._buffer.append(record)

    def get_changes(
        self,
        subject: Optional[str] = None,
        subject_kind: Optional[str] = None,
        limit: int = 50,
    ) -> List[ExplanationRecord]:
        """Retrieve recent changes sorted descending by timestamp."""
        items = list(self._buffer)
        if subject is not None:
            items = [it for it in items if it.subject == subject]
        if subject_kind is not None:
            items = [it for it in items if it.subject_kind == subject_kind]

        # Reverse to return most recent first
        items.reverse()
        return items[:limit]

    def __len__(self) -> int:
        return len(self._buffer)
