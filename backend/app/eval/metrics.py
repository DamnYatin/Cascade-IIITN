"""Evaluation metrics, reliability bins, warning statistics, and bootstrap confidence intervals.

Implements all metrics specified in Playbook Sections 4, 9, and Phase 3 spec:
  - Brier score, Brier Skill Score (BSS) against causal climatology, Murphy decomposition
  - Expected Calibration Error (ECE) and reliability diagram bins with Wilson score intervals
  - Sharpness distribution
  - Lead time statistics (median, IQR, fraction >= 6h, 12h, 24h)
  - POD (Probability of Detection), Misses, Late alerts
  - False-Alarm Rate (FAR per 100 zone-days and as fraction of alerts)
  - Time-to-critical error and interval coverage ([p10, p90])
  - Seed-blocked bootstrap confidence intervals (deterministic with fixed seed)
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np


def brier_score(y_prob: List[float] | np.ndarray, y_true: List[int | bool] | np.ndarray) -> float:
    """Compute Brier score: mean squared error of predicted probabilities."""
    p = np.asarray(y_prob, dtype=float)
    y = np.asarray(y_true, dtype=float)
    if len(p) == 0:
        return 0.0
    return float(np.mean((p - y) ** 2))


def brier_skill_score(
    y_prob: List[float] | np.ndarray,
    y_true: List[int | bool] | np.ndarray,
    ref_brier: Optional[float] = None,
) -> float:
    """Compute Brier Skill Score (BSS) against reference (default: sample climatology).

    BSS = 1 - (BS / BS_ref)
    """
    p = np.asarray(y_prob, dtype=float)
    y = np.asarray(y_true, dtype=float)
    if len(p) == 0:
        return 0.0

    bs = brier_score(p, y)
    if ref_brier is None:
        p_base = float(np.mean(y))
        ref_brier = float(np.mean((p_base - y) ** 2))

    if ref_brier <= 1e-12:
        return 1.0 if bs <= 1e-12 else 0.0

    return float(1.0 - (bs / ref_brier))


def brier_decomposition(
    y_prob: List[float] | np.ndarray,
    y_true: List[int | bool] | np.ndarray,
    n_bins: int = 10,
) -> Dict[str, float]:
    """Murphy decomposition of Brier score: BS = Reliability - Resolution + Uncertainty."""
    p = np.asarray(y_prob, dtype=float)
    y = np.asarray(y_true, dtype=float)
    n = len(p)
    if n == 0:
        return {"brier": 0.0, "reliability": 0.0, "resolution": 0.0, "uncertainty": 0.0}

    y_bar = float(np.mean(y))
    uncertainty = y_bar * (1.0 - y_bar)

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_idx = np.digitize(p, bin_edges) - 1
    bin_idx = np.clip(bin_idx, 0, n_bins - 1)

    reliability = 0.0
    resolution = 0.0

    for b in range(n_bins):
        mask = bin_idx == b
        count = int(np.sum(mask))
        if count > 0:
            p_k = float(np.mean(p[mask]))
            y_k = float(np.mean(y[mask]))
            w = count / float(n)
            reliability += w * ((p_k - y_k) ** 2)
            resolution += w * ((y_k - y_bar) ** 2)

    bs = reliability - resolution + uncertainty
    return {
        "brier": float(bs),
        "reliability": float(reliability),
        "resolution": float(resolution),
        "uncertainty": float(uncertainty),
    }


def wilson_score_interval(k: int, n: int, confidence: float = 0.95) -> Tuple[float, float]:
    """Compute Wilson score interval for binomial proportion."""
    if n <= 0:
        return (0.0, 1.0)
    # Z-value for confidence (default 1.96 for 95%)
    z = 1.95996 if abs(confidence - 0.95) < 0.01 else 1.64485
    p_hat = float(k) / float(n)
    denom = 1.0 + (z**2) / float(n)
    center = (p_hat + (z**2) / (2.0 * float(n))) / denom
    spread = (z / denom) * math.sqrt(max(0.0, (p_hat * (1.0 - p_hat) / float(n)) + ((z**2) / (4.0 * float(n) ** 2))))
    return (max(0.0, center - spread), min(1.0, center + spread))


def compute_reliability_bins(
    y_prob: List[float] | np.ndarray,
    y_true: List[int | bool] | np.ndarray,
    n_bins: int = 10,
    equal_frequency: bool = False,
) -> Tuple[float, List[Dict[str, Any]]]:
    """Compute Expected Calibration Error (ECE) and reliability diagram bin records.

    Returns:
        (ece, bin_records)
    """
    p = np.asarray(y_prob, dtype=float)
    y = np.asarray(y_true, dtype=float)
    n = len(p)
    if n == 0:
        return 0.0, []

    if equal_frequency and n >= n_bins:
        quantiles = np.linspace(0.0, 1.0, n_bins + 1)
        bin_edges = np.percentile(p, quantiles * 100.0)
        bin_edges[0] = 0.0
        bin_edges[-1] = 1.0
        # Deduplicate edges if distribution has ties
        unique_edges = np.unique(bin_edges)
        if len(unique_edges) > 2:
            bin_edges = unique_edges
            n_bins = len(bin_edges) - 1
        else:
            bin_edges = np.linspace(0.0, 1.0, 11)
            n_bins = 10
    else:
        bin_edges = np.linspace(0.0, 1.0, n_bins + 1)

    bin_idx = np.digitize(p, bin_edges) - 1
    bin_idx = np.clip(bin_idx, 0, n_bins - 1)

    bin_records: List[Dict[str, Any]] = []
    ece = 0.0

    for b in range(n_bins):
        mask = bin_idx == b
        count = int(np.sum(mask))
        b_min = float(bin_edges[b])
        b_max = float(bin_edges[b + 1])

        if count > 0:
            pred_mean = float(np.mean(p[mask]))
            obs_freq = float(np.mean(y[mask]))
            hits_count = int(np.sum(y[mask]))
            ci_low, ci_high = wilson_score_interval(hits_count, count)
            gap = abs(pred_mean - obs_freq)
            ece += (count / float(n)) * gap
        else:
            pred_mean = (b_min + b_max) / 2.0
            obs_freq = 0.0
            ci_low, ci_high = (0.0, 0.0)
            gap = 0.0

        bin_records.append(
            {
                "bin_index": b,
                "bin_min": round(b_min, 4),
                "bin_max": round(b_max, 4),
                "count": count,
                "pred_mean": round(pred_mean, 4),
                "obs_freq": round(obs_freq, 4),
                "ci_low": round(ci_low, 4),
                "ci_high": round(ci_high, 4),
                "gap": round(gap, 4),
            }
        )

    return float(ece), bin_records


def compute_sharpness_histogram(
    y_prob: List[float] | np.ndarray,
    n_bins: int = 10,
) -> List[Dict[str, Any]]:
    """Compute histogram of forecast probabilities to reveal sharpness."""
    p = np.asarray(y_prob, dtype=float)
    n = len(p)
    if n == 0:
        return []

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    counts, _ = np.histogram(p, bins=bin_edges)

    hist: List[Dict[str, Any]] = []
    for b in range(n_bins):
        cnt = int(counts[b])
        frac = cnt / float(n) if n > 0 else 0.0
        hist.append(
            {
                "bin_min": round(float(bin_edges[b]), 3),
                "bin_max": round(float(bin_edges[b + 1]), 3),
                "count": cnt,
                "fraction": round(frac, 4),
            }
        )
    return hist


def compute_warning_metrics(
    hits: int,
    misses: int,
    false_alarms: int,
    late_alerts: int,
    lead_times: List[float],
    total_zone_days: float,
) -> Dict[str, Any]:
    """Compute warning metrics: lead times, POD, FAR per 100 zone-days, and alert FAR.

    Args:
        hits: Count of successfully warned episodes.
        misses: Count of true episodes never warned.
        false_alarms: Count of alert runs with no qualifying episode.
        late_alerts: Count of alert runs that began after episode onset.
        lead_times: List of lead time hours for hit episodes.
        total_zone_days: (num_zones * duration_hours) / 24.0.
    """
    total_episodes = hits + misses
    pod = float(hits / total_episodes) if total_episodes > 0 else float("nan")

    total_alert_runs = hits + false_alarms + late_alerts
    far_alert_ratio = float(false_alarms / total_alert_runs) if total_alert_runs > 0 else 0.0

    far_per_100_zone_days = (
        float((false_alarms / total_zone_days) * 100.0) if total_zone_days > 0 else 0.0
    )

    lead_arr = np.asarray(lead_times, dtype=float)
    if len(lead_arr) > 0:
        med_lead = float(np.median(lead_arr))
        p25 = float(np.percentile(lead_arr, 25))
        p75 = float(np.percentile(lead_arr, 75))
        iqr_lead = float(p75 - p25)
        mean_lead = float(np.mean(lead_arr))
        frac_6h = float(np.mean(lead_arr >= 6.0))
        frac_12h = float(np.mean(lead_arr >= 12.0))
        frac_24h = float(np.mean(lead_arr >= 24.0))
    else:
        med_lead = 0.0
        p25 = 0.0
        p75 = 0.0
        iqr_lead = 0.0
        mean_lead = 0.0
        frac_6h = 0.0
        frac_12h = 0.0
        frac_24h = 0.0

    return {
        "hits": hits,
        "misses": misses,
        "false_alarms": false_alarms,
        "late_alerts": late_alerts,
        "total_episodes": total_episodes,
        "total_alert_runs": total_alert_runs,
        "pod": pod,
        "far_per_100_zone_days": round(far_per_100_zone_days, 3),
        "far_alert_ratio": round(far_alert_ratio, 4),
        "lead_time_median": round(med_lead, 2),
        "lead_time_iqr": round(iqr_lead, 2),
        "lead_time_mean": round(mean_lead, 2),
        "lead_frac_ge_6h": round(frac_6h, 4),
        "lead_frac_ge_12h": round(frac_12h, 4),
        "lead_frac_ge_24h": round(frac_24h, 4),
        "lead_times": [round(float(x), 2) for x in lead_arr],
    }


def compute_time_to_critical_metrics(
    actual_ttcs: List[float],
    pred_median_ttcs: List[Optional[float]],
    pred_p10_ttcs: List[Optional[float]],
    pred_p90_ttcs: List[Optional[float]],
    max_horizon: float = 72.0,
) -> Dict[str, Any]:
    """Compute conditional Time-to-Critical error and interval coverage for occurring events."""
    n = len(actual_ttcs)
    if n == 0:
        return {
            "n_occurring": 0,
            "hard_misses": 0,
            "hard_miss_rate": 0.0,
            "mae_median_ttc": 0.0,
            "median_error_ttc": 0.0,
            "coverage_p10_p90": 0.0,
        }

    errors: List[float] = []
    covered: List[bool] = []
    hard_misses = 0

    for act, p_med, p10, p90 in zip(actual_ttcs, pred_median_ttcs, pred_p10_ttcs, pred_p90_ttcs):
        if p_med is None or p_med > max_horizon:
            hard_misses += 1
            continue

        err = abs(p_med - act)
        errors.append(err)

        if p10 is not None and p90 is not None:
            in_interval = (p10 <= act <= p90)
            covered.append(in_interval)

    mae = float(np.mean(errors)) if errors else 0.0
    med_err = float(np.median(errors)) if errors else 0.0
    cov = float(np.mean(covered)) if covered else 0.0
    hard_miss_rate = float(hard_misses / n) if n > 0 else 0.0

    return {
        "n_occurring": n,
        "n_evaluated": len(errors),
        "hard_misses": hard_misses,
        "hard_miss_rate": round(hard_miss_rate, 4),
        "mae_median_ttc": round(mae, 2),
        "median_error_ttc": round(med_err, 2),
        "coverage_p10_p90": round(cov, 4),
    }


def blocked_bootstrap_ci(
    items: List[Any],
    metric_fn: Callable[[List[Any]], float],
    block_fn: Callable[[Any], Any] = lambda x: getattr(x, "seed", 0),
    n_resamples: int = 2000,
    confidence_level: float = 0.95,
    seed: int = 42,
) -> Tuple[float, float, float]:
    """Compute deterministic seed-blocked bootstrap confidence interval.

    Args:
        items: List of sample items (e.g. episodes, predictions, runs).
        metric_fn: Function mapping a resampled list of items to a float metric.
        block_fn: Function extracting block key (e.g. seed) from an item.
        n_resamples: Number of bootstrap iterations.
        confidence_level: Nominal confidence level (default 0.95).
        seed: Random seed for reproducibility.

    Returns:
        (point_estimate, ci_low, ci_high)
    """
    if not items:
        return (0.0, 0.0, 0.0)

    point_estimate = float(metric_fn(items))

    # Group items into blocks
    blocks: Dict[Any, List[Any]] = {}
    for it in items:
        blk = block_fn(it)
        blocks.setdefault(blk, []).append(it)

    block_keys = list(blocks.keys())
    num_blocks = len(block_keys)
    if num_blocks <= 1:
        # Cannot meaningfully resample blocks if only 1 block; fall back to unblocked item resampling
        rng = np.random.default_rng(seed)
        boot_vals: List[float] = []
        n_items = len(items)
        for _ in range(n_resamples):
            idxs = rng.integers(0, n_items, size=n_items)
            resampled = [items[i] for i in idxs]
            boot_vals.append(float(metric_fn(resampled)))
    else:
        rng = np.random.default_rng(seed)
        boot_vals = []
        for _ in range(n_resamples):
            sampled_blks = rng.choice(block_keys, size=num_blocks, replace=True)
            resampled = []
            for b_key in sampled_blks:
                resampled.extend(blocks[b_key])
            boot_vals.append(float(metric_fn(resampled)))

    boot_arr = np.asarray(boot_vals, dtype=float)
    # Filter out NaNs if any
    valid = boot_arr[~np.isnan(boot_arr)]
    if len(valid) == 0:
        return (point_estimate, point_estimate, point_estimate)

    alpha = (1.0 - confidence_level) / 2.0
    ci_low = float(np.percentile(valid, alpha * 100.0))
    ci_high = float(np.percentile(valid, (1.0 - alpha) * 100.0))

    return (round(point_estimate, 4), round(ci_low, 4), round(ci_high, 4))
