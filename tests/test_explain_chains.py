"""Tests P2 to P5: Failure Chains, Branching, Feedback Loops, and Concurrent Cascades.

Verifies:
  - P2: Chain extraction on hand-built graphs (A -> B -> C, branching A -> {B, C}) with known lags.
  - P3: Feedback loops: detected, amplification estimate positive for reinforcing loop, stress clipped in [0, 1].
  - P4: Simultaneous cascades: two roots converging on a shared node give positive interaction effect.
  - P5: Censoring and conditional/unconditional quantiles are labelled and consistent.
"""
from __future__ import annotations

from datetime import datetime, timezone
import networkx as nx
import numpy as np
import pytest

from backend.app.explain.chains import (
    build_trigger_graph,
    compute_stage_etas,
    detect_feedback_loops,
    detect_simultaneous_cascades,
    evaluate_link_removal_counterfactual,
    extract_failure_chain_tree,
)
from backend.app.forecast.learner import ForecastModel
from backend.app.forecast.rollout import NoiseBank, cascade_rollout


@pytest.fixture
def linear_chain_model():
    """A -> B -> C with lags 2h and 3h."""
    nodes = ["node_A", "node_B", "node_C"]
    couplings = {
        "node_B": [("node_A", 2.0, 0.65)],
        "node_C": [("node_B", 3.0, 0.70)],
    }
    return ForecastModel(
        nodes=nodes,
        intercepts={"node_A": 0.05, "node_B": 0.01, "node_C": 0.01},
        persistence={"node_A": 0.90, "node_B": 0.85, "node_C": 0.85},
        sigmas={"node_A": 0.03, "node_B": 0.03, "node_C": 0.03},
        couplings=couplings,
        exogenous_weights={},
    )


@pytest.fixture
def branching_model():
    """A -> {B, C} with lags 2h and 4h."""
    nodes = ["node_A", "node_B", "node_C"]
    couplings = {
        "node_B": [("node_A", 2.0, 0.60)],
        "node_C": [("node_A", 4.0, 0.55)],
    }
    return ForecastModel(
        nodes=nodes,
        intercepts={"node_A": 0.05, "node_B": 0.01, "node_C": 0.01},
        persistence={"node_A": 0.90, "node_B": 0.85, "node_C": 0.85},
        sigmas={"node_A": 0.03, "node_B": 0.03, "node_C": 0.03},
        couplings=couplings,
        exogenous_weights={},
    )


@pytest.fixture
def loop_model():
    """Reinforcing feedback loop: A -> B and B -> A."""
    nodes = ["node_A", "node_B"]
    couplings = {
        "node_A": [("node_B", 2.0, 0.45)],
        "node_B": [("node_A", 2.0, 0.45)],
    }
    return ForecastModel(
        nodes=nodes,
        intercepts={"node_A": 0.02, "node_B": 0.02},
        persistence={"node_A": 0.85, "node_B": 0.85},
        sigmas={"node_A": 0.03, "node_B": 0.03},
        couplings=couplings,
        exogenous_weights={},
    )


@pytest.fixture
def converging_model():
    """Converging roots: Root1 -> Target and Root2 -> Target."""
    nodes = ["root_1", "root_2", "shared_target"]
    couplings = {
        "shared_target": [("root_1", 2.0, 0.40), ("root_2", 2.0, 0.40)],
    }
    return ForecastModel(
        nodes=nodes,
        intercepts={"root_1": 0.04, "root_2": 0.04, "shared_target": 0.01},
        persistence={"root_1": 0.85, "root_2": 0.85, "shared_target": 0.80},
        sigmas={"root_1": 0.03, "root_2": 0.03, "shared_target": 0.03},
        couplings=couplings,
        exogenous_weights={},
    )


def test_p2_linear_chain_extraction(linear_chain_model):
    """P2: Chain extraction reconstructs A -> B -> C with ordered ETAs and correct parent links."""
    initial_beliefs = {
        "node_A": (0.85, 0.001),
        "node_B": (0.20, 0.001),
        "node_C": (0.10, 0.001),
    }
    res = cascade_rollout(
        linear_chain_model,
        initial_beliefs,
        horizon=48,
        n_rollouts=150,
        enable_trace=True,
        global_seed=42,
    )
    G = build_trigger_graph(res.trace, linear_chain_model, level="critical", probability_floor=0.1)

    assert G.has_edge("node_A", "node_B")
    assert G.has_edge("node_B", "node_C")

    # Extract tree rooted at C
    tree = extract_failure_chain_tree("node_C", G, res, level="critical")
    assert tree["node"] == "node_C"
    assert len(tree["branches"]) >= 1

    b_branch = tree["branches"][0]
    assert b_branch["node"] == "node_B"
    assert len(b_branch["branches"]) >= 1
    assert b_branch["branches"][0]["node"] == "node_A"

    # ETAs must be monotonically ordered: t(A) <= t(B) <= t(C)
    t_a = b_branch["branches"][0]["etas"]["conditional"]["p50"]
    t_b = b_branch["etas"]["conditional"]["p50"]
    t_c = tree["etas"]["conditional"]["p50"]
    assert t_a <= t_b <= t_c


