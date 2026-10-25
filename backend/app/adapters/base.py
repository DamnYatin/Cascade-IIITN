"""Source-agnostic rain and hydrometeorological adapter foundation.

Defines the RainAdapter protocol, time-series transformations, and spatial aggregation:
  - ERA5-Land de-accumulation (with 00:00 UTC reset handling).
  - NASA GPM IMERG 30-min to 1-hour aggregation.
  - Zonal area-weighted polygon mean.
  - Latency gating and provenance tagging.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol, runtime_checkable

from shapely.geometry import Polygon, box

from ..schemas import Observation, QualityFlag, SourceKind


@runtime_checkable
class RainAdapter(Protocol):
    """Protocol for all precipitation and hydrometeorological adapters."""

    source_id: str
    latency_hours: float

    def to_observations(
        self,
        zone_id: str,
        start_time: datetime,
        end_time: datetime,
        system: str = "river_embankment",
    ) -> list[Observation]:
        """Produce timezone-aware UTC observations within [start_time, end_time]."""
        ...

    def to_rain_series(
        self,
        zone_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> dict[datetime, float]:
        """Produce hourly rainfall (mm) keyed by UTC datetime."""
        ...


def deaccumulate_era5_precipitation(
    series: list[tuple[datetime, float]],
) -> list[tuple[datetime, float]]:
    """Convert ERA5-Land daily-accumulated precipitation to hourly increments.

    In ERA5-Land:
      - `total_precipitation` is accumulated from 00:00 UTC each day.
      - At 01:00 UTC, the value is the accumulated precipitation since 00:00 UTC.
      - At subsequent hours (02:00, 03:00, ...), the value increases monotonically
        with further rainfall.
      - At 00:00 UTC (or after 24:00), the accumulation resets to 0.

    This function produces hourly rainfall (in mm, converting metres to mm if < 1.0):
      - Handles the 00:00 UTC reset cleanly.
      - Clips negative floating-point differences to 0.0.
      - Preserves exact timestamps.
    """
    if not series:
        return []

    # Sort strictly by timestamp
    sorted_series = sorted(series, key=lambda x: x[0])
    deaccumulated: list[tuple[datetime, float]] = []

    prev_dt: datetime | None = None
    prev_accum: float = 0.0

    for dt, accum in sorted_series:
        if dt.tzinfo is None:
            raise ValueError(f"Naive datetime rejected: {dt}")

        val = float(accum)
        # ERA5 native unit is metres; if values are in metres (e.g. max < 0.5), convert to mm
        # In this helper, caller passes metres or mm; if <= 1.0, scale to mm
        if val < 0.5 and val > 0:
            val = val * 1000.0

        # Check for daily reset: hour == 1 or new calendar day or drop in accumulation
        is_day_start = dt.hour == 1 or (prev_dt is not None and dt.date() > prev_dt.date())

        if is_day_start or prev_dt is None:
            hourly_val = max(0.0, val)
        else:
            if val >= prev_accum:
                hourly_val = max(0.0, val - prev_accum)
            else:
                # Accumulation reset occurred
                hourly_val = max(0.0, val)

        deaccumulated.append((dt, round(hourly_val, 4)))
        prev_dt = dt
        prev_accum = val

    return deaccumulated


def aggregate_half_hourly_to_hourly(
    half_hourly: list[tuple[datetime, float]],
) -> list[tuple[datetime, float]]:
    """Aggregate GPM IMERG 30-min rain rates (mm/hr) to hourly rainfall depths (mm).

    IMERG reports rain rate in mm/hr for 30-minute intervals.
    A complete hour contains two 30-minute intervals:
      e.g. 14:00 (for 14:00-14:30) and 14:30 (for 14:30-15:00).
      Hourly depth (mm) = (rate_00 + rate_30) / 2.0.

    Rule: Missing granules produce NO events (never faked as zeros).
    """
    if not half_hourly:
        return []

    # Bucket by start of the hour
    buckets: dict[datetime, list[float]] = {}
    for dt, rate in half_hourly:
        if dt.tzinfo is None:
            raise ValueError(f"Naive datetime rejected: {dt}")
        hour_start = dt.replace(minute=0, second=0, microsecond=0)
        buckets.setdefault(hour_start, []).append(float(rate))

    hourly: list[tuple[datetime, float]] = []
    for hour_start in sorted(buckets.keys()):
        rates = buckets[hour_start]
        # Only produce an event if at least one valid granule is present
        # In 30-min data, mean rate over present intervals * 1 hour
        avg_rate = sum(rates) / len(rates)
        hourly.append((hour_start, round(max(0.0, avg_rate), 4)))

    return hourly


def compute_zonal_area_weighted_mean(
    grid_cells: list[tuple[Polygon, float]],
    zone_polygon: Polygon,
) -> float:
    """Compute area-weighted mean value of grid cells intersecting a zone polygon.

    Parameters:
      grid_cells: list of (cell_polygon, value)
      zone_polygon: zone boundary Polygon

    Returns:
      Area-weighted mean. If no cells intersect, returns 0.0.
    """
    if not grid_cells or zone_polygon.is_empty:
        return 0.0

    total_weight = 0.0
    weighted_sum = 0.0

    for cell_poly, val in grid_cells:
        if not cell_poly.intersects(zone_polygon):
            continue
        inter = cell_poly.intersection(zone_polygon)
        area = inter.area
        if area > 0:
            total_weight += area
            weighted_sum += area * float(val)

    if total_weight <= 0:
        return 0.0

    return round(weighted_sum / total_weight, 4)
