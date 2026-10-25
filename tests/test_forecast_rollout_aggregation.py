"""Phase 2 tests: Monte Carlo rollout, NoiseBank, and aggregation logic (T8 - T14).

All tests use ForecastModel.from_edges with explicit edges, independent of learning.
"""
from __future__ import annotations

from datetime import datetime, timezone
import numpy as np
import pytest

from backend.app.forecast.aggregate import aggregate_rollouts
from backend.app.forecast.config import AggregationConfig, StressLevelsConfig
from backend.app.forecast.learner import ForecastModel
from backend.app.forecast.rollout import NoiseBank, cascade_rollout
from backend.app.schemas import Edge, NodeId


@pytest.fixture
def test_clock():
    return datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)


def test_t8_noisebank_reuse_and_intervention_common_random_numbers(test_clock):
    """T8: Same NoiseBank reproduces identical rollouts; parameter intervention changes outcomes."""
    nodes = ["z1:sys_a", "z1:sys_b"]
    edges = [
        Edge(u=NodeId("z1:sys_a"), v=NodeId("z1:sys_b"), lag_hours=1.0, weight=0.5, confidence=0.8)
    ]
    model = ForecastModel.from_edges(nodes, edges)
    beliefs = {"z1:sys_a": (0.6, 0.01), "z1:sys_b": (0.2, 0.01)}

    nb1 = NoiseBank(global_seed=42, issue_time=test_clock, n_rollouts=100, n_nodes=2, horizon=24)
    nb2 = NoiseBank(global_seed=42, issue_time=test_clock, n_rollouts=100, n_nodes=2, horizon=24)

    # Run baseline twice with identical seeds
    res1 = cascade_rollout(model, beliefs, horizon=24, n_rollouts=100, noise_bank=nb1)
    res2 = cascade_rollout(model, beliefs, horizon=24, n_rollouts=100, noise_bank=nb2)

    assert np.array_equal(res1.trajectories, res2.trajectories), "Identical NoiseBank produced different rollouts!"

    # Run with intervention hook: break edge sys_a -> sys_b
    def break_edge_intervention(m: ForecastModel) -> ForecastModel:
        return ForecastModel.from_edges(m.nodes, [])

    nb3 = NoiseBank(global_seed=42, issue_time=test_clock, n_rollouts=100, n_nodes=2, horizon=24)
    res_intervened = cascade_rollout(
        model, beliefs, horizon=24, n_rollouts=100, noise_bank=nb3, intervention=break_edge_intervention
    )

    # Outcome differs because edge was cut, but common random numbers were preserved
    assert not np.array_equal(res1.trajectories, res_intervened.trajectories)
    # sys_b stress is significantly lower without the coupling from sys_a
    mean_b_baseline = np.mean(res1.trajectories[:, 1, :])
    mean_b_intervened = np.mean(res_intervened.trajectories[:, 1, :])
    assert mean_b_intervened < mean_b_baseline


def test_t9_t10_p_by_monotonicity_p_at_and_censoring(upper_assam_config, test_clock):
    """T9 & T10: p_by is non-decreasing in horizon; p_by >= p_at; censoring sum equals 1."""
    nodes = [f"{z.id}:river_embankment" for z in upper_assam_config.zones]
    model = ForecastModel.from_edges(nodes, [])
    # Moderate initial belief
    beliefs = {n: (0.35, 0.04) for n in nodes}

    res = cascade_rollout(model, beliefs, horizon=72, n_rollouts=200, global_seed=7)
    horizons = [1, 3, 6, 12, 24, 48, 72]
    agg = aggregate_rollouts(res, upper_assam_config, horizons, StressLevelsConfig(), AggregationConfig())

    for node, metrics in agg.node_metrics.items():
        prev_p_by = -1.0
        for h in horizons:
            p_by_crit = metrics.p_by[h]["CRITICAL"]
            p_at_crit = metrics.p_at[h]["CRITICAL"]

            assert 0.0 <= p_by_crit <= 1.0
            assert 0.0 <= p_at_crit <= 1.0
            # Monotone in horizon
            assert p_by_crit >= prev_p_by - 1e-6, f"p_by decreased from {prev_p_by} to {p_by_crit} at h={h}"
            prev_p_by = p_by_crit
            # p_by >= p_at
            assert p_by_crit >= p_at_crit - 1e-6, f"p_by ({p_by_crit}) < p_at ({p_at_crit}) at h={h}"

        # T10 Censoring property: p_no_critical + p_critical_by_72h == 1.0
        assert metrics.p_no_critical_within_72h + metrics.p_critical_by_72h == pytest.approx(1.0, abs=1e-5)


