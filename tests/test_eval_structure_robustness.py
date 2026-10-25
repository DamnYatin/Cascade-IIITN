"""Tests for Structure, Drift, and Robustness Analyses (G6).

Verifies:
  - Edge recovery against planted graph: precision, recall, F1, and decoy pair FPR.
  - Drift detection latency on planted regime changes and false alarm counts pre-change.
  - Adversity deltas calculation between clean and faulted runs.
  - Source trust ordering: verifies lowest rank for faulty sensor.
  - Evidence quality binning: validates error spread and predictive interval coverage.
"""
from __future__ import annotations

from typing import List, Tuple
import numpy as np
import pytest

from backend.app.eval.robustness import (
    compute_adversity_deltas,
    evaluate_evidence_quality_bins,
    evaluate_trust_ordering,
)
from backend.app.eval.structure import evaluate_drift_latency, evaluate_edge_recovery
from backend.app.schemas import Edge


def test_edge_recovery_metrics():
    """Verify edge precision, recall, F1, and decoy pair rejection."""
    planted = [
        Edge(u="zoneA:rain", v="zoneA:river", lag_hours=2.0, weight=0.6, confidence=0.8),
        Edge(u="zoneA:river", v="zoneA:transport", lag_hours=3.0, weight=0.5, confidence=0.7),
        Edge(u="zoneA:transport", v="zoneA:health", lag_hours=1.0, weight=0.4, confidence=0.6),
    ]
    # Learned has 2 true edges, 1 false positive, and missed 1 edge
    learned = [
        {"u": "zoneA:rain", "v": "zoneA:river", "lag_hours": 2.0},
        {"u": "zoneA:river", "v": "zoneA:transport", "lag_hours": 3.5},
        {"u": "zoneB:power", "v": "zoneA:health", "lag_hours": 1.0},  # FP
    ]
    decoy_pairs = [("zoneB:power", "zoneA:health"), ("zoneA:rain", "zoneB:health")]

    res = evaluate_edge_recovery(learned, planted, decoy_pairs)
    # TP = 2, FP = 1, FN = 1
    assert res["true_positives"] == 2
    assert res["false_positives"] == 1
    assert res["false_negatives"] == 1
    assert res["precision"] == pytest.approx(2 / 3, abs=1e-3)
    assert res["recall"] == pytest.approx(2 / 3, abs=1e-3)
    assert res["f1"] == pytest.approx(2 / 3, abs=1e-3)
    assert res["decoy_fpr"] == pytest.approx(1 / 2, abs=1e-3)
    # Lag error: |2.0 - 2.0| = 0.0, |3.5 - 3.0| = 0.5 -> mean = 0.25
    assert res["mean_lag_error"] == pytest.approx(0.25, abs=1e-2)


def test_drift_latency_evaluation():
    """Verify drift detection latency and pre-change false drift alerts."""
    drift_events = [
        {"hour": 24.0, "type": "page_hinkley"},  # Pre-change false drift
        {"hour": 78.0, "type": "page_hinkley"},  # Post-change detection at 78h
        {"hour": 90.0, "type": "page_hinkley"},
    ]
    res = evaluate_drift_latency(drift_events, planted_change_hour=72.0)
    assert res["detected"] is True
    assert res["detection_delay_hours"] == pytest.approx(6.0, abs=1e-2)
    assert res["false_drift_alerts_pre_change"] == 1

    # Undetected case
    res_undetected = evaluate_drift_latency([], planted_change_hour=72.0)
    assert res_undetected["detected"] is False
    assert res_undetected["detection_delay_hours"] is None


def test_adversity_deltas_computation():
    """Verify performance deltas between clean and faulted runs."""
    clean = {"brier": 0.08, "ece": 0.05, "lead_time_median": 18.0, "pod": 0.95, "far_per_100_zone_days": 0.2}
    faulted = {"brier": 0.12, "ece": 0.09, "lead_time_median": 14.0, "pod": 0.85, "far_per_100_zone_days": 0.5}

    deltas = compute_adversity_deltas(clean, faulted)
    assert deltas["delta_brier"] == pytest.approx(0.04, abs=1e-4)
    assert deltas["delta_ece"] == pytest.approx(0.04, abs=1e-4)
    assert deltas["delta_lead_time"] == pytest.approx(-4.0, abs=1e-2)
    assert deltas["delta_pod"] == pytest.approx(-0.10, abs=1e-4)
    assert deltas["delta_far_per_100_zone_days"] == pytest.approx(0.30, abs=1e-3)


def test_trust_ordering_evaluation():
    """Verify faulty sensor is correctly identified and ranked lowest."""
    trust_map = {
        "sensor_good_1": 0.92,
        "sensor_good_2": 0.88,
        "sensor_faulty": 0.21,
    }
    res = evaluate_trust_ordering(trust_map, faulty_source="sensor_faulty")
    assert res["ranked_lowest"] is True
    assert res["faulty_rank"] == 1
    assert res["total_sources"] == 3
    assert res["faulty_trust"] == 0.21


def test_evidence_quality_bins():
    """Verify evidence quality binning and error/coverage relationships."""
    eqs = [0.1, 0.2, 0.5, 0.6, 0.8, 0.9]
    errors = [4.5, 4.0, 2.0, 1.8, 0.5, 0.4]
    covers = [False, False, True, True, True, True]

    bins = evaluate_evidence_quality_bins(eqs, errors, covers, n_bins=2)
    assert len(bins) == 2
    # Low EQ bin should have higher error
    assert bins[0]["mean_error"] > bins[1]["mean_error"]
    # High EQ bin should have higher coverage
    assert bins[1]["interval_coverage"] >= bins[0]["interval_coverage"]
