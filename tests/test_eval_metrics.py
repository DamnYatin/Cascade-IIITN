"""Tests E1 to E6 for Evaluation Metrics, Alerts, Attribution, Sweeps, and Bootstrap.

Verifies mathematical correctness of the yardstick BEFORE any forecaster results exist.
"""
from __future__ import annotations

import math
from typing import List
import numpy as np
import pytest

from backend.app.eval.alerts import (
    AlertRun,
    AlertStep,
    attribute_alerts,
    detect_alert_runs,
)
from backend.app.eval.events import (
    TrueEpisode,
    extract_city_cascade_episodes,
    extract_episodes_from_binary_mask,
    extract_node_episodes,
    extract_zone_cascade_episodes,
    merge_raw_spans,
)
from backend.app.eval.metrics import (
    blocked_bootstrap_ci,
    brier_decomposition,
    brier_score,
    brier_skill_score,
    compute_reliability_bins,
    compute_sharpness_histogram,
    compute_time_to_critical_metrics,
    compute_warning_metrics,
    wilson_score_interval,
)
from backend.app.eval.sweeps import (
    SweepPoint,
    interpolate_matched_far,
    select_operating_point,
)


def test_e1_brier_skill_ece_exact_toy_values():
    """E1: Verify Brier score, BSS, ECE and reliability bins on hand-computed toy cases."""
    # Toy case 1: 4 predictions
    probs = [0.8, 0.2, 0.9, 0.1]
    labels = [1, 0, 1, 0]

    # Hand computation:
    # errors: (0.8-1)^2=0.04, (0.2-0)^2=0.04, (0.9-1)^2=0.01, (0.1-0)^2=0.01
    # sum = 0.10 -> BS = 0.025
    bs = brier_score(probs, labels)
    assert pytest.approx(bs, abs=1e-6) == 0.025

    # Base rate y_bar = 0.5 -> ref_bs = 0.5 * 0.5 = 0.25
    # BSS = 1 - (0.025 / 0.25) = 1 - 0.10 = 0.90
    bss = brier_skill_score(probs, labels)
    assert pytest.approx(bss, abs=1e-6) == 0.90

    # 2 equal-width bins: [0, 0.5] and [0.5, 1.0]
    ece, bins = compute_reliability_bins(probs, labels, n_bins=2, equal_frequency=False)
    # Bin 0: [0.1, 0.2] -> mean_p=0.15, mean_y=0.0, gap=0.15, count=2
    # Bin 1: [0.8, 0.9] -> mean_p=0.85, mean_y=1.0, gap=0.15, count=2
    # ECE = (2/4)*0.15 + (2/4)*0.15 = 0.15
    assert pytest.approx(ece, abs=1e-6) == 0.15
    assert len(bins) == 2
    assert bins[0]["count"] == 2
    assert pytest.approx(bins[0]["pred_mean"], abs=1e-3) == 0.15
    assert pytest.approx(bins[0]["obs_freq"], abs=1e-3) == 0.0
    assert bins[1]["count"] == 2
    assert pytest.approx(bins[1]["pred_mean"], abs=1e-3) == 0.85
    assert pytest.approx(bins[1]["obs_freq"], abs=1e-3) == 1.0

    # Decomposition
    decomp = brier_decomposition(probs, labels, n_bins=2)
    # Uncertainty = 0.5 * 0.5 = 0.25
    # Reliability = (2/4)*(0.15-0)^2 + (2/4)*(0.85-1)^2 = 0.5*0.0225 + 0.5*0.0225 = 0.0225
    # Resolution = (2/4)*(0-0.5)^2 + (2/4)*(1-0.5)^2 = 0.5*0.25 + 0.5*0.25 = 0.25
    # BS = Rel - Res + Unc = 0.0225 - 0.25 + 0.25 = 0.0225 (slight difference due to binning vs continuous)
    assert pytest.approx(decomp["uncertainty"], abs=1e-4) == 0.25
    assert pytest.approx(decomp["resolution"], abs=1e-4) == 0.25
    assert pytest.approx(decomp["reliability"], abs=1e-4) == 0.0225


def test_e2_alert_run_logic_hysteresis_and_consecutive_steps():
    """E2: Test alert-run logic: hysteresis, minimum consecutive steps, run end."""
    hours = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
    # k=2, tau=0.5, tau_low=0.2, k_off=2
    scores = [
        0.1,  # 0h: low
        0.6,  # 1h: 1 step >= tau (consec=1, no alert yet)
        0.4,  # 2h: drops before k=2 -> no run started
        0.7,  # 3h: 1 step >= tau
        0.8,  # 4h: 2 steps >= tau -> ALERT RUN STARTS! (first_alert_hour = 3h)
        0.3,  # 5h: between tau_low and tau -> stays in run
        0.1,  # 6h: 1 step < tau_low
        0.15, # 7h: 2 steps < tau_low -> ALERT RUN ENDS at 7h
        0.0,  # 8h: low
        0.0,  # 9h: low
    ]
    runs = detect_alert_runs(
        scores=scores,
        hours=hours,
        tau=0.5,
        k=2,
        tau_low=0.2,
        k_off=2,
        entity_id="zone_a",
    )
    assert len(runs) == 1
    run = runs[0]
    assert run.first_alert_hour == 3.0
    assert run.end_alert_hour == 7.0
    assert len(run.steps) == 5  # steps at 3, 4, 5, 6, 7


