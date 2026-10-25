"""Source-agnostic adapters package for real and simulated inputs."""
from .base import (
    RainAdapter,
    aggregate_half_hourly_to_hourly,
    compute_zonal_area_weighted_mean,
    deaccumulate_era5_precipitation,
)
from .cwc import CWCAdapter
from .era5land import ERA5LandAdapter
from .imd_gridded import IMDGriddedAdapter
from .imerg import IMERGAdapter
from .openmeteo import OpenMeteoAdapter

__all__ = [
    "RainAdapter",
    "OpenMeteoAdapter",
    "IMERGAdapter",
    "ERA5LandAdapter",
    "IMDGriddedAdapter",
    "CWCAdapter",
    "deaccumulate_era5_precipitation",
    "aggregate_half_hourly_to_hourly",
    "compute_zonal_area_weighted_mean",
]
