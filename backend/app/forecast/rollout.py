"""Vectorised Monte Carlo cascade engine with Common Random Numbers (NoiseBank).

Features:
  - Vectorised over rollouts and nodes with NumPy.
  - Ring buffer per rollout for historical lags.
  - Strict clipping to [0, 1] prevents divergence in feedback loops.
  - Deterministic common random numbers via SeedSequence(global_seed, issue_time).
  - Intervention hook for counterfactual simulation (Phase 3 ready).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np

from backend.app.forecast.config import StressLevelsConfig
from backend.app.forecast.learner import ForecastModel
from backend.app.forecast.trace import TriggerTrace


class NoiseBank:
    """Pre-generates and manages deterministic common random numbers for rollouts."""

    def __init__(
        self,
        global_seed: int,
        issue_time: datetime,
        n_rollouts: int,
        n_nodes: int,
        horizon: int,
    ):
        self.global_seed = global_seed
        self.issue_time = issue_time
        self.n_rollouts = n_rollouts
        self.n_nodes = n_nodes
        self.horizon = horizon

        time_key = int(issue_time.timestamp()) & 0x7FFFFFFF
        self.seed_seq = np.random.SeedSequence([int(global_seed), time_key])
        children = self.seed_seq.spawn(3)

        self.init_rng = np.random.default_rng(children[0])
        self.step_rng = np.random.default_rng(children[1])
        self.outlook_rng = np.random.default_rng(children[2])

        # Pre-generate standard normal noise for initial perturbations: (n_rollouts, n_nodes)
        self.init_noise = self.init_rng.standard_normal(size=(n_rollouts, n_nodes))
        # Pre-generate process noise: (horizon, n_rollouts, n_nodes)
        self.process_noise = self.step_rng.standard_normal(size=(horizon, n_rollouts, n_nodes))


@dataclass
class RolloutResults:
    nodes: List[str]
    horizon: int
    n_rollouts: int
    # trajectories: shape (n_rollouts, n_nodes, horizon)
    trajectories: np.ndarray
    # first_crossing: (node, level_name) -> array of shape (n_rollouts,) with int step or inf
    first_crossing: Dict[Tuple[str, str], np.ndarray]
    # parent_contributions: (node, parent) -> float average contribution across rollouts
    parent_contributions: Dict[Tuple[str, str], float] = field(default_factory=dict)
    # Additive TriggerTrace (None if enable_trace=False)
    trace: Optional[TriggerTrace] = field(default=None)


def cascade_rollout(
    model: ForecastModel,
    initial_beliefs: Dict[str, Tuple[float, float]],  # node -> (mean, variance)
    horizon: int = 72,
    n_rollouts: int = 300,
    noise_bank: Optional[NoiseBank] = None,
    global_seed: int = 42,
    issue_time: Optional[datetime] = None,
    stress_levels: Optional[StressLevelsConfig] = None,
    rain_outlook_by_zone: Optional[Dict[str, np.ndarray]] = None,  # zone -> (n_rollouts, horizon)
    intervention: Optional[Callable[[ForecastModel], ForecastModel]] = None,
    enable_trace: bool = False,
    patches: Optional[List[Any]] = None,
) -> RolloutResults:
    """Run vectorised Monte Carlo rollouts across nodes and time steps."""
    if issue_time is None:
        issue_time = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
    if stress_levels is None:
        stress_levels = StressLevelsConfig()

    # Apply intervention hook if provided
    active_model = intervention(model) if intervention is not None else model

    nodes = active_model.nodes
    n_nodes = len(nodes)
    node_to_idx = {n: i for i, n in enumerate(nodes)}

    if noise_bank is None:
        noise_bank = NoiseBank(
            global_seed=global_seed,
            issue_time=issue_time,
            n_rollouts=n_rollouts,
            n_nodes=n_nodes,
            horizon=horizon,
        )
    else:
        n_rollouts = min(n_rollouts, noise_bank.n_rollouts)

    # Max lag needed for ring buffer
    max_lag = 1
    for parents in active_model.couplings.values():
        for _, lag, _ in parents:
            max_lag = max(max_lag, int(np.ceil(lag)))

    # Initial state perturbation: s_0 ~ N(mean, var) clipped to [0, 1]
    # ring_buffer shape: (max_lag + 1, n_rollouts, n_nodes)
    # Index 0 corresponds to t=0 (current belief s0).
    # Indices 1..max_lag correspond to past historical steps t < 0 (resting baseline 0.15).
    ring_buffer = np.full((max_lag + 1, n_rollouts, n_nodes), 0.15, dtype=np.float64)
    for i, n in enumerate(nodes):
        m, var = initial_beliefs.get(n, (0.15, 0.04))
        std = float(np.sqrt(max(1e-6, var)))
        pert = m + std * noise_bank.init_noise[:n_rollouts, i]
        s0 = np.clip(pert, 0.0, 1.0)
        ring_buffer[0, :, i] = s0

    # Output storage
    trajectories = np.zeros((n_rollouts, n_nodes, horizon), dtype=np.float64)

    # First crossing trackers: shape (n_rollouts,) per (node, level)
    levels = {
        "watch": stress_levels.watch,
        "high_risk": stress_levels.high_risk,
        "critical": stress_levels.critical,
    }
    first_crossing: Dict[Tuple[str, str], np.ndarray] = {
        (n, lvl): np.full(n_rollouts, np.inf, dtype=np.float64)
        for n in nodes
        for lvl in levels
    }

    # Instantiate trigger trace if enabled (default False)
    trace = TriggerTrace(
        nodes=nodes,
        levels=list(levels.keys()),
        n_rollouts=n_rollouts,
        horizon=horizon,
    ) if enable_trace else None

    # Track parent contributions to crossing
    parent_accumulators: Dict[Tuple[str, str], float] = defaultdict(float)
    crossing_counts: Dict[str, int] = defaultdict(int)

    # Pre-extract vectorised model parameters
    a = np.array([active_model.intercepts.get(n, 0.02) for n in nodes], dtype=np.float64)
    rho = np.array([active_model.persistence.get(n, 0.85) for n in nodes], dtype=np.float64)
    sigmas = np.array([active_model.sigmas.get(n, 0.05) for n in nodes], dtype=np.float64)

    # Time loop
    buffer_idx = 0
    for h in range(horizon):
        step_idx = (buffer_idx + 1) % (max_lag + 1)
        prev_idx = buffer_idx % (max_lag + 1)

        # Baseline autoregressive update: (n_rollouts, n_nodes)
        s_prev = ring_buffer[prev_idx]
        s_next = a + rho * s_prev

        # Add process noise
        eps = noise_bank.process_noise[h][:n_rollouts, :] * sigmas
        s_next += eps

        # Add coupling effects from parents
        for target_node, parents in active_model.couplings.items():
            t_idx = node_to_idx[target_node]
            for parent_node, lag_h, w in parents:
                if parent_node in node_to_idx:
                    p_idx = node_to_idx[parent_node]
                    lag_steps = int(round(lag_h))
                    lookup_idx = (buffer_idx + 1 - lag_steps) % (max_lag + 1)
                    parent_val = ring_buffer[lookup_idx, :, p_idx]
                    coupling_term = w * parent_val
                    s_next[:, t_idx] += coupling_term

                    # Accumulate for dominant parent tracking
                    parent_accumulators[(target_node, parent_node)] += float(np.mean(np.maximum(0.0, coupling_term)))

        # Add exogenous rain effects if available
        for target_node, exo_list in active_model.exogenous_weights.items():
            t_idx = node_to_idx[target_node]
            zone = target_node.split(":")[0]
            if rain_outlook_by_zone and zone in rain_outlook_by_zone:
                rain_vals = rain_outlook_by_zone[zone][:n_rollouts, h]  # (n_rollouts,)
                for feat_name, beta in exo_list:
                    if "rain" in feat_name:
                        s_next[:, t_idx] += beta * (rain_vals / 100.0)

        # Apply dynamic parameter patches if scheduled
        if patches:
            from backend.app.intervene.patches import apply_step_patches
            s_next = apply_step_patches(
                s_next=s_next,
                ring_buffer=ring_buffer,
                h=h,
                buffer_idx=buffer_idx,
                max_lag=max_lag,
                patches=patches,
                node_to_idx=node_to_idx,
                n_rollouts=n_rollouts,
            )

        # Clip to [0, 1] to prevent divergence
        s_next = np.clip(s_next, 0.0, 1.0)
        ring_buffer[step_idx] = s_next
        trajectories[:, :, h] = s_next

        # Check threshold crossings
        step_num = float(h + 1)
        for i, n in enumerate(nodes):
            val_col = s_next[:, i]
            newly_crossed_by_lvl = {}
            for lvl_name, thresh in levels.items():
                crossed = (val_col >= thresh) & (first_crossing[(n, lvl_name)] == np.inf)
                if np.any(crossed):
                    newly_crossed_by_lvl[lvl_name] = crossed

            if newly_crossed_by_lvl:
                if trace is not None:
                    # Trigger terms: each lagged parent term, rain/soil feature terms, bias, noise
                    term_names = ["bias", "noise"]
                    term_cols = [
                        np.full(n_rollouts, a[i], dtype=np.float32),
                        eps[:, i].astype(np.float32),
                    ]
                    if n in active_model.couplings:
                        for parent_node, lag_h, w in active_model.couplings[n]:
                            if parent_node in node_to_idx:
                                p_idx = node_to_idx[parent_node]
                                lag_steps = int(round(lag_h))
                                lookup_idx = (buffer_idx + 1 - lag_steps) % (max_lag + 1)
                                p_val = ring_buffer[lookup_idx, :, p_idx]
                                term_names.append(f"parent:{parent_node}")
                                term_cols.append((w * p_val).astype(np.float32))

                    if n in active_model.exogenous_weights:
                        zone = n.split(":")[0]
                        if rain_outlook_by_zone and zone in rain_outlook_by_zone:
                            rain_vals = rain_outlook_by_zone[zone][:n_rollouts, h]
                            for feat_name, beta in active_model.exogenous_weights[n]:
                                if "rain" in feat_name:
                                    term_names.append(f"rain:{feat_name}")
                                    term_cols.append((beta * (rain_vals / 100.0)).astype(np.float32))

                    term_matrix = np.column_stack(term_cols)
                    for lvl_name, crossed in newly_crossed_by_lvl.items():
                        trace.record_step_crossings(n, lvl_name, int(step_num), crossed, term_names, term_matrix)

                for lvl_name, crossed in newly_crossed_by_lvl.items():
                    first_crossing[(n, lvl_name)][crossed] = step_num
                    if lvl_name == "critical":
                        crossing_counts[n] += int(np.sum(crossed))

        buffer_idx += 1

    return RolloutResults(
        nodes=nodes,
        horizon=horizon,
        n_rollouts=n_rollouts,
        trajectories=trajectories,
        first_crossing=first_crossing,
        parent_contributions=dict(parent_accumulators),
        trace=trace,
    )
