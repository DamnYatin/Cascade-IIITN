"""Structural evaluation: Edge recovery over time, decoy pair FPR, edge flicker, and drift latency.

Rule V1:
  - Belongs in backend/app/eval/ (may read planted graph from GroundTruth).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np

from backend.app.schemas import Edge


def evaluate_edge_recovery(
    learned_edges: List[Dict[str, Any]] | List[Edge],
    planted_edges: List[Edge],
    decoy_pairs: List[Tuple[str, str]],
) -> Dict[str, float]:
    """Compute precision, recall, F1, decoy FPR, and lag error against planted graph."""
    learned_set: Set[Tuple[str, str]] = set()
    learned_lags: Dict[Tuple[str, str], float] = {}

    for e in learned_edges:
        if isinstance(e, dict):
            u, v = str(e["u"]), str(e["v"])
            lag = float(e.get("lag_hours", 1.0))
        else:
            u, v = str(e.u), str(e.v)
            lag = float(e.lag_hours)
        learned_set.add((u, v))
        learned_lags[(u, v)] = lag

    planted_set: Set[Tuple[str, str]] = set()
    planted_lags: Dict[Tuple[str, str], float] = {}
    for pe in planted_edges:
        u, v = str(pe.u), str(pe.v)
        planted_set.add((u, v))
        planted_lags[(u, v)] = float(pe.lag_hours)

    tp_pairs = learned_set & planted_set
    fp_pairs = learned_set - planted_set
    fn_pairs = planted_set - learned_set

    tp = len(tp_pairs)
    fp = len(fp_pairs)
    fn = len(fn_pairs)

    precision = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
    recall = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
    f1 = float(2.0 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    # Decoy pair recovery rate (should be near 0.0)
    decoy_fps = sum(1 for dp in decoy_pairs if dp in learned_set or (dp[1], dp[0]) in learned_set)
    decoy_fpr = float(decoy_fps / len(decoy_pairs)) if decoy_pairs else 0.0

    # Lag errors on matched true positives
    lag_errors = [abs(learned_lags[pair] - planted_lags[pair]) for pair in tp_pairs]
    mean_lag_error = float(np.mean(lag_errors)) if lag_errors else 0.0

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "decoy_fpr": round(decoy_fpr, 4),
        "mean_lag_error": round(mean_lag_error, 2),
    }


def evaluate_drift_latency(
    drift_events: List[Dict[str, Any]],
    planted_change_hour: float = 72.0,
    max_latency_hours: float = 48.0,
    start_time_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute drift detection delay (in hours) and pre-change false drift alerts."""
    pre_change_events = []
    post_change_events = []

    for ev in drift_events:
        t_val = ev.get("time")
        h = ev.get("hour_offset")
        if h is None:
            if isinstance(t_val, str):
                try:
                    dt = datetime.fromisoformat(t_val)
                    if start_time_utc is not None:
                        h = (dt - start_time_utc).total_seconds() / 3600.0
                    else:
                        h = float(ev.get("hour", 0.0))
                except Exception:
                    h = float(ev.get("hour", 0.0))
            elif isinstance(t_val, (int, float)):
                h = float(t_val)
            else:
                h = float(ev.get("hour", 0.0))

        if h < planted_change_hour:
            pre_change_events.append(ev)
        else:
            post_change_events.append((h, ev))

    false_drifts = len(pre_change_events)

    if post_change_events:
        first_post_h, first_ev = min(post_change_events, key=lambda x: x[0])
        delay = first_post_h - planted_change_hour
        detected = (0.0 <= delay <= max_latency_hours)
    else:
        detected = False
        delay = None

    return {
        "detected": detected,
        "detection_delay_hours": round(delay, 2) if delay is not None else None,
        "false_drift_alerts_pre_change": false_drifts,
    }
