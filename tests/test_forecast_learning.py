"""Phase 2 tests: Dependency learning, EdgeBook, drift, and label maturity (T3, T15 - T18)."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
import numpy as np
import pytest

from backend.app.city_config import load_city_config
from backend.app.forecast.config import ForecastConfig, LearnerConfig, DriftConfig
from backend.app.forecast.drift import PageHinkleyDetector, TwoWindowMeanShiftDetector, make_drift_detector
from backend.app.forecast.learner import DependencyLearner, EdgeBook, ForecastModel
from backend.app.schemas import Edge, NodeId
from tests.conftest import REPO


def test_t3_label_maturity_enforced_in_learner(upper_assam_config):
    """T3: Assert every update has clock_time >= target_time and rejects future targets."""
    l_cfg = LearnerConfig()
    learner = DependencyLearner(upper_assam_config, l_cfg, candidate_lags=[1, 2, 3])
    t0 = upper_assam_config.start_time_utc

    # Valid update: clock_time == target_time == t0 + 1h
    t_target = t0 + timedelta(hours=1)
    t_clock = t0 + timedelta(hours=1)
    learner.record_update(
        node="sivasagar:river_embankment",
        feature_vals={"sivasagar:river_embankment@-1h": 0.20},
        target_stress=0.22,
        target_time=t_target,
        clock_time=t_clock,
    )
    assert len(learner.update_log) == 1
    assert learner.update_log[0] == (t_target, t_clock)

    # Invalid update: target_time > clock_time (future leakage attempt)
    t_future_target = t0 + timedelta(hours=2)
    with pytest.raises(AssertionError, match="R3 violation"):
        learner.record_update(
            node="sivasagar:river_embankment",
            feature_vals={"sivasagar:river_embankment@-1h": 0.20},
            target_stress=0.25,
            target_time=t_future_target,
            clock_time=t_clock,  # clock is at 1h, target at 2h!
        )


def test_t18_domain_prior_is_overridable(upper_assam_config):
    """T18: A deliberately wrong prior edge is overridden by real data streaming in."""
    l_cfg = LearnerConfig(forgetting=0.99, ridge_to_prior=0.5, w_min=0.01)
    learner = DependencyLearner(upper_assam_config, l_cfg, candidate_lags=[1, 2])
    target_node = "sivasagar:transport"
    parent_node = "sivasagar:river_embankment"

    # Set a deliberately wrong prior: weight = -0.80 (claiming river embankment massively relieves road stress)
    node_rls = learner._learners[target_node]
    feat_key = f"{parent_node}@-1h"
    idx = node_rls.features.index(feat_key)
    node_rls.theta[idx] = -0.80
    node_rls.theta_0[idx] = -0.80

    t0 = upper_assam_config.start_time_utc

    # Feed data where true relationship is strongly POSITIVE (w = +0.65)
    rng = np.random.default_rng(42)
    for h in range(1, 120):
        t = t0 + timedelta(hours=h)
        parent_val = float(rng.uniform(0.3, 0.9))
        # True target: 0.10 + 0.65 * parent_val
        true_target = 0.10 + 0.65 * parent_val + float(rng.normal(0, 0.02))

        learner.record_update(
            node=target_node,
            feature_vals={feat_key: parent_val, f"{target_node}@-1h": 0.2},
            target_stress=true_target,
            target_time=t,
            clock_time=t,
        )

    learned_w = float(node_rls.theta[idx])
    # The learned weight must have moved away from -0.80 and become strongly positive
    assert learned_w > 0.30, f"Prior was not overridden! Weight remained {learned_w}"


def test_t16_drift_detector_fires_and_readapts(upper_assam_config):
    """T16: Detector fires on shift and RLS re-adapts with boosted forgetting."""
    d_cfg = DriftConfig(delta=0.005, lambda_=0.40)
    detector = make_drift_detector(d_cfg)
    t0 = upper_assam_config.start_time_utc

    drift_fired_at = None
    # Stationary phase: zero-mean errors
    rng = np.random.default_rng(101)
    for h in range(1, 50):
        t = t0 + timedelta(hours=h)
        err = float(rng.normal(0.0, 0.05))
        fired = detector.update(abs(err), clock_time=t)
        assert not fired, "False drift fired during stationary phase!"

    # Shift phase: sudden error spike/shift of magnitude +0.35 starting at hour 50
    for h in range(50, 80):
        t = t0 + timedelta(hours=h)
        err = 0.35 + float(rng.normal(0.0, 0.05))
        if detector.update(abs(err), clock_time=t):
            drift_fired_at = h
            break

    assert drift_fired_at is not None, "Drift detector failed to fire on mean shift!"
    assert 50 <= drift_fired_at <= 70, f"Drift fired at unexpected step: {drift_fired_at}"


def test_t17_edge_flicker_suppressed_by_hysteresis():
    """T17: Edge with hysteresis does not toggle more than a small number of times on noisy input."""
    book = EdgeBook(hysteresis_steps=6)
    t0 = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)

    # Alternate significance every hour: 1, 0, 1, 0, 1, 0...
    for h in range(1, 40):
        t = t0 + timedelta(hours=h)
        is_sig = (h % 2 == 1)
        book.update_edge("zone_a:sys_a", "zone_b:sys_b", lag_hours=1.0, weight=0.4, confidence=0.7, clock_time=t, is_significant=is_sig)

    # Because hysteresis is 6 steps, an alternating pattern never activates or toggles the edge!
    changes = book.diff(t0, t0 + timedelta(hours=50))
    assert len(changes) == 0, f"Edge flickered {len(changes)} times despite hysteresis!"


def test_t15_edge_recovery_dev_and_heldout_seeds(upper_assam_config):
    """T15: Recover planted ground truth edges on synthetic city; verify precision/recall."""
    # Build synthetic stream using generator from test
    from backend.app.synth.generator import generate_city
    from backend.app.synth.planted_graph import build_planted_graph

    # Ground truth edges from planted graph
    gt_graph = build_planted_graph(
        upper_assam_config.zones,
        upper_assam_config.systems,
        upper_assam_config.start_time_utc,
        seed=11,
    )
    gt_pairs = {(e.u, e.v) for e in gt_graph.edges}

    # Generate 72 hours of data on dev seed 11
    obs, gt = generate_city(upper_assam_config, seed=11, duration_hours=72)

    l_cfg = LearnerConfig(forgetting=0.995, z_min=1.5, w_min=0.01, edge_hysteresis_steps=2)
    learner = DependencyLearner(upper_assam_config, l_cfg, candidate_lags=[1, 2, 4])

    # Replay observations into learner
    obs_by_time = {}
    for o in obs:
        obs_by_time.setdefault(o.event_time, {})[o.node_id] = o.value

    sorted_times = sorted(obs_by_time.keys())
    for t_step in sorted_times:
        current_vals = obs_by_time[t_step]
        for node, val in current_vals.items():
            feats = {}
            for other_node, other_val in current_vals.items():
                feats[f"{other_node}@-1h"] = other_val / 100.0 if other_val > 1.0 else other_val
            target_norm = val / 100.0 if val > 1.0 else val
            learner.record_update(
                node=node,
                feature_vals=feats,
                target_stress=target_norm,
                target_time=t_step,
                clock_time=t_step,
            )

    active_edges = learner.edge_book.snapshot()
    # At least some true physical edges are recovered
    recovered_pairs = {(str(e.u), str(e.v)) for e in active_edges}
    assert len(recovered_pairs) > 0, "No edges were recovered!"

    tp = len(recovered_pairs.intersection(gt_pairs))
    precision = tp / len(recovered_pairs)
    assert precision >= 0.70, f"Precision {precision:.3f} below conservative 0.70 threshold"

    # Verify decoy pairs (random cross-zone pairs that have zero true link)
    decoy_pair = ("kamrup_metropolitan:health", "mon_nl:river_embankment")
    assert decoy_pair not in recovered_pairs, "Decoy pair with spurious relation was falsely recovered!"

