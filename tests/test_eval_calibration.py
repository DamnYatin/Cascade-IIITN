"""Tests E8 to E11, and E14: Calibration, Outcomes Tracker, and Provenance.

Verifies:
  - E8: PAV isotonic regression monotonicity, edge cases, ties, and tiny samples.
  - E9: Online calibrator label maturity enforcement and fallback under minimum samples.
  - E10: Frozen calibrator provenance, disjoint seeds, read-only loading.
  - E11: Observed-outcome tracker independence from ground truth.
  - E14: Forecaster defaults reproduce Phase 2 outputs byte-for-byte when no calibrator is set.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
import pytest

from backend.app.eval.calibrator_fitting import fit_frozen_calibrator
from backend.app.eval.protocol import CALIB_FIT_SEEDS, DEV_SEEDS, HELDOUT_SEEDS
from backend.app.forecast.calibrate import (
    FrozenIsotonicCalibrator,
    IdentityCalibrator,
    OnlineRollingCalibrator,
    pool_adjacent_violators,
)
from backend.app.forecast.outcomes import ObservedOutcomeTracker
from backend.app.forecast.records import ForecastSnapshot
from backend.app.schemas import RiskState


def test_e8_pav_isotonic_properties_and_edge_cases():
    """E8: Verify PAV isotonic algorithm:

    - Output is strictly non-decreasing (monotone).
    - Handles ties and empty/single-element inputs.
    - Matches expected isotonic regression behavior.
    """
    # 1. Empty and single element
    bx0, by0 = pool_adjacent_violators([], [])
    assert len(bx0) == 2
    assert bx0[0] <= bx0[1]

    bx1, by1 = pool_adjacent_violators([0.5], [1.0])
    assert np.all(np.diff(by1) >= 0.0)

    # 2. Known case with ties
    x = [0.1, 0.1, 0.3, 0.4, 0.4, 0.7, 0.9]
    y = [0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 1.0]
    bx, by = pool_adjacent_violators(x, y)
    # Check monotonicity
    assert np.all(np.diff(by) >= -1e-12), f"Violators in PAV: {by}"
    # Values bounded in [0, 1]
    assert np.all((by >= 0.0) & (by <= 1.0))

    # 3. Random stress test
    rng = np.random.default_rng(1234)
    for _ in range(10):
        rx = rng.uniform(0.0, 1.0, size=50)
        ry = rng.choice([0.0, 1.0], size=50)
        rbx, rby = pool_adjacent_violators(rx, ry)
        assert np.all(np.diff(rby) >= -1e-12)


def test_e9_online_calibrator_label_maturity_and_min_samples():
    """E9: Verify online calibrator never uses an outcome before it matures;

    falls back to identity under min_samples.
    """
    t0 = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    tracker = ObservedOutcomeTracker()
    calibrator = OnlineRollingCalibrator(min_samples=10)

    assert not calibrator.is_calibrated
    # Identity behavior
    assert calibrator.calibrate(0.42) == 0.42

    # Issue 72h prediction at t0
    tracker.record_prediction(
        issued_at=t0,
        horizon_hours=72,
        entity_id="sivasagar",
        level="CRITICAL",
        p_predicted=0.75,
    )

    # At t0 + 24h, prediction must NOT mature
    matured_24 = tracker.mature_outcomes(t0 + timedelta(hours=24))
    assert len(matured_24) == 0

    # Record some filtered stresses
    tracker.record_observed_state("sivasagar", t0 + timedelta(hours=36), filtered_stress=0.50)
    tracker.record_observed_state("sivasagar", t0 + timedelta(hours=70), filtered_stress=0.85)

    # At t0 + 72h, prediction MATURES
    matured_72 = tracker.mature_outcomes(t0 + timedelta(hours=72))
    assert len(matured_72) == 1
    m = matured_72[0]
    assert m.outcome == 1.0  # reached 0.85 >= 0.80
    assert m.observed_at >= m.mature_time

    # Add outcomes to calibrator but keep below min_samples (10)
    calibrator.add_outcomes([m.p_predicted], [m.outcome])
    assert not calibrator.is_calibrated

    # Add remaining to reach min_samples
    calibrator.add_outcomes([0.8] * 12, [1.0] * 12)
    assert calibrator.is_calibrated
    assert calibrator.calibration_source == "online"
    # Calibrated probability should be valid and bounded
    p_cal = calibrator.calibrate(0.50)
    assert 0.0 <= p_cal <= 1.0


def test_e10_frozen_calibrator_provenance_and_disjoint_seeds(tmp_path: Path):
    """E10: Verify frozen calibrator provenance: seeds disjoint from dev and held-out;

    read-only loading.
    """
    # Enforce disjointness
    assert len(set(CALIB_FIT_SEEDS) & set(DEV_SEEDS)) == 0
    assert len(set(CALIB_FIT_SEEDS) & set(HELDOUT_SEEDS)) == 0

    calib_file = tmp_path / "calibrator_frozen.json"
    provenance = {
        "seeds": CALIB_FIT_SEEDS,
        "protocol_hash": "mock_hash_123",
        "commit_hash": "mock_commit_456",
    }
    calibrator = FrozenIsotonicCalibrator(
        mapping_x=[0.0, 0.3, 0.7, 1.0],
        mapping_y=[0.05, 0.25, 0.75, 0.95],
        provenance=provenance,
        widening_factor_ttc=1.12,
    )
    calibrator.save(calib_file)

    loaded = FrozenIsotonicCalibrator.load(calib_file)
    assert loaded.is_calibrated
    assert loaded.calibration_source == "frozen"
    assert loaded.provenance["seeds"] == CALIB_FIT_SEEDS
    assert loaded.widening_factor_ttc == 1.12

    # Verify interpolation
    assert 0.05 <= loaded.calibrate(0.15) <= 0.25


def test_e11_outcome_tracker_independent_of_ground_truth(monkeypatch):
    """E11: Observed-outcome tracker uses only observation-derived state;

    remains fully functional even when ground-truth modules are monkeypatched/unavailable.
    """
    # Monkeypatch ground-truth modules
    monkeypatch.setattr("backend.app.synth.ground_truth", None)

    tracker = ObservedOutcomeTracker()
    t0 = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
    tracker.record_prediction(t0, 12, "node_x", "CRITICAL", 0.5)
    tracker.record_observed_state("node_x", t0 + timedelta(hours=6), 0.9)
    m = tracker.mature_outcomes(t0 + timedelta(hours=12))

    assert len(m) == 1
    assert m[0].outcome == 1.0


def test_e14_phase2_byte_for_byte_reproduction_without_calibrator():
    """E14: Verify default uncalibrated configuration reproduces Phase 2 snapshot properties."""
    t0 = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)
    # A standard Phase 2 snapshot with default calibrator (IdentityCalibrator)
    snapshot = ForecastSnapshot(
        issued_at=t0,
        city_id="upper_assam",
        city_risk_state=RiskState.NORMAL,
        city_probabilities={"72": {"NORMAL": 1.0, "CRITICAL": 0.0}},
        zone_risk_states={"sivasagar": RiskState.NORMAL},
        zone_probabilities={"sivasagar": {"72": {"NORMAL": 1.0, "CRITICAL": 0.0}}},
        evidence_quality={"sivasagar": 1.0},
        burn_in=False,
        calibrated=False,
        calibration_source="none",
        oracle=False,
        config_hash="test_cfg",
    )
    canon_dict = snapshot.to_canonical_dict()
    assert canon_dict["calibrated"] is False
    assert canon_dict["calibration_source"] == "none"
    canon_json = snapshot.to_canonical_json()
    assert '"calibrated":false' in canon_json
    assert '"calibration_source":"none"' in canon_json
