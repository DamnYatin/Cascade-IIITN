"""City configuration loader: YAML -> frozen ``CityConfig``.

The YAML is the single source of truth for a city (zones, systems, streams,
thresholds, weak domain-prior edges). Loading validates it through Pydantic so
any invalid config fails fast with a clear error instead of silently producing
a broken simulation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .schemas import CityConfig, Edge, SystemSpec, StreamSpec, Zone


def _parse_dt(value: Any) -> datetime:
    """Parse a YAML datetime into a timezone-aware UTC datetime."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    raise ValueError(f"cannot parse datetime: {value!r}")


def load_city_config(path: str | Path) -> CityConfig:
    """Load and validate a city config from YAML.

    Raises:
        FileNotFoundError: if the config file does not exist.
        ValueError / yaml.YAMLError / pydantic.ValidationError: if the config
            is malformed or fails schema validation.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"city config not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ValueError(f"city config {path} must contain a YAML mapping")

    city_id = raw.get("city_id")
    if not city_id:
        raise ValueError("city config must define city_id")

    zones = [Zone(**z) for z in raw.get("zones", [])]
    systems = [SystemSpec(**s) for s in raw.get("systems", [])]
    streams = [StreamSpec(**s) for s in raw.get("streams", [])]

    start_time = _parse_dt(raw.get("start_time_utc"))
    threshold = float(raw.get("critical_stress_threshold", 0.8))

    prior_edges = []
    for e in raw.get("domain_prior_edges", []):
        prior_edges.append(
            Edge(
                u=e["u"],
                v=e["v"],
                lag_hours=float(e.get("lag_hours", 1.0)),
                weight=float(e.get("weight", 0.0)),
                confidence=float(e.get("confidence", 0.5)),
                last_updated=start_time,
            )
        )

    return CityConfig(
        city_id=str(city_id),
        zones=zones,
        systems=systems,
        streams=streams,
        domain_prior_edges=prior_edges,
        start_time_utc=start_time,
        critical_stress_threshold=threshold,
    )
