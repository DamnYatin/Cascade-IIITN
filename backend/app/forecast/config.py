"""Forecast engine configuration and schema validation."""
from __future__ import annotations

from pathlib import Path
from typing import Any, List
import yaml
from pydantic import BaseModel, Field, model_validator


class StressLevelsConfig(BaseModel):
    watch: float = Field(default=0.40, ge=0.0, le=1.0)
    high_risk: float = Field(default=0.60, ge=0.0, le=1.0)
    critical: float = Field(default=0.80, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def check_monotonicity(self) -> StressLevelsConfig:
        if not (self.watch < self.high_risk < self.critical):
            raise ValueError(
                f"Stress levels must be strictly increasing: watch={self.watch}, "
                f"high_risk={self.high_risk}, critical={self.critical}"
            )
        return self


class LearnerConfig(BaseModel):
    forgetting: float = Field(default=0.995, gt=0.0, le=1.0)
    ridge_to_prior: float = Field(default=1.0, ge=0.0)
    max_active_edges_per_node: int = Field(default=6, ge=1)
    z_min: float = Field(default=2.0, ge=0.0)
    w_min: float = Field(default=0.02, ge=0.0)
    edge_hysteresis_steps: int = Field(default=6, ge=1)


class DriftConfig(BaseModel):
    method: str = Field(default="page_hinkley")
    delta: float = Field(default=0.005, ge=0.0)
    lambda_: float = Field(default=0.5, ge=0.0)
    boost_hours: int = Field(default=24, ge=1)
    forgetting_during_boost: float = Field(default=0.97, gt=0.0, le=1.0)


class TrustConfig(BaseModel):
    prior_alpha: float = Field(default=4.0, gt=0.0)
    prior_beta: float = Field(default=1.0, gt=0.0)
    min_corroborators_for_reports: int = Field(default=2, ge=1)
    report_weight_cap: float = Field(default=0.3, ge=0.0, le=1.0)
    outlier_z: float = Field(default=4.0, ge=1.0)
    flatline_hours: int = Field(default=6, ge=1)


class MapperConfig(BaseModel):
    p_crit72_watch: float = Field(default=0.05, ge=0.0, le=1.0)
    p_crit72_high: float = Field(default=0.20, ge=0.0, le=1.0)
    p_crit12_critical: float = Field(default=0.50, ge=0.0, le=1.0)
    ttc_high_hours: int = Field(default=24, ge=1)
    min_dwell_steps: int = Field(default=3, ge=1)
    alert_tau: float = Field(default=0.30, ge=0.0, le=1.0)
    alert_k: int = Field(default=2, ge=1)


class AggregationConfig(BaseModel):
    zone_cascade_min_systems: int = Field(default=2, ge=1)
    city_zone_fraction: float = Field(default=0.2, gt=0.0, le=1.0)


class AblationConfig(BaseModel):
    static_graph: bool = Field(default=False)
    prior_only: bool = Field(default=False)
    no_source_trust: bool = Field(default=False)
    no_evidence_widening: bool = Field(default=False)
    persistence_outlook_only: bool = Field(default=False)


class ForecastConfig(BaseModel):
    step_hours: int = Field(default=1, ge=1)
    horizons_hours: List[int] = Field(default_factory=lambda: [1, 3, 6, 12, 24, 48, 72])
    rollouts: int = Field(default=300, ge=10)
    stress_levels: StressLevelsConfig = Field(default_factory=StressLevelsConfig)
    candidate_lags_hours: List[int] = Field(default_factory=lambda: [1, 2, 3, 6, 12, 24])
    reorder_window_hours: int = Field(default=24, ge=1)
    burn_in_hours: int = Field(default=72, ge=0)

    learner: LearnerConfig = Field(default_factory=LearnerConfig)
    drift: DriftConfig = Field(default_factory=DriftConfig)
    trust: TrustConfig = Field(default_factory=TrustConfig)
    mapper: MapperConfig = Field(default_factory=MapperConfig)
    aggregation: AggregationConfig = Field(default_factory=AggregationConfig)
    ablation: AblationConfig = Field(default_factory=AblationConfig)


def load_forecast_config(path: str | Path | None = None) -> ForecastConfig:
    """Load and validate forecast configuration from YAML."""
    if path is None:
        path = Path("configs/forecast.yaml")
    else:
        path = Path(path)

    if not path.exists():
        # Fall back to default config if file does not exist
        return ForecastConfig()

    content = path.read_text(encoding="utf-8")
    data = yaml.safe_load(content) or {}
    return ForecastConfig.model_validate(data)
