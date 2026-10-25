"""Seeded fault injector applied to observations before release.

Faults are toggleable at runtime (add/remove ``FaultSpec`` objects). Each fault
either tags the affected observations with a :class:`~backend.app.schemas.QualityFlag`
or is recorded in the injector's ``fault_log`` -- which is kept separate from the
stream and must never be exposed to the model (the model only ever sees
:class:`~backend.app.replay.stream.StreamView`).

All random decisions use an isolated ``numpy.random.Generator`` created from an
explicit seed; the global RNG is never touched.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np

from ..schemas import Observation, QualityFlag, SourceKind


@dataclass
class FaultSpec:
    kind: str  # dropout | stuck_at | spike | feed_delay | contradictory_duplicate | citizen_spam | zone_blackout
    target_zone: Optional[str] = None
    target_system: Optional[str] = None
    start_hour: int = 0            # hour offset from city start (inclusive)
    end_hour: int = 10**9          # hour offset (inclusive)
    probability: float = 0.5       # for probabilistic faults
    delay_hours: float = 2.0       # for feed_delay
    stuck_value: float = 0.0       # for stuck_at
    spike_magnitude: float = 10.0  # for spike
    burst_count: int = 20          # for citizen_spam

    def matches(self, obs: Observation, hour_offset: int) -> bool:
        if not (self.start_hour <= hour_offset <= self.end_hour):
            return False
        if self.target_zone is not None and obs.zone != self.target_zone:
            return False
        if self.target_system is not None and obs.system != self.target_system:
            return False
        return True


@dataclass
class FaultLogEntry:
    kind: str
    target_zone: Optional[str]
    target_system: Optional[str]
    hour_offset_start: int
    hour_offset_end: int
    affected_count: int
    note: str = ""


class FaultInjector:
    def __init__(self, seed: int):
        self._rng = np.random.default_rng(seed)
        self.faults: list[FaultSpec] = []
        self.fault_log: list[FaultLogEntry] = []

    def add_fault(self, spec: FaultSpec) -> None:
        self.faults.append(spec)

    def remove_fault(self, kind: str) -> int:
        before = len(self.faults)
        self.faults = [f for f in self.faults if f.kind != kind]
        return before - len(self.faults)

    def clear(self) -> None:
        self.faults.clear()
        self.fault_log.clear()

    def _hour_offset(self, obs: Observation, start_time_utc: datetime) -> int:
        return int((obs.event_time - start_time_utc).total_seconds() // 3600)

    def apply(
        self, observations: list[Observation], start_time_utc: datetime
    ) -> list[Observation]:
        """Apply all active faults and return the modified observation list.

        The fault log is appended to internally (``self.fault_log``) but is not
        returned here -- callers that are not the model (e.g. the CLI) may read
        ``injector.fault_log`` directly.
        """
        if start_time_utc.tzinfo is None:
            raise ValueError("start_time_utc must be timezone-aware (UTC)")
        start_time_utc = start_time_utc.astimezone(timezone.utc)

        out: list[Observation] = []

        for obs in observations:
            h = self._hour_offset(obs, start_time_utc)
            dropped = False

            for fault in self.faults:
                if not fault.matches(obs, h):
                    continue

                if fault.kind == "dropout":
                    if self._rng.random() < fault.probability:
                        dropped = True
                        self.fault_log.append(
                            FaultLogEntry(
                                kind="dropout",
                                target_zone=fault.target_zone,
                                target_system=fault.target_system,
                                hour_offset_start=fault.start_hour,
                                hour_offset_end=fault.end_hour,
                                affected_count=1,
                                note=f"dropped observation {obs.obs_id}",
                            )
                        )
                        break

                elif fault.kind == "stuck_at":
                    obs = Observation(
                        **{**obs.model_dump(), "value": float(fault.stuck_value),
                           "quality_flags": list(obs.quality_flags)
                           + [QualityFlag.STUCK_AT]}
                    )
                    self.fault_log.append(
                        FaultLogEntry(
                            kind="stuck_at",
                            target_zone=fault.target_zone,
                            target_system=fault.target_system,
                            hour_offset_start=fault.start_hour,
                            hour_offset_end=fault.end_hour,
                            affected_count=1,
                            note=f"stuck at {fault.stuck_value} for {obs.obs_id}",
                        )
                    )

                elif fault.kind == "spike":
                    if self._rng.random() < fault.probability:
                        sign = 1.0 if self._rng.random() < 0.5 else -1.0
                        obs = Observation(
                            **{**obs.model_dump(),
                               "value": float(obs.value) + sign * float(fault.spike_magnitude),
                               "quality_flags": list(obs.quality_flags)
                               + [QualityFlag.SPIKE]}
                        )
                        self.fault_log.append(
                            FaultLogEntry(
                                kind="spike",
                                target_zone=fault.target_zone,
                                target_system=fault.target_system,
                                hour_offset_start=fault.start_hour,
                                hour_offset_end=fault.end_hour,
                                affected_count=1,
                                note=f"spike on {obs.obs_id}",
                            )
                        )

                elif fault.kind == "feed_delay":
                    obs = Observation(
                        **{**obs.model_dump(),
                           "arrival_time": obs.arrival_time
                           + timedelta(hours=float(fault.delay_hours)),
                           "quality_flags": list(obs.quality_flags)
                           + [QualityFlag.FEED_DELAY]}
                    )
                    self.fault_log.append(
                        FaultLogEntry(
                            kind="feed_delay",
                            target_zone=fault.target_zone,
                            target_system=fault.target_system,
                            hour_offset_start=fault.start_hour,
                            hour_offset_end=fault.end_hour,
                            affected_count=1,
                            note=f"delayed {fault.delay_hours}h for {obs.obs_id}",
                        )
                    )

                elif fault.kind == "contradictory_duplicate":
                    if self._rng.random() < fault.probability:
                        # Duplicate with a contradictory (flipped-sign) value.
                        dup = Observation(
                            **{**obs.model_dump(),
                               "value": float(-obs.value),
                               "quality_flags": list(obs.quality_flags)
                               + [QualityFlag.CONTRADICTORY_DUPLICATE]}
                        )
                        obs = Observation(
                            **{**obs.model_dump(),
                               "quality_flags": list(obs.quality_flags)
                               + [QualityFlag.CONTRADICTORY_DUPLICATE]}
                        )
                        self.fault_log.append(
                            FaultLogEntry(
                                kind="contradictory_duplicate",
                                target_zone=fault.target_zone,
                                target_system=fault.target_system,
                                hour_offset_start=fault.start_hour,
                                hour_offset_end=fault.end_hour,
                                affected_count=2,
                                note=f"contradictory duplicate for {obs.obs_id}",
                            )
                        )
                        out.append(dup)

                elif fault.kind == "zone_blackout":
                    dropped = True
                    self.fault_log.append(
                        FaultLogEntry(
                            kind="zone_blackout",
                            target_zone=fault.target_zone,
                            target_system=fault.target_system,
                            hour_offset_start=fault.start_hour,
                            hour_offset_end=fault.end_hour,
                            affected_count=1,
                            note=f"blacked out zone {fault.target_zone} at {obs.obs_id}",
                        )
                    )
                    break

            if not dropped:
                out.append(obs)

        # citizen_spam: inject a burst of fake citizen reports for the target zone.
        for fault in self.faults:
            if fault.kind != "citizen_spam":
                continue
            if fault.target_zone is None:
                continue
            span = max(1, fault.end_hour - fault.start_hour + 1)
            per_hour = max(1, fault.burst_count // span)
            for h in range(fault.start_hour, fault.end_hour + 1):
                if self._rng.random() > fault.probability:
                    continue
                for _ in range(per_hour):
                    event_time = start_time_utc + timedelta(hours=h)
                    obs = Observation(
                        source="citizen_report",
                        source_kind=SourceKind.SIMULATED,
                        zone=fault.target_zone,
                        system="roads",
                        value=float(self._rng.uniform(0.0, 100.0)),
                        event_time=event_time,
                        arrival_time=event_time + timedelta(hours=float(self._rng.uniform(0, 2))),
                        quality_flags=[QualityFlag.CITIZEN_REPORT, QualityFlag.LOW_CONFIDENCE],
                        node_id=f"{fault.target_zone}:roads",
                    )
                    out.append(obs)
                    self.fault_log.append(
                        FaultLogEntry(
                            kind="citizen_spam",
                            target_zone=fault.target_zone,
                            target_system=fault.target_system,
                            hour_offset_start=fault.start_hour,
                            hour_offset_end=fault.end_hour,
                            affected_count=1,
                            note=f"spam report in {fault.target_zone} hour {h}",
                        )
                    )

        out.sort(key=lambda o: (o.arrival_time, o.event_time, o.obs_id))
        return out
