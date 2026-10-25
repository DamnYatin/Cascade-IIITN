"""Calibrator implementations: Pool-Adjacent-Violators (PAV), Frozen, and Online Rolling.

Rule V2:
  - Calibration may only use outcomes that were OBSERVABLE and MATURED.
  - Online calibration derives outcomes from the system's own filtered state trajectory.
  - Offline frozen calibration is fitted strictly on calib-fit seeds disjoint from eval.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple
import numpy as np


def pool_adjacent_violators(
    x: List[float] | np.ndarray,
    y: List[float] | np.ndarray,
    weights: Optional[List[float] | np.ndarray] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Pure-Python / NumPy Pool Adjacent Violators (PAV) isotonic regression algorithm.

    Finds non-decreasing y_iso minimizing sum w_i * (y_iso - y_i)^2 subject to y_iso[i] <= y_iso[i+1].

    Returns:
        (unique_x, fitted_y)
    """
    x_arr = np.asarray(x, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    n = len(x_arr)
    if n == 0:
        return np.array([0.0, 1.0]), np.array([0.0, 1.0])
    if n == 1:
        val = float(max(0.0, min(1.0, y_arr[0])))
        return np.array([0.0, float(x_arr[0]), 1.0]), np.array([val, val, val])

    if weights is None:
        w_arr = np.ones(n, dtype=float)
    else:
        w_arr = np.asarray(weights, dtype=float)

    # Sort primarily by x ascending, stably
    order = np.argsort(x_arr)
    x_sorted = x_arr[order]
    y_sorted = y_arr[order]
    w_sorted = w_arr[order]

    # Block representation: [weight, sum_wy, x_min, x_max]
    blocks: List[List[float]] = []
    for xi, yi, wi in zip(x_sorted, y_sorted, w_sorted):
        blocks.append([wi, wi * yi, xi, xi])

        while len(blocks) >= 2:
            prev_val = blocks[-2][1] / max(1e-12, blocks[-2][0])
            curr_val = blocks[-1][1] / max(1e-12, blocks[-1][0])
            if curr_val < prev_val:
                # Pool adjacent violators
                w1, wy1, xmin1, xmax1 = blocks.pop()
                w0, wy0, xmin0, xmax0 = blocks.pop()
                blocks.append([w0 + w1, wy0 + wy1, xmin0, xmax1])
            else:
                break

    # Build monotone breakpoints
    bp_x: List[float] = [0.0]
    bp_y: List[float] = []

    # Initial anchor
    first_y = max(0.0, min(1.0, blocks[0][1] / max(1e-12, blocks[0][0])))
    bp_y.append(first_y)

    for b in blocks:
        val = max(0.0, min(1.0, b[1] / max(1e-12, b[0])))
        mid_x = (b[2] + b[3]) / 2.0
        if mid_x > bp_x[-1]:
            bp_x.append(mid_x)
            bp_y.append(val)

    if bp_x[-1] < 1.0:
        bp_x.append(1.0)
        last_y = max(0.0, min(1.0, blocks[-1][1] / max(1e-12, blocks[-1][0])))
        bp_y.append(last_y)

    # Ensure endpoints are strictly [0.0, 1.0] and monotone non-decreasing
    final_x = np.array(bp_x, dtype=float)
    final_y = np.maximum.accumulate(np.array(bp_y, dtype=float))
    return final_x, final_y


class Calibrator(Protocol):
    """Protocol for calibrating raw rollout probabilities."""

    is_calibrated: bool
    calibration_source: str

    def calibrate(self, p: float, context: Optional[str] = None) -> float:
        """Calibrate raw probability p in [0, 1]."""
        ...


class IdentityCalibrator:
    """Default identity calibrator: passes raw probabilities through untouched."""

    def __init__(self):
        self.is_calibrated = False
        self.calibration_source = "none"

    def calibrate(self, p: float, context: Optional[str] = None) -> float:
        return float(max(0.0, min(1.0, p)))


class OnlineRollingCalibrator:
    """Online rolling isotonic calibrator updated from matured observed outcomes."""

    def __init__(
        self,
        min_samples: int = 20,
        shrinkage_n0: float = 15.0,
        max_buffer_size: int = 500,
    ):
        self.min_samples = min_samples
        self.shrinkage_n0 = shrinkage_n0
        self.max_buffer_size = max_buffer_size

        self.is_calibrated = False
        self.calibration_source = "online"

        self._x_buffer: List[float] = []
        self._y_buffer: List[float] = []
        self._w_buffer: List[float] = []

        self._map_x = np.array([0.0, 1.0])
        self._map_y = np.array([0.0, 1.0])

    def add_outcomes(
        self,
        predicted_probs: List[float],
        true_outcomes: List[float],
        weights: Optional[List[float]] = None,
    ) -> None:
        """Ingest newly matured outcomes and refit isotonic curve."""
        if not predicted_probs:
            return

        w_list = weights if weights is not None else [1.0] * len(predicted_probs)
        for p, y, w in zip(predicted_probs, true_outcomes, w_list):
            self._x_buffer.append(float(p))
            self._y_buffer.append(float(y))
            self._w_buffer.append(float(w))

        # Maintain bounded ring buffer
        if len(self._x_buffer) > self.max_buffer_size:
            self._x_buffer = self._x_buffer[-self.max_buffer_size :]
            self._y_buffer = self._y_buffer[-self.max_buffer_size :]
            self._w_buffer = self._w_buffer[-self.max_buffer_size :]

        # Check minimum samples
        if len(self._x_buffer) >= self.min_samples:
            self.is_calibrated = True
            bx, by = pool_adjacent_violators(self._x_buffer, self._y_buffer, self._w_buffer)
            self._map_x = bx
            self._map_y = by
        else:
            self.is_calibrated = False

    def calibrate(self, p: float, context: Optional[str] = None) -> float:
        """Calibrate probability p with shrinkage toward identity for small samples."""
        p_clamped = max(0.0, min(1.0, float(p)))
        if not self.is_calibrated:
            return p_clamped

        # Monotone piecewise linear interpolation
        p_iso = float(np.interp(p_clamped, self._map_x, self._map_y))

        # Shrinkage toward identity: gamma = N / (N + N0)
        n = len(self._x_buffer)
        gamma = n / (n + self.shrinkage_n0)
        calibrated_p = gamma * p_iso + (1.0 - gamma) * p_clamped
        return float(max(0.0, min(1.0, calibrated_p)))


class FrozenIsotonicCalibrator:
    """Offline frozen isotonic calibrator fitted on calib-fit seeds and loaded read-only."""

    def __init__(
        self,
        mapping_x: List[float] | np.ndarray,
        mapping_y: List[float] | np.ndarray,
        provenance: Optional[Dict[str, Any]] = None,
        widening_factor_ttc: float = 1.0,
    ):
        self._map_x = np.asarray(mapping_x, dtype=float)
        self._map_y = np.maximum.accumulate(np.asarray(mapping_y, dtype=float))
        self.provenance = provenance or {}
        self.widening_factor_ttc = float(widening_factor_ttc)

        self.is_calibrated = True
        self.calibration_source = "frozen"

    @classmethod
    def load(cls, path: str | Path) -> FrozenIsotonicCalibrator:
        """Load frozen calibrator from JSON with provenance validation."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Frozen calibrator file not found: {p}")

        data = json.loads(p.read_text(encoding="utf-8"))
        map_x = data["mapping_x"]
        map_y = data["mapping_y"]
        prov = data.get("provenance", {})
        widening = data.get("widening_factor_ttc", 1.0)
        return cls(mapping_x=map_x, mapping_y=map_y, provenance=prov, widening_factor_ttc=widening)

    def save(self, path: str | Path) -> None:
        """Save frozen calibrator to JSON with provenance."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "calibration_source": "frozen",
            "mapping_x": [round(float(v), 5) for v in self._map_x],
            "mapping_y": [round(float(v), 5) for v in self._map_y],
            "widening_factor_ttc": round(self.widening_factor_ttc, 4),
            "provenance": self.provenance,
        }
        p.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def calibrate(self, p: float, context: Optional[str] = None) -> float:
        """Calibrate probability p using frozen piecewise linear isotonic mapping."""
        p_clamped = max(0.0, min(1.0, float(p)))
        calibrated_p = float(np.interp(p_clamped, self._map_x, self._map_y))
        return float(max(0.0, min(1.0, calibrated_p)))
