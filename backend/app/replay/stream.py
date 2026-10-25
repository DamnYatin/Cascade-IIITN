"""Leakage-proof replay stream.

``ReplayStream.release_until(t)`` returns only observations whose
``arrival_time <= t``, sorted by arrival time, and never returns an observation
twice (it advances an internal cursor).

``StreamView`` is the *only* object future model code may receive. It exposes
the released observations and the current clock time and nothing else. Because
it releases observations only up to ``clock.now``, it is impossible (by
design, not convention) for the view to return data whose ``arrival_time`` is
in the future relative to the clock.

Ground truth (``backend.app.synth``) is never referenced here, which keeps the
model packages structurally isolated from leakage.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, List

from ..schemas import Observation


class ReplayStream:
    def __init__(self, observations: Iterable[Observation]):
        # Stable, deterministic release order: by arrival_time, then event_time,
        # then obs_id. Sorting once here keeps release_until O(released).
        self._obs: List[Observation] = sorted(
            observations, key=lambda o: (o.arrival_time, o.event_time, o.obs_id)
        )
        self._cursor = 0
        self._released_count = 0

    def release_until(self, t: datetime) -> List[Observation]:
        """Return observations with ``arrival_time <= t`` not yet released.

        Results are sorted by arrival_time. An observation is released exactly
        once across the lifetime of the stream.
        """
        if t.tzinfo is None:
            raise ValueError("t must be timezone-aware (UTC)")
        t = t.astimezone(timezone.utc)
        released: List[Observation] = []
        while (
            self._cursor < len(self._obs)
            and self._obs[self._cursor].arrival_time <= t
        ):
            released.append(self._obs[self._cursor])
            self._cursor += 1
        self._released_count += len(released)
        return released

    def released_so_far(self) -> int:
        return self._released_count

    def total(self) -> int:
        return len(self._obs)

    def reset(self) -> None:
        self._cursor = 0
        self._released_count = 0

    @property
    def view(self) -> StreamView:
        start_t = self._obs[0].arrival_time if self._obs else datetime.now(timezone.utc)
        return StreamView(self, start_t)


class StreamView:
    """Read-only view handed to the model.

    The model can only call :meth:`released` (bounded by the clock) and read
    :attr:`clock_time`. It cannot reach the underlying un-released observations
    or the ground truth.
    """

    def __init__(self, stream: ReplayStream, clock_time: datetime):
        if clock_time.tzinfo is None:
            raise ValueError("clock_time must be timezone-aware (UTC)")
        self._stream = stream
        self._clock_time = clock_time.astimezone(timezone.utc)

    @property
    def clock_time(self) -> datetime:
        return self._clock_time

    def set_clock_time(self, clock_time: datetime) -> None:
        if clock_time.tzinfo is None:
            raise ValueError("clock_time must be timezone-aware (UTC)")
        self._clock_time = clock_time.astimezone(timezone.utc)

    def released(self) -> List[Observation]:
        """Observations released up to the current clock time (arrival_time <= clock)."""
        return self._stream.release_until(self._clock_time)

    def snapshot(self) -> List[Observation]:
        """Return a copy of the currently released observations (no future data)."""
        return list(self.released())
