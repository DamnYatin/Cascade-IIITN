"""IMD gridded rainfall adapter (zone/geometry driven, no hardcoded districts)."""
from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from ..schemas import Observation, QualityFlag, SourceKind
from .base import RainAdapter

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class IMDGriddedAdapter:
    """IMD daily 0.25 gridded rainfall adapter driven by zone metadata."""

    source_id = "rain_imd_daily"

    def __init__(
        self,
        grid_data_path: Optional[Path | str] = None,
        latency_hours: float = 36.0,  # daily operational publishing lag
    ):
        self.grid_data_path = Path(grid_data_path) if grid_data_path else None
        self.latency_hours = latency_hours

    def to_rain_series(
        self,
        zone_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> dict[datetime, float]:
        if self.grid_data_path is None or not self.grid_data_path.exists():
            return {}
        # Reads daily grid or district-matched rows
        series: dict[datetime, float] = {}
        with self.grid_data_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("zone_id", "").strip().lower() == zone_id.lower():
                    d = datetime.strptime(row["date"].strip(), "%Y-%m-%d").date()
                    dt = datetime(d.year, d.month, d.day, 0, tzinfo=timezone.utc)
                    if start_time <= dt <= end_time:
                        series[dt] = float(row.get("rainfall", 0.0))
        return series

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
            arrival_time = dt + timedelta(hours=self.latency_hours)
            obs = Observation(
                obs_id=f"imd:{zone_id}:{dt.strftime('%Y%m%d')}",
                source=self.source_id,
                source_kind=SourceKind.REAL,
                zone=zone_id,
                system=system,
                value=round(float(val), 4),
                event_time=dt,
                arrival_time=arrival_time,
                quality_flags=[
                    QualityFlag.REAL,
                    "product=imd_daily_gridded",
                    "resolution=24h",
                ],
                node_id=f"{zone_id}:{system}",
            )
            observations.append(obs)

        return observations
