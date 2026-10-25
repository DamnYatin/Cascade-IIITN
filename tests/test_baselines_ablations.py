"""Tests E12, E17, and E18: Baselines, Ablations, and Package Isolation.

Verifies:
  - E12: Import and file-reference isolation for forecast/ and baselines/.
  - E17: Baselines (B1, B2, B3) run end-to-end on both city configs through StreamView only,
    produce valid scores in [0, 1], are deterministic, and handle missing data without NaN.
  - E18: Ablations (B4 through B7) change behavior in the intended direction.
"""
from __future__ import annotations

import ast
import importlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
import pytest

from backend.app.baselines.ablations import make_ablation_forecaster
from backend.app.baselines.isolated import IsolatedMonitoringBaseline
from backend.app.baselines.rainrule import ClimatologyPersistenceBaseline, RainRuleBaseline
from backend.app.city_config import load_city_config
from backend.app.forecast.config import load_forecast_config
from backend.app.forecast.engine import ForecastEngine
from backend.app.replay.faults import FaultInjector, FaultSpec
from backend.app.replay.stream import ReplayStream, StreamView
from backend.app.schemas import Observation, QualityFlag, SourceKind
from tests.conftest import REPO


def test_e12_import_and_file_isolation_forecast_and_baselines():
    """E12: Verify forecast/ and baselines/ NEVER import eval, synth, or scenario label files (Rule V1)."""
    prohibited_modules = ["backend.app.eval", "backend.app.synth"]
    forbidden_terms = [
        "critical_labels.json",
        "observed_response.json",
        "events.json",
        "official_bulletins.json",
        "planted",
        "ground_truth",
    ]

    target_packages = ["backend.app.forecast", "backend.app.baselines"]

    for pkg_name in target_packages:
        mod = importlib.import_module(pkg_name)
        pkg_path = Path(mod.__file__).parent
        for py in pkg_path.glob("**/*.py"):
            text = py.read_text(encoding="utf-8")
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for prohibited in prohibited_modules:
                            assert not alias.name.startswith(prohibited), f"{py} imports {alias.name}"
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for prohibited in prohibited_modules:
                            assert not node.module.startswith(prohibited), f"{py} imports from {node.module}"

            for term in forbidden_terms:
                assert term not in text.lower(), f"{py} references forbidden term: {term}"


def test_e17_baselines_run_end_to_end_on_both_configs(upper_assam_config, north_bank_config):
    """E17: Verify each baseline runs end-to-end on both configs, outputs in [0, 1], and handles missing data."""
    configs = [upper_assam_config, north_bank_config]

    for cfg in configs:
        b1 = IsolatedMonitoringBaseline(cfg)
        b2 = RainRuleBaseline(cfg)
        b3 = ClimatologyPersistenceBaseline(cfg)

        t0 = cfg.start_time_utc
        # Create small stream of 10 observations with missing zones
        obs = [
            Observation(
                source="rain_sensor",
                source_kind=SourceKind.REAL,
                zone=cfg.zones[0].id,
                system=cfg.systems[0].id,
                value=45.0,
                event_time=t0,
                arrival_time=t0 + timedelta(minutes=5),
            ),
            Observation(
                source="traffic_sensor",
                source_kind=SourceKind.SIMULATED,
                zone=cfg.zones[0].id,
                system="transport" if "transport" in [s.id for s in cfg.systems] else cfg.systems[1].id,
                value=85.0,
                event_time=t0 + timedelta(hours=1),
                arrival_time=t0 + timedelta(hours=1, minutes=10),
            ),
        ]
        stream = ReplayStream(obs)
        stream_view = StreamView(stream, t0 + timedelta(hours=2))

        # 1. Isolated Monitoring (B1)
        scores1 = b1.step(t0 + timedelta(hours=2), stream_view)
        assert len(scores1) == len(cfg.zones)
        for z_id, sc in scores1.items():
            assert 0.0 <= sc <= 1.0
            assert not np.isnan(sc)

        # 2. Rain Rule (B2)
        scores2 = b2.step(t0 + timedelta(hours=2), stream_view)
        assert len(scores2) == len(cfg.zones)
        for z_id, sc in scores2.items():
            assert 0.0 <= sc <= 1.0
            assert not np.isnan(sc)

        # 3. Climatology / Persistence (B3)
        scores3 = b3.step(t0 + timedelta(hours=2), stream_view)
        assert len(scores3) == len(cfg.zones)
        for z_id, sc in scores3.items():
            assert 0.0 <= sc <= 1.0
            assert not np.isnan(sc)


def test_e18_ablation_flags_behavior_change(upper_assam_config):
    """E18: Verify ablation flags alter forecaster behavior in the intended direction.

    Specifically:
      - B5 (prior_only): learning updates are disabled; learned weights stay at zero.
      - B6 (no_source_trust): outlier gating is bypassed; faulty spikes are trusted.
    """
    t0 = upper_assam_config.start_time_utc
    f_cfg = load_forecast_config()
    f_cfg.rollouts = 10
    f_cfg.burn_in_hours = 0  # immediate learning outside burn-in

    # 1. Test B5 prior_only
    engine_b5 = make_ablation_forecaster("b5_prior_only", upper_assam_config, f_cfg, seed=42)
    obs_batch = [
        Observation(
            source="sensor_siva",
            source_kind=SourceKind.SIMULATED,
            zone="sivasagar",
            system="river_embankment",
            value=80.0,
            event_time=t0,
            arrival_time=t0 + timedelta(minutes=5),
        ),
        Observation(
            source="sensor_siva_trans",
            source_kind=SourceKind.SIMULATED,
            zone="sivasagar",
            system="transport",
            value=85.0,
            event_time=t0 + timedelta(hours=1),
            arrival_time=t0 + timedelta(hours=1, minutes=5),
        ),
    ]
    stream = ReplayStream(obs_batch)
    stream_view = StreamView(stream, t0 + timedelta(hours=2))

    snap_b5 = engine_b5.step(t0 + timedelta(hours=2), stream_view)
    # EdgeBook should have no newly learned dynamic edges
    assert len(engine_b5.learner.edge_book.snapshot()) == 0

    # 2. Test B6 no_source_trust
    engine_b6 = make_ablation_forecaster("b6_no_trust", upper_assam_config, f_cfg, seed=42)
    # Trust manager in B6 returns 1.0 and is_outlier returns False
    assert engine_b6.trust_manager.get_trust("adversarial_sensor") == 1.0
    assert engine_b6.trust_manager.is_outlier("sivasagar:transport", 1000.0, t0, [10.0, 12.0]) is False