def test_t11_chain_first_passage_ordering(test_clock):
    """T11: Hand-built chain A -> B -> C with known lags produces ordered median first passage times."""
    nodes = ["z1:sys_a", "z1:sys_b", "z1:sys_c"]
    # Chain with 4-hour lags: A -> (4h) -> B -> (4h) -> C
    edges = [
        Edge(u=NodeId("z1:sys_a"), v=NodeId("z1:sys_b"), lag_hours=4.0, weight=0.6, confidence=0.9),
        Edge(u=NodeId("z1:sys_b"), v=NodeId("z1:sys_c"), lag_hours=4.0, weight=0.6, confidence=0.9),
    ]
    model = ForecastModel.from_edges(nodes, edges, default_persistence=0.92)
    # A starts near critical, B and C start low
    beliefs = {"z1:sys_a": (0.85, 0.01), "z1:sys_b": (0.20, 0.01), "z1:sys_c": (0.20, 0.01)}

    res = cascade_rollout(model, beliefs, horizon=48, n_rollouts=250, global_seed=42)

    # First crossing times for HIGH_RISK (0.60)
    fc_a = np.median(res.first_crossing[("z1:sys_a", "high_risk")])
    fc_b = np.median(res.first_crossing[("z1:sys_b", "high_risk")])
    fc_c = np.median(res.first_crossing[("z1:sys_c", "high_risk")])

    # A < B < C ordered first-passage times
    assert fc_a < fc_b < fc_c, f"Expected A < B < C first passage, got A={fc_a}, B={fc_b}, C={fc_c}"
    # Gaps reflect positive lag
    assert fc_b - fc_a >= 1.0
    assert fc_c - fc_b >= 1.0


def test_t12_feedback_loop_amplifies_without_divergence(test_clock):
    """T12: Two-node mutual excitation loop amplifies stress relative to uncoupled, stays in [0, 1]."""
    nodes = ["z1:sys_a", "z1:sys_b"]
    # Mutual excitation loop
    edges_loop = [
        Edge(u=NodeId("z1:sys_a"), v=NodeId("z1:sys_b"), lag_hours=1.0, weight=0.45, confidence=0.8),
        Edge(u=NodeId("z1:sys_b"), v=NodeId("z1:sys_a"), lag_hours=1.0, weight=0.45, confidence=0.8),
    ]
    model_loop = ForecastModel.from_edges(nodes, edges_loop)
    model_no_loop = ForecastModel.from_edges(nodes, [])

    beliefs = {"z1:sys_a": (0.50, 0.01), "z1:sys_b": (0.50, 0.01)}

    res_loop = cascade_rollout(model_loop, beliefs, horizon=36, n_rollouts=150, global_seed=11)
    res_no_loop = cascade_rollout(model_no_loop, beliefs, horizon=36, n_rollouts=150, global_seed=11)

    # Stays strictly within [0, 1] without divergence
    assert np.all(res_loop.trajectories >= 0.0)
    assert np.all(res_loop.trajectories <= 1.0)

    # Loop amplifies stress compared to uncoupled
    mean_loop = np.mean(res_loop.trajectories)
    mean_no_loop = np.mean(res_no_loop.trajectories)
    assert mean_loop > mean_no_loop + 0.10, f"Loop did not amplify: {mean_loop} vs {mean_no_loop}"