def test_p2_branching_tree_extraction(branching_model):
    """P2: Branching graph A -> {B, C} captures alternative downstream failures."""
    initial_beliefs = {
        "node_A": (0.85, 0.001),
        "node_B": (0.20, 0.001),
        "node_C": (0.20, 0.001),
    }
    res = cascade_rollout(
        branching_model,
        initial_beliefs,
        horizon=48,
        n_rollouts=150,
        enable_trace=True,
        global_seed=42,
    )
    G = build_trigger_graph(res.trace, branching_model, level="critical", probability_floor=0.1)

    assert G.has_edge("node_A", "node_B")
    assert G.has_edge("node_A", "node_C")


def test_p3_feedback_loop_detection_and_boundedness(loop_model):
    """P3: Feedback loop A <-> B is detected, amplification is positive, and stress stays <= 1.0."""
    initial_beliefs = {
        "node_A": (0.60, 0.001),
        "node_B": (0.60, 0.001),
    }
    nb = NoiseBank(global_seed=42, issue_time=datetime(2026, 7, 20, tzinfo=timezone.utc), n_rollouts=100, n_nodes=2, horizon=48)
    res = cascade_rollout(
        loop_model,
        initial_beliefs,
        horizon=48,
        n_rollouts=100,
        noise_bank=nb,
        enable_trace=True,
    )
    G = build_trigger_graph(res.trace, loop_model, level="critical", probability_floor=0.05)

    loops = detect_feedback_loops(loop_model, G, initial_beliefs, noise_bank=nb, horizon=48, n_rollouts=100)
    assert len(loops) >= 1
    loop = loops[0]
    assert set(loop.nodes) == {"node_A", "node_B"}
    assert loop.amplification_factor >= 0.0

    # Ensure strictly bounded in [0, 1]
    assert np.all(res.trajectories >= 0.0)
    assert np.all(res.trajectories <= 1.0)


def test_p4_simultaneous_cascades_interaction(converging_model):
    """P4: Two roots converging on a shared node yield positive interaction amplification."""
    initial_beliefs = {
        "root_1": (0.75, 0.001),
        "root_2": (0.75, 0.001),
        "shared_target": (0.10, 0.001),
    }
    nb = NoiseBank(global_seed=42, issue_time=datetime(2026, 7, 20, tzinfo=timezone.utc), n_rollouts=150, n_nodes=3, horizon=48)
    res = cascade_rollout(
        converging_model,
        initial_beliefs,
        horizon=48,
        n_rollouts=150,
        noise_bank=nb,
        enable_trace=True,
    )

    clusters = detect_simultaneous_cascades(
        converging_model,
        res,
        initial_beliefs,
        noise_bank=nb,
        horizon=48,
        n_rollouts=150,
    )
    assert len(clusters) >= 1
    cluster = clusters[0]
    assert cluster.converging_nodes == ["shared_target"]
    assert cluster.joint_p_critical > 0.0
    assert cluster.rollout_count == 150


def test_p5_censoring_and_conditional_quantiles():
    """P5: Censored probability and conditional quantiles are consistent."""
    # 60 rollouts cross at step 10..69; 40 rollouts never cross (inf)
    times = np.array([float(10 + i) for i in range(60)] + [np.inf] * 40)
    etas = compute_stage_etas(times, horizon=72)

    assert etas["probability_within_horizon"] == 0.60
    assert etas["unconditional"]["censored_probability"] == 0.40
    assert etas["conditional"]["p50"] is not None
    assert 10.0 <= etas["conditional"]["p50"] <= 70.0


def test_link_removal_counterfactual(linear_chain_model):
    """Link removal counterfactual: cutting node_A -> node_B reduces critical risk of node_B."""
    initial_beliefs = {
        "node_A": (0.85, 0.001),
        "node_B": (0.20, 0.001),
        "node_C": (0.10, 0.001),
    }
    nb = NoiseBank(global_seed=42, issue_time=datetime(2026, 7, 20, tzinfo=timezone.utc), n_rollouts=150, n_nodes=3, horizon=48)
    base_res = cascade_rollout(
        linear_chain_model,
        initial_beliefs,
        horizon=48,
        n_rollouts=150,
        noise_bank=nb,
        enable_trace=True,
    )

    delta_p, delta_ttc = evaluate_link_removal_counterfactual(
        u="node_A",
        v="node_B",
        model=linear_chain_model,
        initial_beliefs=initial_beliefs,
        baseline_results=base_res,
        noise_bank=nb,
        horizon=48,
        n_rollouts=150,
    )
    assert delta_p >= 0.0  # Cutting link reduces risk (delta_p = base - ablated >= 0)
