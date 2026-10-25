"""Copernicus CDS ERA5-Land precipitation and soil moisture adapter."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..schemas import Observation, QualityFlag, SourceKind
from .base import RainAdapter, deaccumulate_era5_precipitation

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_CACHE_DIR = REPO_ROOT / "data" / "cache" / "era5land"


class ERA5LandAdapter:
    """ERA5-Land reanalysis adapter with 00:00 UTC de-accumulation and 5-day latency."""

    source_id = "rain_era5land"

    def __init__(
        self,
        city_id: str = "upper_assam",
        cache_dir: Path | str = DEFAULT_CACHE_DIR,
        latency_hours: float = 120.0,  # ~5 days documented operational latency
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
        """Load and deaccumulate ERA5-Land precipitation series."""
        cache_file = self.cache_dir / f"{self.city_id}_{zone_id}.json"
        if not cache_file.exists():
            summary_file = self.cache_dir / f"{self.city_id}_era5land_summary.json"
            if not summary_file.exists():
                raise FileNotFoundError(
                    f"ERA5-Land cache missing for zone {zone_id} in {self.cache_dir}."
                )
            return {}

        with cache_file.open("r", encoding="utf-8") as f:
            data = json.load(f)

        raw_accum = []
        for item in data.get("accumulated_precipitation", []):
            dt = datetime.fromisoformat(item["time"]).replace(tzinfo=timezone.utc)
            val = float(item["accum_val"])
            raw_accum.append((dt, val))

        deaccum = deaccumulate_era5_precipitation(raw_accum)
        return {
            dt: val
            for dt, val in deaccum
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
                obs_id=f"era5land:{zone_id}:{dt.strftime('%Y%m%d%H%M')}",
                source=self.source_id,
                source_kind=SourceKind.REAL,
                zone=zone_id,
                system=system,
                value=round(float(val), 4),
                event_time=dt,
                arrival_time=arrival_time,
                quality_flags=[
                    QualityFlag.REAL,
                    "product=era5land",
                    "deaccumulated=true",
                ],
                node_id=f"{zone_id}:{system}",
            )
            observations.append(obs)

        return observations
