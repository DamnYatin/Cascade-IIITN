"""Adapters for forecaster ablations (B4 through B7) and unified baseline runner.

Rule V1:
  - Consumes STRICTLY StreamView.
  - Zero imports of ground truth or evaluation packages.
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from backend.app.city_config import load_city_config
from backend.app.forecast.config import ForecastConfig, load_forecast_config
from backend.app.forecast.engine import ForecastEngine
from backend.app.schemas import CityConfig


def make_ablation_forecaster(
    ablation_name: str,
    city_config: CityConfig,
    base_config: Optional[ForecastConfig] = None,
    seed: int = 42,
    anchor_mode: str = "off",
) -> ForecastEngine:
    """Instantiate ForecastEngine with specified ablation flags active.

    Ablations:
      - b4_static_graph: static graph after burn-in (online learning & drift boost disabled)
      - b5_prior_only: domain prior only (online learning completely disabled)
      - b6_no_trust: no source trust, no outlier gating, no evidence widening
      - b7_persistence_outlook: basic persistence decay rain outlook only
    """
    cfg = base_config.model_copy(deep=True) if base_config else load_forecast_config()

    if ablation_name == "b4_static_graph":
        cfg.ablation.static_graph = True
    elif ablation_name == "b5_prior_only":
        cfg.ablation.prior_only = True
    elif ablation_name == "b6_no_trust":
        cfg.ablation.no_source_trust = True
        cfg.ablation.no_evidence_widening = True
    elif ablation_name == "b7_persistence_outlook":
        cfg.ablation.persistence_outlook_only = True
    elif ablation_name not in ("full", "forecaster"):
        raise ValueError(f"Unknown ablation name: {ablation_name}")

    return ForecastEngine(
        city_config=city_config,
        forecast_config=cfg,
        global_seed=seed,
        anchor_mode=anchor_mode,
    )
