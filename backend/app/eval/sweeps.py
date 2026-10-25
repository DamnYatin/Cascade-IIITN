"""Threshold sweeps, operating-point selection, and matched-FAR baseline comparison.

Pre-registered selection rule:
  - Select (tau, k, tau_low) that maximizes POD subject to false_alarm_rate <= target_far.
  - Tie-break rule: select candidate with larger median lead time.
  - Infeasible handling: if no operating point achieves FAR <= target_far, select the
    point with minimum FAR, breaking ties with higher POD.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from backend.app.eval.alerts import AlertRun, attribute_alerts, detect_alert_runs
from backend.app.eval.events import TrueEpisode
from backend.app.eval.metrics import compute_warning_metrics


@dataclass
class SweepPoint:
    tau: float
    k: int
    tau_low: float
    pod: float
    far_per_100_zone_days: float
    far_alert_ratio: float
    lead_time_median: float
    lead_time_iqr: float
    hits: int
    misses: int
    false_alarms: int
    late_alerts: int
    lead_times: List[float] = field(default_factory=list)


def evaluate_threshold_point(
    zone_scores: Dict[str, Tuple[List[float], List[float]]],  # zone -> (scores, hours)
    zone_episodes: Dict[str, List[TrueEpisode]],
    tau: float,
    k: int,
    tau_low: float,
    k_off: int = 2,
    total_duration_hours: float = 72.0,
    h_hit: float = 72.0,
) -> SweepPoint:
    """Evaluate a single operating point (tau, k, tau_low) across all zones."""
    num_zones = len(zone_scores)
    total_zone_days = (num_zones * total_duration_hours) / 24.0

    all_hits = 0
    all_misses = 0
    all_false_alarms = 0
    all_late_alerts = 0
    all_leads: List[float] = []

    for z_id, (scores, hours) in zone_scores.items():
        episodes = zone_episodes.get(z_id, [])
        runs = detect_alert_runs(
            scores=scores,
            hours=hours,
            tau=tau,
            k=k,
            tau_low=tau_low,
            k_off=k_off,
            entity_id=z_id,
        )
        attrib = attribute_alerts(
            alert_runs=runs,
            episodes=episodes,
            h_hit=h_hit,
            entity_id=z_id,
        )
        all_hits += len(attrib.hits)
        all_false_alarms += len(attrib.false_alarms)
        all_late_alerts += len(attrib.late_alerts)
        all_misses += len(attrib.missed_episodes)
        all_leads.extend(attrib.lead_times)

    metrics = compute_warning_metrics(
        hits=all_hits,
        misses=all_misses,
        false_alarms=all_false_alarms,
        late_alerts=all_late_alerts,
        lead_times=all_leads,
        total_zone_days=total_zone_days,
    )

    return SweepPoint(
        tau=round(tau, 3),
        k=int(k),
        tau_low=round(tau_low, 3),
        pod=metrics["pod"],
        far_per_100_zone_days=metrics["far_per_100_zone_days"],
        far_alert_ratio=metrics["far_alert_ratio"],
        lead_time_median=metrics["lead_time_median"],
        lead_time_iqr=metrics["lead_time_iqr"],
        hits=metrics["hits"],
        misses=metrics["misses"],
        false_alarms=metrics["false_alarms"],
        late_alerts=metrics["late_alerts"],
        lead_times=all_leads,
    )


def select_operating_point(
    sweep_points: List[SweepPoint],
    target_far: float = 1.0,
) -> Tuple[SweepPoint, bool]:
    """Select optimal operating point adhering strictly to pre-registered rule.

    Rule:
      1. Filter points where far_per_100_zone_days <= target_far.
      2. If feasible points exist: pick max POD. Tie-break by max lead_time_median.
      3. If no points are feasible: pick min far_per_100_zone_days, tie-break by max POD.

    Returns:
        (selected_point, is_feasible)
    """
    if not sweep_points:
        raise ValueError("Cannot select operating point from empty sweep.")

    feasible = [p for p in sweep_points if not np.isnan(p.pod) and p.far_per_100_zone_days <= target_far]

    if feasible:
        # Sort by: -pod (descending), -lead_time_median (descending), far (ascending)
        best = sorted(
            feasible,
            key=lambda p: (-p.pod, -p.lead_time_median, p.far_per_100_zone_days),
        )[0]
        return best, True

    # Infeasible target: select point minimizing FAR, then maximizing POD
    fallback = sorted(
        sweep_points,
        key=lambda p: (
            p.far_per_100_zone_days,
            -p.pod if not np.isnan(p.pod) else 1.0,
            -p.lead_time_median,
        ),
    )[0]
    return fallback, False


def interpolate_matched_far(
    sweep_points: List[SweepPoint],
    target_far: float,
) -> Dict[str, float]:
    """Interpolate lead time and POD at a target FAR along the empirical sweep curve.

    Linear interpolation between adjacent sweep points sorted by FAR.
    """
    valid = [p for p in sweep_points if not np.isnan(p.pod) and not np.isnan(p.lead_time_median)]
    if not valid:
        return {"matched_far": target_far, "lead_time": 0.0, "pod": 0.0, "status": "no_data"}

    sorted_pts = sorted(valid, key=lambda p: p.far_per_100_zone_days)

    fars = np.array([p.far_per_100_zone_days for p in sorted_pts])
    leads = np.array([p.lead_time_median for p in sorted_pts])
    pods = np.array([p.pod for p in sorted_pts])

    # If target_far is outside range, clamp or nearest
    if target_far <= fars[0]:
        return {
            "matched_far": float(fars[0]),
            "lead_time": float(leads[0]),
            "pod": float(pods[0]),
            "status": "extrapolated_lower",
        }
    if target_far >= fars[-1]:
        return {
            "matched_far": float(fars[-1]),
            "lead_time": float(leads[-1]),
            "pod": float(pods[-1]),
            "status": "extrapolated_upper",
        }

    interp_lead = float(np.interp(target_far, fars, leads))
    interp_pod = float(np.interp(target_far, fars, pods))

    return {
        "matched_far": float(target_far),
        "lead_time": round(interp_lead, 2),
        "pod": round(interp_pod, 4),
        "status": "interpolated",
    }
