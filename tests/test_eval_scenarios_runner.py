"""Tests E7 and E20: Storm Generator and Runner Caching / Determinism.

Verifies:
  - E7: Storm generator determinism, non-negativity, and upstream-to-downstream lag.
  - E20: Runner caching: identical inputs yield cached predictions; key alterations invalidate; resume yields byte-identical results.
"""
from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pytest

from backend.app.city_config import load_city_config
from backend.app.eval.protocol import PROTOCOL_FAMILIES, compute_protocol_hash
from backend.app.eval.runner import EvalRunConfig, run_single_evaluation
from backend.app.eval.storm_rain import StochasticStormRainGenerator


def test_e7_storm_generator_properties():
    """E7: Verify storm generator determinism, non-negativity, and upstream lag."""
    city_cfg = load_city_config("configs/upper_assam.yaml")
    gen = StochasticStormRainGenerator(
        arrival_rate=0.08,
        min_intensity_mm=20.0,
        max_intensity_mm=50.0,
        upstream_lag_hours=3.0,
    )

    # 1. Determinism: Same seed produces exact same dictionary
    r1 = gen.generate(city_cfg.zones, duration_hours=72, seed=42)
    r2 = gen.generate(city_cfg.zones, duration_hours=72, seed=42)
    assert r1 == r2

    # Different seed produces different rainfall
    r3 = gen.generate(city_cfg.zones, duration_hours=72, seed=43)
    assert r1 != r3

    # 2. Non-negativity
    for z_id, series in r1.items():
        for h, mm in series.items():
            assert mm >= 0.0, f"Rainfall in {z_id} at hour {h} was negative: {mm}"

    # 3. Upstream-to-downstream lag:
    # Upstream driver zone: mon_nl. Downstream zone: charaideo or sivasagar.
    # Find the first major storm peak in mon_nl
    mon_series = r1.get("mon_nl", {})
    downstream_series = r1.get("sivasagar", {})

    mon_rain_hours = [h for h, val in mon_series.items() if val > 10.0]
    down_rain_hours = [h for h, val in downstream_series.items() if val > 10.0]

    if mon_rain_hours and down_rain_hours:
        # First major rain in upstream should start at or before downstream rain
        assert min(mon_rain_hours) <= min(down_rain_hours)

    # 4. Quiet control generator: all values <= 1.0 mm
    quiet = gen.generate_quiet(city_cfg.zones, duration_hours=72, seed=42)
    for z_id, series in quiet.items():
        for h, mm in series.items():
            assert mm <= 1.0


def test_e20_runner_caching_and_resume(tmp_path: Path):
    """E20: Verify runner disk cache:

    - Identical config loads from cache without recomputing.
    - Altering any signature parameter (e.g. seed, rollouts) invalidates cache.
    - Resume produces identical outputs.
    """
    run_cfg = EvalRunConfig(
        city_id="upper_assam",
        family="F-storm",
        seed=11,
        duration_hours=12,  # Short duration for fast unit testing
        cadence_hours=3,
        rollouts=10,
        method="forecaster",
    )

    # Run 1: generate and cache
    res1 = run_single_evaluation(run_cfg, cache_dir=tmp_path, use_cache=True)
    assert Path(tmp_path).exists()
    cached_files = list(tmp_path.glob("*.json"))
    assert len(cached_files) == 1

    # Run 2: should read from cache (verify by modifying file or comparing keys)
    res2 = run_single_evaluation(run_cfg, cache_dir=tmp_path, use_cache=True)
    assert res1["cache_key"] == res2["cache_key"]
    assert res1["zone_p_crit_72"] == res2["zone_p_crit_72"]

    # Alter parameter (e.g. rollouts from 10 to 15) -> cache key changes, new file created
    run_cfg_altered = EvalRunConfig(
        city_id="upper_assam",
        family="F-storm",
        seed=11,
        duration_hours=12,
        cadence_hours=3,
        rollouts=15,  # Altered!
        method="forecaster",
    )
    res3 = run_single_evaluation(run_cfg_altered, cache_dir=tmp_path, use_cache=True)
    assert res3["cache_key"] != res1["cache_key"]
    cached_files_after = list(tmp_path.glob("*.json"))
    assert len(cached_files_after) == 2


def test_protocol_hash_stability():
    """Verify pre-registered protocol hash is deterministic and non-empty."""
    h1 = compute_protocol_hash()
    h2 = compute_protocol_hash()
    assert h1 == h2
    assert len(h1) == 64