def test_t13_simultaneous_cascades_higher_joint_probability(test_clock):
    """T13: Two triggers in different zones produce higher joint probability at shared node than either alone."""
    nodes = ["z1:sys_a", "z2:sys_a", "z3:sys_shared"]
    edges = [
        Edge(u=NodeId("z1:sys_a"), v=NodeId("z3:sys_shared"), lag_hours=2.0, weight=0.04, confidence=0.8),
        Edge(u=NodeId("z2:sys_a"), v=NodeId("z3:sys_shared"), lag_hours=2.0, weight=0.04, confidence=0.8),
    ]
    model = ForecastModel.from_edges(nodes, edges, default_persistence=0.85)

    # Scenario 1: Only trigger 1 high
    b1 = {"z1:sys_a": (0.8, 0.001), "z2:sys_a": (0.1, 0.001), "z3:sys_shared": (0.2, 0.001)}
    r1 = cascade_rollout(model, b1, horizon=12, n_rollouts=150, global_seed=5)

    # Scenario 2: Only trigger 2 high
    b2 = {"z1:sys_a": (0.1, 0.001), "z2:sys_a": (0.8, 0.001), "z3:sys_shared": (0.2, 0.001)}
    r2 = cascade_rollout(model, b2, horizon=12, n_rollouts=150, global_seed=5)

    # Scenario 3: Both triggers high simultaneously
    b3 = {"z1:sys_a": (0.8, 0.001), "z2:sys_a": (0.8, 0.001), "z3:sys_shared": (0.2, 0.001)}
    r3 = cascade_rollout(model, b3, horizon=12, n_rollouts=150, global_seed=5)

    p_shared_1 = np.mean(r1.first_crossing[("z3:sys_shared", "watch")] <= 12)
    p_shared_2 = np.mean(r2.first_crossing[("z3:sys_shared", "watch")] <= 12)
    p_shared_joint = np.mean(r3.first_crossing[("z3:sys_shared", "watch")] <= 12)

    assert p_shared_joint > p_shared_1, f"Joint {p_shared_joint} not > Trigger 1 {p_shared_1}"
    assert p_shared_joint > p_shared_2, f"Joint {p_shared_joint} not > Trigger 2 {p_shared_2}"


def test_t14_zone_cascade_rule_requires_multiple_systems(upper_assam_config, test_clock):
    """T14: Zone CRITICAL requires >= 2 simultaneous systems at critical; 1 critical node alone does not."""
    nodes = [f"sivasagar:{s.id}" for s in upper_assam_config.systems]
    model = ForecastModel.from_edges(nodes, [], default_persistence=0.98)

    # Case A: Exactly ONE node is critical (river_embankment = 0.95), others all quiet (0.10)
    beliefs_single = {n: (0.10, 0.001) for n in nodes}
    beliefs_single["sivasagar:river_embankment"] = (0.95, 0.001)

    res_single = cascade_rollout(model, beliefs_single, horizon=12, n_rollouts=100, global_seed=42)
    agg_single = aggregate_rollouts(
        res_single, upper_assam_config, [6, 12], StressLevelsConfig(), AggregationConfig(zone_cascade_min_systems=2)
    )

    # In single node critical, zone CRITICAL probability must be ZERO because min_systems=2
    p_zone_crit_single = agg_single.zone_probabilities["sivasagar"][12]["CRITICAL"]
    assert p_zone_crit_single == 0.0, f"Single node critical triggered zone CRITICAL: {p_zone_crit_single}"

    # Case B: TWO nodes simultaneously critical
    beliefs_multi = dict(beliefs_single)
    beliefs_multi["sivasagar:transport"] = (0.95, 0.001)

    res_multi = cascade_rollout(model, beliefs_multi, horizon=12, n_rollouts=100, global_seed=42)
    agg_multi = aggregate_rollouts(
        res_multi, upper_assam_config, [6, 12], StressLevelsConfig(), AggregationConfig(zone_cascade_min_systems=2)
    )

    p_zone_crit_multi = agg_multi.zone_probabilities["sivasagar"][12]["CRITICAL"]
    assert p_zone_crit_multi > 0.80, f"Two critical nodes failed to trigger zone CRITICAL: {p_zone_crit_multi}"
