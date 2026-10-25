"""NASA GPM IMERG Late Run (V07) satellite rainfall adapter."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from ..schemas import Observation, QualityFlag, SourceKind
from .base import RainAdapter, aggregate_half_hourly_to_hourly

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_CACHE_DIR = REPO_ROOT / "data" / "cache" / "imerg"


class IMERGAdapter:
    """Processes GPM IMERG satellite rainfall observations with latency gating."""

    source_id = "rain_imerg_late"

    def __init__(
        self,
        city_id: str = "upper_assam",
        cache_dir: Path | str = DEFAULT_CACHE_DIR,
        latency_hours: float = 14.0,  # Documented GPM Late run latency
    ):
        self.city_id = city_id
        self.cache_dir = Path(cache_dir)
        self.latency_hours = latency_hours

    def to_rain_series(
        self,
        zone_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> dict[datetime, float]:
        """Return hourly aggregated IMERG rainfall."""
        cache_file = self.cache_dir / f"{self.city_id}_{zone_id}.json"
        if not cache_file.exists():
            # Check summary or fixture
            summary_file = self.cache_dir / f"{self.city_id}_imerg_summary.json"
            if not summary_file.exists():
                raise FileNotFoundError(
                    f"IMERG cache not found for {zone_id} in {self.cache_dir}."
                )
            # If indexed summary exists, return empty or parsed granules
            return {}

        with cache_file.open("r", encoding="utf-8") as f:
            data = json.load(f)

        raw_half_hourly = []
        for item in data.get("half_hourly", []):
            dt = datetime.fromisoformat(item["time"]).replace(tzinfo=timezone.utc)
            val = float(item["precipitation_rate"])
            raw_half_hourly.append((dt, val))

        aggregated = aggregate_half_hourly_to_hourly(raw_half_hourly)
        return {
            dt: val
            for dt, val in aggregated
            if start_time <= dt <= end_time
        }

    def to_observations(
        self,
        zone_id: str,
        start_time: datetime,
        end_time: datetime,
        system: str = "river_embankment",
    ) -> list[Observation]:
        series = self.to_rain_series(zone_id, start_time, end_time)
        observations: list[Observation] = []

        for dt, val in sorted(series.items()):
            if val <= 0:
                continue
            arrival_time = dt + timedelta(hours=self.latency_hours)
            obs = Observation(
                obs_id=f"imerg:{zone_id}:{dt.strftime('%Y%m%d%H%M')}",
                source=self.source_id,
                source_kind=SourceKind.REAL,
                zone=zone_id,
                system=system,
                value=round(float(val), 4),
                event_time=dt,
                arrival_time=arrival_time,
                quality_flags=[
                    QualityFlag.REAL,
                    "product=imerg_late",
                    "aggregation=hourly_mean",
                ],
                node_id=f"{zone_id}:{system}",
            )
            observations.append(obs)

        return observations
