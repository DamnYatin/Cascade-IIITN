"""TriggerTrace: Path-level causal trigger attribution inside Monte Carlo rollouts.

Records:
  - Exact time step t when node first crosses each stress level (watch, high_risk, critical).
  - Per-term contributions to stress update at crossing step:
    each lagged parent term, rain/soil feature terms, baseline bias, noise.
  - Dominant contributor (largest positive contribution).
  - Efficient array-backed storage with bounded memory.
  - Zero RNG consumption (trajectories identical with or without tracing).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import numpy as np


@dataclass
class TriggerTrace:
    """Compact recorder of first-crossing trigger attribution across rollouts."""
    nodes: List[str]
    levels: List[str]
    n_rollouts: int
    horizon: int

    # (node_idx, level_idx, rollout_idx) -> step number (or -1 if no crossing)
    # Shape: (n_nodes, n_levels, n_rollouts), dtype=np.int16
    crossing_steps: np.ndarray = field(init=False)

    # Dominant contributor term name for each (node_idx, level_idx, rollout_idx)
    # Dict: (node_name, level_name) -> list of length n_rollouts of str (empty if not crossed)
    dominant_terms: Dict[Tuple[str, str], List[Optional[str]]] = field(init=False)

    # Dominant parent node name (None if dominant was rain, bias, or noise)
    # Dict: (node_name, level_name) -> list of length n_rollouts of Optional[str]
    dominant_parents: Dict[Tuple[str, str], List[Optional[str]]] = field(init=False)

    # Dominant contribution value: (n_nodes, n_levels, n_rollouts), dtype=np.float32
    dominant_values: np.ndarray = field(init=False)

    def __post_init__(self):
        n_n = len(self.nodes)
        n_l = len(self.levels)
        self.node_to_idx = {n: i for i, n in enumerate(self.nodes)}
        self.level_to_idx = {lvl: i for i, lvl in enumerate(self.levels)}

        self.crossing_steps = np.full((n_n, n_l, self.n_rollouts), -1, dtype=np.int16)
        self.dominant_values = np.zeros((n_n, n_l, self.n_rollouts), dtype=np.float32)

        self.dominant_terms = {
            (n, lvl): [None] * self.n_rollouts
            for n in self.nodes
            for lvl in self.levels
        }
        self.dominant_parents = {
            (n, lvl): [None] * self.n_rollouts
            for n in self.nodes
            for lvl in self.levels
        }

    def record_step_crossings(
        self,
        node_name: str,
        level_name: str,
        step: int,
        crossed_mask: np.ndarray,  # boolean array of shape (n_rollouts,)
        term_names: List[str],      # e.g. ['bias', 'persistence', 'noise', 'parent:u', 'rain']
        term_matrix: np.ndarray,    # shape (n_rollouts, len(term_names))
    ) -> None:
        """Record dominant contributor for rollouts newly crossing at this step."""
        if not np.any(crossed_mask):
            return

        n_idx = self.node_to_idx[node_name]
        l_idx = self.level_to_idx[level_name]

        # Extract rows for crossing rollouts
        crossing_r_indices = np.where(crossed_mask)[0]
        self.crossing_steps[n_idx, l_idx, crossing_r_indices] = int(step)

        sub_matrix = term_matrix[crossing_r_indices]  # (K, num_terms)
        best_term_indices = np.argmax(sub_matrix, axis=1)  # (K,)

        dom_terms_list = self.dominant_terms[(node_name, level_name)]
        dom_parents_list = self.dominant_parents[(node_name, level_name)]

        for k_idx, r_idx in enumerate(crossing_r_indices):
            best_t_idx = int(best_term_indices[k_idx])
            best_term_name = term_names[best_t_idx]
            val = float(sub_matrix[k_idx, best_t_idx])

            self.dominant_values[n_idx, l_idx, r_idx] = val
            dom_terms_list[r_idx] = best_term_name

            if best_term_name.startswith("parent:"):
                p_name = best_term_name.split("parent:", 1)[1]
                dom_parents_list[r_idx] = p_name
            else:
                dom_parents_list[r_idx] = None

    def get_link_usage_probability(
        self,
        u: str,
        v: str,
        level: str = "critical",
    ) -> float:
        """Compute P(u was v's dominant trigger | v crossed level)."""
        if v not in self.node_to_idx or level not in self.level_to_idx:
            return 0.0

        v_idx = self.node_to_idx[v]
        l_idx = self.level_to_idx[level]
        crossed_mask = self.crossing_steps[v_idx, l_idx] >= 0
        total_crossings = int(np.sum(crossed_mask))
        if total_crossings == 0:
            return 0.0

        dom_parents = self.dominant_parents[(v, level)]
        u_count = sum(1 for r_idx in np.where(crossed_mask)[0] if dom_parents[r_idx] == u)
        return float(u_count / total_crossings)

    def get_link_timing_stats(
        self,
        u: str,
        v: str,
        level: str = "critical",
    ) -> Dict[str, float]:
        """Compute lag quantiles (p10, p50, p90) between u crossing and v crossing."""
        if u not in self.node_to_idx or v not in self.node_to_idx or level not in self.level_to_idx:
            return {"p10": 0.0, "p50": 0.0, "p90": 0.0, "mean": 0.0, "sample_size": 0}

        u_idx = self.node_to_idx[u]
        v_idx = self.node_to_idx[v]
        l_idx = self.level_to_idx[level]

        u_steps = self.crossing_steps[u_idx, l_idx]
        v_steps = self.crossing_steps[v_idx, l_idx]
        dom_parents = self.dominant_parents[(v, level)]

        # Rollouts where v crossed and u was its dominant parent
        valid_r = [
            r for r in range(self.n_rollouts)
            if v_steps[r] >= 0 and dom_parents[r] == u
        ]
        if not valid_r:
            return {"p10": 0.0, "p50": 0.0, "p90": 0.0, "mean": 0.0, "sample_size": 0}

        lags = []
        for r in valid_r:
            u_t = u_steps[r]
            v_t = v_steps[r]
            # If u crossed before or at v, lag is v_t - u_t; else 1.0 step fallback
            lag = max(1.0, float(v_t - u_t)) if u_t >= 0 else 1.0
            lags.append(lag)

        lags_arr = np.array(lags, dtype=np.float64)
        return {
            "p10": float(np.percentile(lags_arr, 10)),
            "p50": float(np.percentile(lags_arr, 50)),
            "p90": float(np.percentile(lags_arr, 90)),
            "mean": float(np.mean(lags_arr)),
            "sample_size": len(lags),
        }
