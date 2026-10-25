"""Replay clock: advances in simulated time, one hour per step.

Design notes for leakage isolation:
* All timestamps are timezone-aware UTC datetimes. Naive datetimes are rejected.
* The clock only moves forward: ``seek_forward`` rejects any target earlier than
  the current time. There is no rewind, which prevents a model from "re-reading"
  the past with future knowledge.
* ``speed`` is a multiplier on simulated-hours-per-advance; it does not affect
  determinism of the underlying observation stream.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


class ReplayClock:
    def __init__(self, start_time_utc: datetime):
        if start_time_utc.tzinfo is None:
            raise ValueError("start_time_utc must be timezone-aware (UTC)")
        self._start = start_time_utc.astimezone(timezone.utc)
        self._current = self._start
        self._paused = False
        self.speed: float = 1.0

    @property
    def start_time(self) -> datetime:
        return self._start

    @property
    def now(self) -> datetime:
        return self._current

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def advance(self, hours: float) -> datetime:
        """Advance simulated time by ``hours`` (scaled by speed). No-op if paused."""
        if self._paused:
            return self._current
        if hours < 0:
            raise ValueError("advance requires non-negative hours")
        self._current = self._current + timedelta(hours=hours * self.speed)
        return self._current

    def seek_forward(self, to_time: datetime) -> datetime:
        """Seek forward only. Rejects targets earlier than the current time."""
        if to_time.tzinfo is None:
            raise ValueError("to_time must be timezone-aware (UTC)")
        to_time = to_time.astimezone(timezone.utc)
        if to_time < self._current:
            raise ValueError(
                f"seek-forward only: {to_time} is before current {self._current}"
            )
        self._current = to_time
        return self._current

    def reset(self) -> None:
        self._current = self._start
        self._paused = False
