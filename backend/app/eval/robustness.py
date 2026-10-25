"""Robustness and Adversity Analysis: Fault deltas, trust ordering, and evidence quality.

Rule V1:
  - Belongs in backend/app/eval/
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import numpy as np


def compute_adversity_deltas(
    clean_metrics: Dict[str, Any],
    faulted_metrics: Dict[str, Any],
) -> Dict[str, float]:
    """Compute performance deltas between clean and faulted runs.

    Delta = Faulted - Clean (except for POD and Lead Time where Clean - Faulted shows degradation).
    """
    clean_brier = clean_metrics.get("brier", 0.0)
    fault_brier = faulted_metrics.get("brier", 0.0)

    clean_ece = clean_metrics.get("ece", 0.0)
    fault_ece = faulted_metrics.get("ece", 0.0)

    clean_lead = clean_metrics.get("lead_time_median", 0.0)
    fault_lead = faulted_metrics.get("lead_time_median", 0.0)

    clean_pod = clean_metrics.get("pod", 0.0)
    fault_pod = faulted_metrics.get("pod", 0.0)

    clean_far = clean_metrics.get("far_per_100_zone_days", 0.0)
    fault_far = faulted_metrics.get("far_per_100_zone_days", 0.0)

    return {
        "delta_brier": round(float(fault_brier - clean_brier), 4),
        "delta_ece": round(float(fault_ece - clean_ece), 4),
        "delta_lead_time": round(float(fault_lead - clean_lead), 2),
        "delta_pod": round(float(fault_pod - clean_pod), 4),
        "delta_far_per_100_zone_days": round(float(fault_far - clean_far), 3),
    }


def evaluate_trust_ordering(
    source_trust_map: Dict[str, float],
    faulty_source: str,
) -> Dict[str, Any]:
    """Evaluate whether the faulty source is successfully ranked lowest among sources."""
    if not source_trust_map:
        return {"ranked_lowest": False, "faulty_rank": 0, "total_sources": 0}

    # Sort sources by trust ascending: lowest trust first
    sorted_sources = sorted(source_trust_map.items(), key=lambda kv: kv[1])
    ranked_names = [k for k, v in sorted_sources]

    total = len(ranked_names)
    rank = ranked_names.index(faulty_source) + 1 if faulty_source in ranked_names else total
    lowest = (rank == 1)

    return {
        "ranked_lowest": lowest,
        "faulty_rank": rank,
        "total_sources": total,
        "faulty_trust": round(source_trust_map.get(faulty_source, 1.0), 4),
        "mean_peer_trust": round(float(np.mean([v for k, v in source_trust_map.items() if k != faulty_source])), 4) if total > 1 else 1.0,
    }


def evaluate_evidence_quality_bins(
    evidence_qualities: List[float],
    actual_errors: List[float],
    interval_covers: List[bool],
    n_bins: int = 4,
) -> List[Dict[str, Any]]:
    """Compute error spread and predictive interval coverage across evidence quality bins."""
    eq_arr = np.asarray(evidence_qualities, dtype=float)
    err_arr = np.asarray(actual_errors, dtype=float)
    cov_arr = np.asarray(interval_covers, dtype=bool)

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_idx = np.digitize(eq_arr, bin_edges) - 1
    bin_idx = np.clip(bin_idx, 0, n_bins - 1)

    bin_records = []
    for b in range(n_bins):
        mask = bin_idx == b
        count = int(np.sum(mask))
        if count > 0:
            mean_eq = float(np.mean(eq_arr[mask]))
            mae = float(np.mean(err_arr[mask]))
            cov = float(np.mean(cov_arr[mask]))
        else:
            mean_eq = (bin_edges[b] + bin_edges[b + 1]) / 2.0
            mae = 0.0
            cov = 0.0

        bin_records.append(
            {
                "bin_index": b,
                "eq_min": round(float(bin_edges[b]), 2),
                "eq_max": round(float(bin_edges[b + 1]), 2),
                "count": count,
                "mean_eq": round(mean_eq, 3),
                "mean_error": round(mae, 3),
                "interval_coverage": round(cov, 4),
            }
        )

    return bin_records