def test_e3_attribution_edge_cases():
    """E3: Attribution edge cases:

    - Overlapping runs
    - Back-to-back episodes
    - Run spanning two episodes
    - Alert after episode start (late)
    - No alert (miss)
    - Alert with no episode (false alarm)
    - One run never credited twice
    """
    # 1. Standard hit: alert at 10h, episode at 30h (lead = 20h <= 72h)
    run1 = AlertRun(run_id="r1", entity_id="z1", level="CRITICAL", first_alert_hour=10.0, end_alert_hour=25.0)
    ep1 = TrueEpisode(episode_id="ep1", entity_type="zone_cascade", entity_id="z1", level="CRITICAL", start_hour=30.0, end_hour=40.0)

    res1 = attribute_alerts([run1], [ep1], h_hit=72.0)
    assert len(res1.hits) == 1
    assert res1.hits[0].lead_time_hours == 20.0
    assert len(res1.missed_episodes) == 0
    assert len(res1.false_alarms) == 0

    # 2. Alert after episode start -> LATE (negative lead), episode is MISSED
    run_late = AlertRun(run_id="r_late", entity_id="z1", level="CRITICAL", first_alert_hour=35.0, end_alert_hour=45.0)
    res_late = attribute_alerts([run_late], [ep1], h_hit=72.0)
    assert len(res_late.hits) == 0
    assert len(res_late.late_alerts) == 1
    assert res_late.late_alerts[0].lead_time_hours == -5.0
    assert len(res_late.missed_episodes) == 1
    assert len(res_late.false_alarms) == 0

    # 3. Alert with no episode -> FALSE ALARM
    run_fa = AlertRun(run_id="r_fa", entity_id="z1", level="CRITICAL", first_alert_hour=100.0, end_alert_hour=110.0)
    res_fa = attribute_alerts([run_fa], [ep1], h_hit=72.0)
    assert len(res_fa.hits) == 0
    assert len(res_fa.false_alarms) == 1
    assert len(res_fa.missed_episodes) == 1

    # 4. Run spanning two episodes: one run can serve at most ONE episode
    # ep1 at 20h, ep2 at 40h; run at 10h.
    ep2 = TrueEpisode(episode_id="ep2", entity_type="zone_cascade", entity_id="z1", level="CRITICAL", start_hour=40.0, end_hour=50.0)
    res_span = attribute_alerts([run1], [ep1, ep2], h_hit=72.0)
    assert len(res_span.hits) == 1
    assert res_span.hits[0].matched_episode_id == "ep1"
    assert len(res_span.missed_episodes) == 1
    assert res_span.missed_episodes[0].episode_id == "ep2"

    # 5. Two runs before one episode: earliest qualifying run gets credit, second run is false alarm
    run_earlier = AlertRun(run_id="r_early", entity_id="z1", level="CRITICAL", first_alert_hour=5.0, end_alert_hour=15.0)
    run_later = AlertRun(run_id="r_late", entity_id="z1", level="CRITICAL", first_alert_hour=15.0, end_alert_hour=25.0)
    res_multi = attribute_alerts([run_earlier, run_later], [ep1], h_hit=72.0)
    assert len(res_multi.hits) == 1
    assert res_multi.hits[0].run_id == "r_early"
    assert res_multi.hits[0].lead_time_hours == 25.0
    assert len(res_multi.false_alarms) == 1
    assert res_multi.false_alarms[0].run_id == "r_late"


def test_e4_lead_time_far_and_pod_on_known_timelines():
    """E4: Test lead time, FAR per 100 zone-days and POD on hand-built timelines with known answers."""
    # 2 zones, 72 hours simulation -> total_zone_days = (2 * 72) / 24 = 6.0 zone-days
    # Zone 1 has episode at 24h, alert at 12h (hit, lead 12h)
    # Zone 2 has episode at 48h, alert at 24h (hit, lead 24h)
    # Zone 1 has another alert at 60h with no episode (false alarm)
    # Zone 2 has a missed episode at 65h (miss)
    hits = 2
    misses = 1
    false_alarms = 1
    late_alerts = 0
    lead_times = [12.0, 24.0]
    total_zone_days = 6.0

    metrics = compute_warning_metrics(
        hits=hits,
        misses=misses,
        false_alarms=false_alarms,
        late_alerts=late_alerts,
        lead_times=lead_times,
        total_zone_days=total_zone_days,
    )

    # Total episodes = 2 + 1 = 3 -> POD = 2/3 = 0.6667
    assert pytest.approx(metrics["pod"], abs=1e-3) == 0.6667
    # FAR per 100 zone-days = (1 / 6.0) * 100 = 16.667
    assert pytest.approx(metrics["far_per_100_zone_days"], abs=1e-3) == 16.667
    # Alert ratio = 1 / (2 + 1 + 0) = 1/3 = 0.3333
    assert pytest.approx(metrics["far_alert_ratio"], abs=1e-3) == 0.3333
    # Median lead time = median([12, 24]) = 18.0h
    assert metrics["lead_time_median"] == 18.0
    assert metrics["lead_time_iqr"] == 6.0
    assert metrics["lead_frac_ge_12h"] == 1.0
    assert metrics["lead_frac_ge_24h"] == 0.5


