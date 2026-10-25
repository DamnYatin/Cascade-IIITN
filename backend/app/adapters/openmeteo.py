"""Open-Meteo Archive rain adapter (ERA5-family reanalysis)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from ..schemas import Observation, QualityFlag, SourceKind
from .base import RainAdapter

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_CACHE_DIR = REPO_ROOT / "data" / "cache" / "openmeteo"


class OpenMeteoAdapter:
    """Reads cached hourly precipitation and soil moisture from Open-Meteo."""

    source_id = "rain_openmeteo"

    def __init__(
        self,
        city_id: str = "upper_assam",
        cache_dir: Path | str = DEFAULT_CACHE_DIR,
        latency_hours: float = 24.0,
    ):
        self.city_id = city_id
        self.cache_dir = Path(cache_dir)
        self.latency_hours = latency_hours

    def _load_zone_cache(self, zone_id: str) -> dict:
        cache_file = self.cache_dir / f"{self.city_id}_{zone_id}.json"
        if not cache_file.exists():
            raise FileNotFoundError(
                f"Open-Meteo cache missing for zone {zone_id}: {cache_file}. "
                "Run 'python scripts/fetch_assam_data.py' first."
            )
        with cache_file.open("r", encoding="utf-8") as f:
            return json.load(f)

    def to_rain_series(
        self,
        zone_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> dict[datetime, float]:
        """Return hourly rainfall (mm) keyed by timezone-aware UTC datetime."""
        data = self._load_zone_cache(zone_id)
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        precip = hourly.get("precipitation", [])

        series: dict[datetime, float] = {}
        for t_str, val in zip(times, precip):
            dt = datetime.fromisoformat(t_str).replace(tzinfo=timezone.utc)
            if start_time <= dt <= end_time:
                series[dt] = max(0.0, float(val or 0.0))
        return series

    def to_observations(
        self,
        zone_id: str,
        start_time: datetime,
        end_time: datetime,
        system: str = "river_embankment",
    ) -> list[Observation]:
        """Convert hourly rain into frozen Observation objects with latency gating."""
        series = self.to_rain_series(zone_id, start_time, end_time)
        observations: list[Observation] = []

        for dt, val in sorted(series.items()):
            if val <= 0:
                continue  # keep stream sparse
            arrival_time = dt + timedelta(hours=self.latency_hours)
            obs = Observation(
                obs_id=f"openmeteo:{zone_id}:{dt.strftime('%Y%m%d%H%M')}",
                source=self.source_id,
                source_kind=SourceKind.REAL,
                zone=zone_id,
                system=system,
                value=round(float(val), 4),
                event_time=dt,
                arrival_time=arrival_time,
                quality_flags=[
                    QualityFlag.REAL,
                    "product=openmeteo_era5",
                    "aggregation=centroid",
                ],
                node_id=f"{zone_id}:{system}",
            )
            observations.append(obs)

        return observations
