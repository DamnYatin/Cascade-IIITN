"""Calibrator interface and identity implementation.

Phase 2 uses uncalibrated raw probabilities (calibrated=false).
Phase 3 will fit empirical calibration (isotonic/Platt).
"""
from __future__ import annotations

from typing import Optional, Protocol


class Calibrator(Protocol):
    """Protocol for calibrating raw rollout probabilities."""

    is_calibrated: bool

    def calibrate(self, p: float, context: Optional[str] = None) -> float:
        """Calibrate raw probability p in [0, 1]."""
        ...


class IdentityCalibrator:
    """Default identity calibrator: passes raw probabilities through untouched."""

    def __init__(self):
        self.is_calibrated = False

    def calibrate(self, p: float, context: Optional[str] = None) -> float:
        return float(max(0.0, min(1.0, p)))
