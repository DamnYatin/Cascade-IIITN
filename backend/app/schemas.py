"""Frozen Pydantic v2 schemas for the 72-Hour Warning Phase 1 backbone.

These contracts are intentionally small and complete: every later module
(estimator, learner, forecaster, UI) codes against them and nothing else.
Nothing in this module imports the synthetic ground-truth packages
(backend/app/synth/*), which keeps the model packages free of leakage.

Design notes:
* Every timestamp is a timezone-aware UTC datetime; naive datetimes are rejected.
* Observation carries both event_time (when it happened) and arrival_time
  (when the system receives it); arrival_time >= event_time is enforced.
* NodeId is exactly "zone_id:system_id" — zones and systems are never spliced.
* All models are frozen so a replay stream is deterministic and hashable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(value: datetime | None) -> datetime | None:
    """Reject naive datetimes everywhere; IST/UTC confusion is a classic leak."""
    if value is not None and value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware (UTC)")
    return value


class NodeId(str):
    """``zone_id:system_id`` — the canonical node key; never spliced across expiries."""

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler):
        from pydantic_core import core_schema

        def validate(v: Any) -> str:
            if not isinstance(v, str):
                raise TypeError("node id must be a string")
            if v.count(":") != 1:
                raise ValueError("node id must be exactly 'zone_id:system_id'")
            zone, system = v.split(":")
            if not zone or not system:
                raise ValueError("node id must be exactly 'zone_id:system_id'")
            return v

        return core_schema.no_info_plain_validator_function(validate)


class RiskState(str, Enum):
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    HIGH_RISK = "HIGH_RISK"
    CRITICAL = "CRITICAL"


class SourceKind(str, Enum):
    REAL = "real"
    SIMULATED = "simulated"
    DISAGGREGATED = "disaggregated"


class QualityFlag(str, Enum):
    DROPOUT = "dropout"
    STUCK_AT = "stuck_at"
    SPIKE = "spike"
    FEED_DELAY = "feed_delay"
    CONTRADICTORY_DUPLICATE = "contradictory_duplicate"
    CITIZEN_REPORT = "citizen_report"
    MISSING_ZONE_BLACKOUT = "missing_zone_blackout"
    LOW_CONFIDENCE = "low_confidence"
    REAL = "real"
    SIMULATED = "simulated"
    ANCHORED = "anchored"
    DISAGGREGATED = "disaggregated"


class Zone(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    centroid_lat: float = Field(ge=-90, le=90)
    centroid_lon: float = Field(ge=-180, le=180)
    neighbours: list[str] = Field(default_factory=list)
    systems: list[str] | None = Field(default=None, description="Optional system subset for this zone")
    jurisdiction: str | None = Field(default=None)
    role: str | None = Field(default=None)
    river_links: list[dict[str, Any]] = Field(default_factory=list)
    assets: dict[str, Any] | list[dict[str, Any]] = Field(default_factory=dict)


    @model_validator(mode="after")
    def _no_self_neighbour(self) -> "Zone":
        if self.id in self.neighbours:
            raise ValueError(f"zone {self.id} cannot list itself as a neighbour")
        return self


class SystemSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str  # e.g. drainage, roads, power, comms, hospital, emergency_response
    name: str | None = None
    capacity: float | None = Field(default=None, gt=0)
    critical_threshold: float | None = Field(default=None, gt=0)
    unit: str = "unitless"

    @model_validator(mode="after")
    def _has_limit(self) -> "SystemSpec":
        if self.capacity is None and self.critical_threshold is None:
            raise ValueError(f"system {self.id} needs capacity or critical_threshold")
        return self


class StreamSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str  # e.g. imd_rain, drainage_sensor, citizen_report
    system: str
    cadence_hours: float = Field(gt=0)
    typical_delay_hours: float = Field(ge=0)
    noise_level: float = Field(ge=0, le=1)
    source_kind: SourceKind = SourceKind.SIMULATED
    false_report_rate: float = Field(
        default=0.1,
        ge=0,
        le=1,
        description="For citizen_report sources: fraction of reports unrelated to truth.",
    )


class Edge(BaseModel):
    model_config = ConfigDict(frozen=True)

    u: NodeId
    v: NodeId
    lag_hours: float = Field(ge=0)
    weight: float  # signed: positive increases stress, negative relieves it
    confidence: float = Field(ge=0, le=1)
    last_updated: datetime = Field(default_factory=_utc_now)

    @field_validator("last_updated")
    @classmethod
    def _aware(cls, v):
        return _ensure_aware(v)


class CityConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    city_id: str
    zones: list[Zone]
    systems: list[SystemSpec]
    streams: list[StreamSpec]
    domain_prior_edges: list[Edge] = Field(
        default_factory=list,
        description="Weak prior only — explicitly NOT the ground truth.",
    )
    start_time_utc: datetime
    critical_stress_threshold: float = Field(default=0.8, ge=0, le=1)

    @field_validator("start_time_utc")
    @classmethod
    def _aware(cls, v):
        return _ensure_aware(v)

    @model_validator(mode="after")
    def _refs(self) -> "CityConfig":
        zone_ids = {z.id for z in self.zones}
        system_ids = {s.id for s in self.systems}
        for zone in self.zones:
            for n in zone.neighbours:
                if n not in zone_ids:
                    raise ValueError(f"zone {zone.id} references unknown neighbour {n}")
        for stream in self.streams:
            if stream.system not in system_ids:
                raise ValueError(
                    f"stream {stream.source} references unknown system {stream.system}"
                )
        return self


class Observation(BaseModel):
    model_config = ConfigDict(frozen=True)

    obs_id: str = Field(default_factory=lambda: str(uuid4()))
    source: str
    source_kind: SourceKind
    zone: str
    system: str
    value: float
    event_time: datetime
    arrival_time: datetime
    quality_flags: list[QualityFlag | str] = Field(default_factory=list)
    node_id: str | None = Field(default=None, description="derived zone:system")




    @field_validator("event_time", "arrival_time")
    @classmethod
    def _aware(cls, v):
        return _ensure_aware(v)

    @model_validator(mode="after")
    def _ordering_and_node(self) -> "Observation":
        if self.arrival_time < self.event_time:
            raise ValueError("arrival_time must be >= event_time")
        if self.node_id is None:
            object.__setattr__(self, "node_id", f"{self.zone}:{self.system}")
        return self


class PredictionRecord(BaseModel):
    """Defined for Phase 1; unused by the replay backbone itself."""

    model_config = ConfigDict(frozen=True)

    issued_at: datetime
    node: NodeId
    horizon_hours: float = Field(ge=0)
    p_state_geq: dict[str, float]  # e.g. {"HIGH_RISK": 0.12, "CRITICAL": 0.03}
    ttc_quantiles: dict[str, float]  # e.g. {"p50": 31.0, "p80": 44.0}
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("issued_at")
    @classmethod
    def _aware(cls, v):
        return _ensure_aware(v)


class StreamMessage(BaseModel):
    """The exact JSON message the future WebSocket will emit."""

    model_config = ConfigDict(frozen=True)

    type: str = "observations"
    clock_time: datetime
    observations: list[Observation] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("clock_time")
    @classmethod
    def _aware(cls, v):
        return _ensure_aware(v)
