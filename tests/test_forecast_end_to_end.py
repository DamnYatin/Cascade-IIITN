"""Phase 2 end-to-end integration tests: Canary leakage, determinism, and multi-city configs (T1, T7, T23)."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import pytest

from backend.app.city_config import load_city_config
from backend.app.forecast.config import ForecastConfig
from backend.app.forecast.engine import ForecastEngine
from backend.app.replay.stream import ReplayStream
from backend.app.schemas import Observation, QualityFlag, SourceKind
from backend.app.synth.generator import generate_city
from tests.conftest import REPO


def test_t1_leakage_canary_forecast_engine(upper_assam_config, north_bank_config):
    """T1: Corrupting all observations with arrival_time > T leaves snapshots at or before T bit-for-bit identical."""
    for cfg in (upper_assam_config, north_bank_config):
        obs, _ = generate_city(cfg, seed=11, duration_hours=36)
        t0 = cfg.start_time_utc
        t_cutoff = t0 + timedelta(hours=12)

        # 1. Normal run
        f_cfg = ForecastConfig(rollouts=50, step_hours=2)
        engine_a = ForecastEngine(city_config=cfg, forecast_config=f_cfg, global_seed=42)
        stream_a = ReplayStream(list(obs))

        snapshots_a = []
        cur_t = t0 + timedelta(hours=2)
        while cur_t <= t_cutoff:
            snap = engine_a.step(cur_t, stream_a.view)
            snapshots_a.append(snap.to_canonical_json())
            cur_t += timedelta(hours=2)

        # 2. Corrupted run: replace all observations with arrival_time > t_cutoff with extreme garbage
        corrupted_obs = []
        for o in obs:
            if o.arrival_time > t_cutoff:
                corrupted_obs.append(o.model_copy(update={"value": 999999.0, "source": "poison_feed"}))
            else:
                corrupted_obs.append(o)

        engine_b = ForecastEngine(city_config=cfg, forecast_config=f_cfg, global_seed=42)
        stream_b = ReplayStream(corrupted_obs)

        snapshots_b = []
        cur_t = t0 + timedelta(hours=2)
        while cur_t <= t_cutoff:
            snap = engine_b.step(cur_t, stream_b.view)
            snapshots_b.append(snap.to_canonical_json())
            cur_t += timedelta(hours=2)

        # Assert bit-for-bit identical JSON snapshots
        assert snapshots_a == snapshots_b, f"Leakage canary failed for city {cfg.city_id}!"


def test_t7_determinism_same_seed_gives_identical_forecast_hash(upper_assam_config):
    """T7: Same seed produces identical forecast hash; different seed differs."""
    obs, _ = generate_city(upper_assam_config, seed=11, duration_hours=24)
    t0 = upper_assam_config.start_time_utc
    t_eval = t0 + timedelta(hours=6)
    f_cfg = ForecastConfig(rollouts=50)

    # Run 1: seed 42
    engine_1 = ForecastEngine(city_config=upper_assam_config, forecast_config=f_cfg, global_seed=42)
    stream_1 = ReplayStream(list(obs))
    snap_1 = engine_1.step(t_eval, stream_1.view)
    hash_1 = snap_1.compute_forecast_hash()

    # Run 2: seed 42
    engine_2 = ForecastEngine(city_config=upper_assam_config, forecast_config=f_cfg, global_seed=42)
    stream_2 = ReplayStream(list(obs))
    snap_2 = engine_2.step(t_eval, stream_2.view)
    hash_2 = snap_2.compute_forecast_hash()

    assert hash_1 == hash_2, "Determinism failed! Same seed gave different forecast hashes."

    # Run 3: seed 99
    engine_3 = ForecastEngine(city_config=upper_assam_config, forecast_config=f_cfg, global_seed=99)
    stream_3 = ReplayStream(list(obs))
    snap_3 = engine_3.step(t_eval, stream_3.view)
    hash_3 = snap_3.compute_forecast_hash()

    assert hash_1 != hash_3, "Different seed gave identical forecast hash!"


def test_t23_both_configs_run_end_to_end_and_flag_unobserved(upper_assam_config, north_bank_config):
    """T23: Both upper_assam and north_bank_assam run end-to-end with zero code changes."""
    for cfg in (upper_assam_config, north_bank_config):
        obs, _ = generate_city(cfg, seed=1, duration_hours=12)
        t_eval = cfg.start_time_utc + timedelta(hours=6)

        f_cfg = ForecastConfig(rollouts=30)
        engine = ForecastEngine(city_config=cfg, forecast_config=f_cfg, global_seed=123)
        stream = ReplayStream(list(obs))

        snapshot = engine.step(t_eval, stream.view)
        assert snapshot.city_id == cfg.city_id
        assert len(snapshot.zone_risk_states) == len(cfg.zones)
        assert len(snapshot.zone_probabilities) == len(cfg.zones)

        # Unobserved nodes are flagged in estimator
        if engine.estimator.unobserved_nodes:
            for unobs in engine.estimator.unobserved_nodes:
                st = engine.estimator.states[unobs]
                assert st.unobserved is True
                assert st.evidence_quality == 0.0
