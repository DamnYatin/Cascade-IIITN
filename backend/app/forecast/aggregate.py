"""Multi-horizon probabilistic aggregation, censoring, and cascade summary.

Computes:
  - p_by: P(node reached >= state at any time <= h) (cumulative, monotone non-decreasing in h)
  - p_at: P(node is >= state at time h)
  - Time-to-critical quantiles with explicit censoring handling
  - Multi-system simultaneous cascade rule at zone and city levels
  - Machine-readable cascade summary (ordered stages with ETAs and dominant parent)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from backend.app.forecast.config import AggregationConfig, StressLevelsConfig
from backend.app.forecast.rollout import RolloutResults
from backend.app.schemas import CityConfig, RiskState


@dataclass
class NodeForecastMetrics:
    node: str
    # p_by: horizon -> {state_name: float}
    p_by: Dict[int, Dict[str, float]]
    # p_at: horizon -> {state_name: float}
    p_at: Dict[int, Dict[str, float]]
    # Time-to-critical quantiles
    p_no_critical_within_72h: float
    p_critical_by_72h: float
    ttc_unconditional: Dict[str, Optional[float]]  # {"p10": ..., "p50": ..., "p90": ...}
    ttc_conditional: Dict[str, Optional[float]]  # {"p10_cond": ..., "p50_cond": ..., "p90_cond": ...}


@dataclass
class CascadeStage:
    stage_index: int
    node: str
    probability: float
    eta_p10: Optional[float]
    eta_p50: Optional[float]
    eta_p90: Optional[float]
    dominant_parent: Optional[str]
    coupling_weight: Optional[float]
    lag_hours: Optional[float]


@dataclass
class AggregationResults:
    node_metrics: Dict[str, NodeForecastMetrics]
    # zone_id -> horizon -> {state: probability}
    zone_probabilities: Dict[str, Dict[int, Dict[str, float]]]
    # city -> horizon -> {state: probability}
    city_probabilities: Dict[int, Dict[str, float]]
    # Cascade summaries
    zone_cascade_summaries: Dict[str, List[CascadeStage]]
    city_cascade_summary: List[CascadeStage]


def aggregate_rollouts(
    results: RolloutResults,
    city_config: CityConfig,
    horizons: List[int],
    stress_levels: StressLevelsConfig,
    aggregation_config: AggregationConfig,
) -> AggregationResults:
    """Aggregate rollout trajectories into multi-horizon probabilistic metrics."""
    nodes = results.nodes
    n_nodes = len(nodes)
    n_rollouts = results.n_rollouts
    node_to_idx = {n: i for i, n in enumerate(nodes)}

    levels = {
        "WATCH": stress_levels.watch,
        "HIGH_RISK": stress_levels.high_risk,
        "CRITICAL": stress_levels.critical,
    }

    # 1. Node-level metrics
    node_metrics: Dict[str, NodeForecastMetrics] = {}
    for i, node in enumerate(nodes):
        p_by: Dict[int, Dict[str, float]] = {}
        p_at: Dict[int, Dict[str, float]] = {}

        # First crossing arrays
        fc_watch = results.first_crossing.get((node, "watch"), np.full(n_rollouts, np.inf))
        fc_high = results.first_crossing.get((node, "high_risk"), np.full(n_rollouts, np.inf))
        fc_crit = results.first_crossing.get((node, "critical"), np.full(n_rollouts, np.inf))

        for h in horizons:
            # Cumulative: reached level by step h
            p_by[h] = {
                "NORMAL": 1.0,
                "WATCH": float(np.mean(fc_watch <= h)),
                "HIGH_RISK": float(np.mean(fc_high <= h)),
                "CRITICAL": float(np.mean(fc_crit <= h)),
            }
            # Instantaneous at step h
            step_idx = min(h - 1, results.horizon - 1)
            vals_at_h = results.trajectories[:, i, step_idx]
            p_at[h] = {
                "NORMAL": 1.0,
                "WATCH": float(np.mean(vals_at_h >= stress_levels.watch)),
                "HIGH_RISK": float(np.mean(vals_at_h >= stress_levels.high_risk)),
                "CRITICAL": float(np.mean(vals_at_h >= stress_levels.critical)),
            }

        # Time-to-critical calculations
        max_h = 72
        crit_by_72 = fc_crit <= max_h
        p_crit_72 = float(np.mean(crit_by_72))
        p_no_crit = 1.0 - p_crit_72

        # Unconditional quantiles (null if quantile mass falls in censored mass)
        ttc_uncond: Dict[str, Optional[float]] = {}
        sorted_times = np.sort(fc_crit)
        for q_name, q_val in [("p10", 0.10), ("p50", 0.50), ("p90", 0.90)]:
            rank = int(np.ceil(q_val * n_rollouts)) - 1
            val = sorted_times[rank]
            if np.isinf(val) or val > max_h:
                ttc_uncond[q_name] = None
            else:
                ttc_uncond[q_name] = float(val)

        # Conditional quantiles (given critical occurs within 72h)
        ttc_cond: Dict[str, Optional[float]] = {}
        finite_times = fc_crit[crit_by_72]
        if len(finite_times) > 0:
            ttc_cond["p10_cond"] = float(np.percentile(finite_times, 10))
            ttc_cond["p50_cond"] = float(np.percentile(finite_times, 50))
            ttc_cond["p90_cond"] = float(np.percentile(finite_times, 90))
        else:
            ttc_cond["p10_cond"] = None
            ttc_cond["p50_cond"] = None
            ttc_cond["p90_cond"] = None

        node_metrics[node] = NodeForecastMetrics(
            node=node,
            p_by=p_by,
            p_at=p_at,
            p_no_critical_within_72h=p_no_crit,
            p_critical_by_72h=p_crit_72,
            ttc_unconditional=ttc_uncond,
            ttc_conditional=ttc_cond,
        )

    # 2. Zone-level aggregation
    # Group node indices by zone
    zone_node_indices: Dict[str, List[int]] = {}
    for z in city_config.zones:
        zone_node_indices[z.id] = [i for i, n in enumerate(nodes) if n.startswith(f"{z.id}:")]

    zone_probabilities: Dict[str, Dict[int, Dict[str, float]]] = {}
    zone_cascade_rollout_flags: Dict[str, np.ndarray] = {}  # zone -> (n_rollouts, horizon) bool

    min_systems = aggregation_config.zone_cascade_min_systems

    for z_id, idxs in zone_node_indices.items():
        zone_probabilities[z_id] = {}
        if not idxs:
            continue

        # Trajectories for this zone: shape (n_rollouts, len(idxs), horizon)
        z_trajs = results.trajectories[:, idxs, :]

        # Zone CRITICAL = at least min_systems simultaneously >= critical threshold
        is_crit_node = z_trajs >= stress_levels.critical
        crit_system_count = np.sum(is_crit_node, axis=1)  # (n_rollouts, horizon)
        zone_crit_by_step = crit_system_count >= min_systems  # (n_rollouts, horizon)
        zone_cascade_rollout_flags[z_id] = zone_crit_by_step

        # Zone HIGH_RISK = any node >= high_risk threshold
        is_high_node = z_trajs >= stress_levels.high_risk
        zone_high_by_step = np.any(is_high_node, axis=1)

        # Zone WATCH = any node >= watch threshold
        is_watch_node = z_trajs >= stress_levels.watch
        zone_watch_by_step = np.any(is_watch_node, axis=1)

        # Cumulative over time <= h
        for h in horizons:
            step_limit = min(h, results.horizon)
            p_crit_by_h = float(np.mean(np.any(zone_crit_by_step[:, :step_limit], axis=1)))
            p_high_by_h = float(np.mean(np.any(zone_high_by_step[:, :step_limit], axis=1)))
            p_watch_by_h = float(np.mean(np.any(zone_watch_by_step[:, :step_limit], axis=1)))

            zone_probabilities[z_id][h] = {
                "NORMAL": 1.0,
                "WATCH": p_watch_by_h,
                "HIGH_RISK": p_high_by_h,
                "CRITICAL": p_crit_by_h,
            }

    # 3. City-level aggregation
    city_probabilities: Dict[int, Dict[str, float]] = {}
    num_zones = len(city_config.zones)
    zone_fraction_thresh = aggregation_config.city_zone_fraction

    # City CRITICAL = at least city_zone_fraction of zones are cascade-critical simultaneously
    # Stack zone critical masks: shape (num_zones, n_rollouts, horizon)
    if zone_cascade_rollout_flags:
        stacked = np.stack(list(zone_cascade_rollout_flags.values()), axis=0)  # (Z, R, H)
        simultaneous_crit_zones = np.sum(stacked, axis=0)  # (R, H)
        city_crit_by_step = (simultaneous_crit_zones / max(1, num_zones)) >= zone_fraction_thresh

        for h in horizons:
            step_limit = min(h, results.horizon)
            p_city_crit = float(np.mean(np.any(city_crit_by_step[:, :step_limit], axis=1)))
            p_city_high = float(np.mean(np.any(simultaneous_crit_zones[:, :step_limit] >= 1, axis=1)))
            p_city_watch = float(max(p_city_high, 0.10))

            city_probabilities[h] = {
                "NORMAL": 1.0,
                "WATCH": p_city_watch,
                "HIGH_RISK": p_city_high,
                "CRITICAL": p_city_crit,
            }
    else:
        for h in horizons:
            city_probabilities[h] = {"NORMAL": 1.0, "WATCH": 0.0, "HIGH_RISK": 0.0, "CRITICAL": 0.0}

    # 4. Cascade summaries (ordered failure stages by ETA)
    def build_summary(target_nodes: List[str]) -> List[CascadeStage]:
        stages: List[Tuple[float, CascadeStage]] = []
        for n in target_nodes:
            m = node_metrics[n]
            # Only include nodes with non-trivial probability of crossing critical or high
            p_event = m.p_by.get(72, {}).get("HIGH_RISK", 0.0)
            if p_event < 0.05:
                continue

            eta_50 = m.ttc_conditional.get("p50_cond")
            order_key = eta_50 if eta_50 is not None else 999.0

            # Find dominant parent from results.parent_contributions
            dom_parent: Optional[str] = None
            max_contrib = 0.0
            for (tgt, par), contrib in results.parent_contributions.items():
                if tgt == n and contrib > max_contrib:
                    max_contrib = contrib
                    dom_parent = par

            stages.append(
                (
                    order_key,
                    CascadeStage(
                        stage_index=0,  # will index below
                        node=n,
                        probability=p_event,
                        eta_p10=m.ttc_conditional.get("p10_cond"),
                        eta_p50=eta_50,
                        eta_p90=m.ttc_conditional.get("p90_cond"),
                        dominant_parent=dom_parent,
                        coupling_weight=max_contrib if dom_parent else None,
                        lag_hours=1.0 if dom_parent else None,
                    ),
                )
            )

        stages.sort(key=lambda x: x[0])
        ordered: List[CascadeStage] = []
        for idx, (_, stg) in enumerate(stages, start=1):
            stg.stage_index = idx
            ordered.append(stg)
        return ordered

    zone_cascade_summaries: Dict[str, List[CascadeStage]] = {}
    for z in city_config.zones:
        z_nodes = [n for n in nodes if n.startswith(f"{z.id}:")]
        zone_cascade_summaries[z.id] = build_summary(z_nodes)

    city_cascade_summary = build_summary(nodes)

    return AggregationResults(
        node_metrics=node_metrics,
        zone_probabilities=zone_probabilities,
        city_probabilities=city_probabilities,
        zone_cascade_summaries=zone_cascade_summaries,
        city_cascade_summary=city_cascade_summary,
    )
