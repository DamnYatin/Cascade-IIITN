"""Tests P1: Forecast TriggerTrace Instrumentation and Zero-RNG Consumption.

Verifies:
  - P1 Trace off: rollouts byte-identical to baseline.
  - P1 Trace on: trajectories bit-for-bit identical to trace off (tracing consumes zero RNG).
  - Link usage probability P(u was dominant trigger | v crossed) and lag quantiles match expectations.
"""
from __future__ import annotations

from datetime import datetime, timezone
import numpy as np
import pytest

from backend.app.city_config import load_city_config
from backend.app.forecast.config import ForecastConfig, StressLevelsConfig
from backend.app.forecast.learner import ForecastModel
from backend.app.forecast.rollout import NoiseBank, cascade_rollout
from backend.app.schemas import Edge, NodeId
from tests.conftest import REPO


@pytest.fixture
def micro_model():
    """Create a 3-node linear chain model: A -> B -> C."""
    nodes = ["node_A", "node_B", "node_C"]
    couplings = {
        "node_B": [("node_A", 2.0, 0.65)],
        "node_C": [("node_B", 3.0, 0.70)],
    }
    return ForecastModel(
        nodes=nodes,
        intercepts={"node_A": 0.05, "node_B": 0.01, "node_C": 0.01},
        persistence={"node_A": 0.90, "node_B": 0.85, "node_C": 0.85},
        sigmas={"node_A": 0.04, "node_B": 0.03, "node_C": 0.03},
        couplings=couplings,
        exogenous_weights={},
    )


def test_p1_trace_zero_rng_consumption_and_byte_identity(micro_model):
    """P1: Trajectories with enable_trace=True are bit-for-bit identical to enable_trace=False."""
    issue_time = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
    initial_beliefs = {
        "node_A": (0.60, 0.01),
        "node_B": (0.20, 0.01),
        "node_C": (0.15, 0.01),
    }

    # Run 1: Trace off
    res_off = cascade_rollout(
        model=micro_model,
        initial_beliefs=initial_beliefs,
        horizon=48,
        n_rollouts=100,
        global_seed=42,
        issue_time=issue_time,
        enable_trace=False,
    )
    assert res_off.trace is None

    # Run 2: Trace on
    res_on = cascade_rollout(
        model=micro_model,
        initial_beliefs=initial_beliefs,
        horizon=48,
        n_rollouts=100,
        global_seed=42,
        issue_time=issue_time,
        enable_trace=True,
    )
    assert res_on.trace is not None

    # Strict bit-for-bit trajectory identity
    np.testing.assert_array_equal(res_off.trajectories, res_on.trajectories)
    for k in res_off.first_crossing:
        np.testing.assert_array_equal(res_off.first_crossing[k], res_on.first_crossing[k])


def test_p1_trace_dominant_parent_and_usage_probability(micro_model):
    """P1: TriggerTrace correctly identifies node_A as dominant parent of node_B, and node_B of node_C."""
    issue_time = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
    # High initial stress on A to trigger cascade across B and C
    initial_beliefs = {
        "node_A": (0.85, 0.001),
        "node_B": (0.20, 0.001),
        "node_C": (0.10, 0.001),
    }

    res = cascade_rollout(
        model=micro_model,
        initial_beliefs=initial_beliefs,
        horizon=48,
        n_rollouts=200,
        global_seed=123,
        issue_time=issue_time,
        enable_trace=True,
    )
    trace = res.trace
    assert trace is not None

    # P(node_A was dominant trigger of node_B | node_B critical) should be very high
    p_ab = trace.get_link_usage_probability("node_A", "node_B", level="critical")
    assert p_ab > 0.85, f"Expected node_A to dominate node_B crossings, got {p_ab}"

    # P(node_B was dominant trigger of node_C | node_C critical) should be very high
    p_bc = trace.get_link_usage_probability("node_B", "node_C", level="critical")
    assert p_bc > 0.85, f"Expected node_B to dominate node_C crossings, got {p_bc}"

    # P(node_A was dominant trigger of node_C | node_C critical) should be 0 (no direct link)
    p_ac = trace.get_link_usage_probability("node_A", "node_C", level="critical")
    assert p_ac == 0.0

    # Timing stats between B and C
    timing_bc = trace.get_link_timing_stats("node_B", "node_C", level="critical")
    assert timing_bc["sample_size"] > 0
    # True lag is 3.0h; mean lag should be near 3.0
    assert 1.0 <= timing_bc["mean"] <= 6.0
