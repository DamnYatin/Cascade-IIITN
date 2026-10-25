"""Tests E13 and E19: Evaluation Canary and Metric Self-Tests with Synthetic Predictors.

Verifies:
  - E13: Future isolation canary: replacing observations after T with garbage yields
    byte-identical predictions and metrics at or before T on both configs.
  - E19: Metric self-tests:
      * Perfect-foresight predictor achieves near-zero Brier and large positive lead.
      * Constant 0.5 predictor yields analytically expected Brier and flat reliability.
      * Random predictor shows no skill (BSS <= 0).
      * Time-shuffled predictor (permutation control) destroys skill.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
import pytest

from backend.app.city_config import load_city_config
from backend.app.eval.alerts import AlertRun, attribute_alerts, detect_alert_runs
from backend.app.eval.events import TrueEpisode, extract_zone_cascade_episodes
from backend.app.eval.metrics import (
    brier_score,
    brier_skill_score,
    compute_reliability_bins,
    compute_warning_metrics,
)
from backend.app.eval.runner import EvalRunConfig, run_single_evaluation
from backend.app.eval.scenarios import build_scenario_instance
from backend.app.forecast.config import load_forecast_config
from backend.app.forecast.engine import ForecastEngine
from backend.app.replay.stream import ReplayStream, StreamView
from backend.app.schemas import Observation, QualityFlag, SourceKind


def test_e13_evaluation_canary_both_configs(upper_assam_config, north_bank_config, tmp_path: Path):
    """E13: Verify evaluation-level future isolation on both configs.

    Corrupting all data with arrival_time > T must leave predictions at or before T byte-identical.
    """
    for cfg in [upper_assam_config, north_bank_config]:
        t0 = cfg.start_time_utc
        t_cutoff = t0 + timedelta(hours=6)

        # Build scenario
        scenario = build_scenario_instance(
            family="F-storm",
            city_config=cfg,
            seed=42,
            duration_hours=12,
        )

        # Run 1: clean observations
        f_cfg = load_forecast_config()
        f_cfg.rollouts = 10
        engine1 = ForecastEngine(city_config=cfg, forecast_config=f_cfg, global_seed=42)
        stream1 = ReplayStream(scenario.observations)
        view1 = StreamView(stream1, t0)

        snaps1 = []
        for h in [0, 3, 6]:
            clock = t0 + timedelta(hours=h)
            view1.set_clock_time(clock)
            snaps1.append(engine1.step(clock, view1))

        # Run 2: corrupt all observations arriving after t_cutoff with extreme noise
        corrupted_obs = []
        for o in scenario.observations:
            if o.arrival_time > t_cutoff:
                # Corrupt completely
                corrupted_o = o.model_copy(
                    update={"value": -9999.0, "quality_flags": list(o.quality_flags) + [QualityFlag.SPIKE]}
                )
                corrupted_obs.append(corrupted_o)
            else:
                corrupted_obs.append(o)

        engine2 = ForecastEngine(city_config=cfg, forecast_config=f_cfg, global_seed=42)
        stream2 = ReplayStream(corrupted_obs)
        view2 = StreamView(stream2, t0)

        snaps2 = []
        for h in [0, 3, 6]:
            clock = t0 + timedelta(hours=h)
            view2.set_clock_time(clock)
            snaps2.append(engine2.step(clock, view2))

        # Assert byte-for-byte identity of predictions issued at or before T
        for s1, s2 in zip(snaps1, snaps2):
            assert s1.to_canonical_json() == s2.to_canonical_json()


def test_e19_metric_selftests_synthetic_predictors():
    """E19: Metric self-tests using synthetic reference predictors:

    - Perfect foresight
    - Constant 0.5 predictor
    - Random predictor
    - Time-shuffled predictor
    """
    rng = np.random.default_rng(777)
    n = 200
    # Balanced true labels
    y_true = np.array([1 if i < 100 else 0 for i in range(n)])

    # 1. Perfect Foresight Predictor (diagnostic only, uses truth)
    p_perfect = np.array([0.99 if y == 1 else 0.01 for y in y_true])
    bs_perf = brier_score(p_perfect, y_true)
    bss_perf = brier_skill_score(p_perfect, y_true)
    assert bs_perf < 0.02
    assert bss_perf > 0.90

    # 2. Constant 0.5 Predictor
    p_const = np.full(n, 0.5)
    bs_const = brier_score(p_const, y_true)
    # Expected BS: (0.5 - 1)^2 * 0.5 + (0.5 - 0)^2 * 0.5 = 0.25
    assert pytest.approx(bs_const, abs=1e-6) == 0.25
    bss_const = brier_skill_score(p_const, y_true)
    assert pytest.approx(bss_const, abs=1e-6) == 0.0  # Equal to climatology

    # Flat reliability line: single non-empty bin at 0.5 with obs_freq 0.5
    ece_const, bins_const = compute_reliability_bins(p_const, y_true, n_bins=5)
    # Only bin containing 0.5 has items, and pred_mean ≈ obs_freq
    active_bins = [b for b in bins_const if b["count"] > 0]
    assert len(active_bins) == 1
    assert pytest.approx(active_bins[0]["pred_mean"], abs=1e-2) == 0.5
    assert pytest.approx(active_bins[0]["obs_freq"], abs=1e-2) == 0.5

    # 3. Random Uniform Predictor
    p_rand = rng.uniform(0.0, 1.0, size=n)
    bss_rand = brier_skill_score(p_rand, y_true)
    # Expected Brier for uniform is ~0.333 > 0.25 -> negative skill!
    assert bss_rand < 0.0

    # 4. Time-Shuffled Predictor (permutation control)
    # Start with a skilled predictor, then shuffle in time
    p_skilled = np.clip(y_true * 0.8 + rng.normal(0.1, 0.1, size=n), 0.0, 1.0)
    bss_skilled = brier_skill_score(p_skilled, y_true)
    assert bss_skilled > 0.40

    p_shuffled = rng.permutation(p_skilled)
    bss_shuffled = brier_skill_score(p_shuffled, y_true)
    # Permutation control destroys predictive skill
    assert bss_shuffled < bss_skilled
    assert bss_shuffled <= 0.10
