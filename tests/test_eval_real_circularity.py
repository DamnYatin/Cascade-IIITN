"""Test E15: Circularity Guard and Real-Event Evaluation Integrity.

Rule V5:
  - Guard must refuse or flag anchor_mode=on when evaluating against critical labels or response.
  - Evaluation must run cleanly with anchor_mode=off.
  - Provenance must explicitly state simulated downstream systems and small-n negative controls.
"""
from __future__ import annotations

import pytest

from backend.app.eval.realcheck import (
    CircularityGuardError,
    evaluate_real_assam_event,
    validate_circularity_guard,
)


def test_e15_circularity_guard_strictly_rejects_anchor_mode_on():
    """E15: validate_circularity_guard must raise CircularityGuardError if anchor_mode=on."""
    with pytest.raises(CircularityGuardError) as exc_info:
        validate_circularity_guard("on")
    assert "Rule V5 Violation" in str(exc_info.value)
    assert "strictly prohibited" in str(exc_info.value)

    # Must also reject mixed case e.g. "ON" or "On"
    with pytest.raises(CircularityGuardError):
        validate_circularity_guard("ON")

    # anchor_mode=off must pass without error
    validate_circularity_guard("off")


def test_e15_evaluate_real_event_circularity_enforcement():
    """E15: evaluate_real_assam_event must fail immediately if anchor_mode=on."""
    with pytest.raises(CircularityGuardError):
        evaluate_real_assam_event(anchor_mode="on")


def test_e15_real_event_provenance_and_negative_controls():
    """E15: evaluate_real_assam_event under anchor_mode=off returns honest provenance and negative controls."""
    res = evaluate_real_assam_event(
        city_id="upper_assam",
        anchor_mode="off",
        duration_hours=72,  # short test run
        cadence_hours=6,
        rollouts=10,
    )
    assert res["circularity_status"] == "GUARANTEED_CLEAN: anchor_mode=off"
    assert "SIMULATED infrastructure" in res["provenance"]["downstream_systems"]
    assert "Real rainfall" in res["provenance"]["inputs"]

    nc = res["negative_controls"]
    assert "unaffected_zones" in nc
    assert "unaffected_zones_alert_count" in nc
    assert "small_sample_caveat" in nc
