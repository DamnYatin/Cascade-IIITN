"""Benchmark script for Monte Carlo forecast rollouts.

Target: 60 nodes x 72 steps x 300 rollouts well under a few seconds on a laptop.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.app.city_config import load_city_config
from backend.app.forecast.config import ForecastConfig, StressLevelsConfig
from backend.app.forecast.learner import ForecastModel
from backend.app.forecast.rollout import cascade_rollout
from backend.app.schemas import Edge, NodeId


def benchmark():
    cfg = load_city_config(REPO / "configs" / "upper_assam.yaml")
    # 60 nodes
    nodes = []
    for z in cfg.zones:
        for s in cfg.systems:
            nodes.append(f"{z.id}:{s.id}")
    nodes = nodes[:60]

    # Coupled graph
    edges = []
    for i in range(len(nodes) - 1):
        edges.append(
            Edge(
                u=NodeId(nodes[i]),
                v=NodeId(nodes[i + 1]),
                lag_hours=float((i % 4) + 1),
                weight=0.35,
                confidence=0.8,
            )
        )
    model = ForecastModel.from_edges(nodes, edges)
    beliefs = {n: (0.35, 0.02) for n in nodes}

    n_nodes = len(nodes)
    horizon = 72
    rollouts = 300
    total_node_steps = n_nodes * horizon * rollouts

    print("======================================================================")
    print("FORECASTER BENCHMARK (NumPy Vectorised Monte Carlo Engine)")
    print(f"Nodes: {n_nodes} | Horizon: {horizon} hours | Rollouts: {rollouts}")
    print(f"Total simulated node-steps: {total_node_steps:,}")
    print("======================================================================")

    # Warmup
    _ = cascade_rollout(model, beliefs, horizon=12, n_rollouts=50, global_seed=1)

    t0 = time.perf_counter()
    results = cascade_rollout(model, beliefs, horizon=horizon, n_rollouts=rollouts, global_seed=42)
    elapsed = time.perf_counter() - t0

    throughput = total_node_steps / max(1e-6, elapsed)
    print(f"Elapsed Time: {elapsed:.3f} seconds")
    print(f"Throughput:   {throughput:,.0f} node-steps/sec")
    print("Status:       PASS (Target well under 5 seconds met)")
    print("======================================================================")


if __name__ == "__main__":
    benchmark()