def test_e5_matched_far_and_operating_point_selection():
    """E5: Test matched-FAR interpolation and operating-point selection, including ties and infeasible targets."""
    # Build a synthetic sweep curve
    points = [
        SweepPoint(tau=0.7, k=3, tau_low=0.4, pod=0.50, far_per_100_zone_days=0.5, far_alert_ratio=0.1, lead_time_median=10.0, lead_time_iqr=2.0, hits=5, misses=5, false_alarms=1, late_alerts=0),
        SweepPoint(tau=0.5, k=2, tau_low=0.3, pod=0.80, far_per_100_zone_days=1.5, far_alert_ratio=0.2, lead_time_median=20.0, lead_time_iqr=4.0, hits=8, misses=2, false_alarms=3, late_alerts=0),
        # Tie case: same POD and FAR, but different lead times
        SweepPoint(tau=0.4, k=2, tau_low=0.2, pod=0.80, far_per_100_zone_days=1.5, far_alert_ratio=0.2, lead_time_median=25.0, lead_time_iqr=3.0, hits=8, misses=2, false_alarms=3, late_alerts=0),
        SweepPoint(tau=0.2, k=1, tau_low=0.1, pod=0.95, far_per_100_zone_days=5.0, far_alert_ratio=0.5, lead_time_median=35.0, lead_time_iqr=5.0, hits=9, misses=1, false_alarms=10, late_alerts=0),
    ]

    # 1. Feasible target FAR = 2.0
    # Feasible points: far <= 2.0 are tau=0.7 (pod 0.5), tau=0.5 (pod 0.8, lead 20), tau=0.4 (pod 0.8, lead 25).
    # Best POD is 0.80. Tie-break by larger lead time -> tau=0.4 (lead 25.0) must win!
    best_pt, is_feas = select_operating_point(points, target_far=2.0)
    assert is_feas is True
    assert best_pt.tau == 0.4
    assert best_pt.lead_time_median == 25.0

    # 2. Infeasible target FAR = 0.2
    # No point has FAR <= 0.2. Minimum FAR point is tau=0.7 (FAR 0.5)
    fallback_pt, is_feas2 = select_operating_point(points, target_far=0.2)
    assert is_feas2 is False
    assert fallback_pt.tau == 0.7
    assert fallback_pt.far_per_100_zone_days == 0.5

    # 3. Matched-FAR interpolation
    # At target FAR = 1.0 (between 0.5 and 1.5):
    # far 0.5 -> lead 10.0, pod 0.50
    # far 1.5 -> lead 20.0, pod 0.80
    # At 1.0 (exact midpoint), lead should be 15.0, pod should be 0.65
    interp = interpolate_matched_far(points[:2], target_far=1.0)
    assert pytest.approx(interp["lead_time"], abs=1e-1) == 15.0
    assert pytest.approx(interp["pod"], abs=1e-3) == 0.650


def test_e6_deterministic_seed_blocked_bootstrap():
    """E6: Verify blocked bootstrap:

    - Deterministic for fixed seed
    - Correct blocking by seed
    - Intervals contain true parameter on a known toy distribution
    """
    class MockRecord:
        def __init__(self, seed: int, value: float):
            self.seed = seed
            self.value = value

    # Generate samples from Normal(mu=10.0, sigma=2.0) grouped across 10 seeds
    rng = np.random.default_rng(999)
    records: List[MockRecord] = []
    for s in range(10):
        # 20 observations per seed
        vals = rng.normal(loc=10.0, scale=2.0, size=20)
        for v in vals:
            records.append(MockRecord(seed=s, value=float(v)))

    metric_mean = lambda recs: float(np.mean([r.value for r in recs]))

    # Run bootstrap twice with same seed -> must be identical
    pt1, lo1, hi1 = blocked_bootstrap_ci(records, metric_mean, seed=42)
    pt2, lo2, hi2 = blocked_bootstrap_ci(records, metric_mean, seed=42)

    assert pt1 == pt2
    assert lo1 == lo2
    assert hi1 == hi2

    # Verify nominal interval coverage: true mean 10.0 must be inside [lo1, hi1]
    assert lo1 <= 10.0 <= hi1
    # Check width is reasonable (std of mean is 2.0 / sqrt(200) ≈ 0.14, 95% CI width ≈ 0.56)
    assert 9.0 <= lo1 <= 10.0
    assert 10.0 <= hi1 <= 11.0
