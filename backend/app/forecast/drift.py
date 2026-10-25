"""Online concept drift detectors for prediction errors.

Implementations:
  - Page-Hinkley test (pure Python / NumPy)
  - Two-window mean-shift test (pure Python / NumPy)
  - Optional River ADWIN adapter behind common interface
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Deque, List, Optional
from collections import deque
import numpy as np

from backend.app.forecast.config import DriftConfig


@dataclass(frozen=True)
class DriftEvent:
    node: str
    time: datetime
    detector: str
    magnitude: float


class BaseDriftDetector:
    def update(self, val: float, clock_time: datetime) -> bool:
        raise NotImplementedError

    def reset(self) -> None:
        raise NotImplementedError


class PageHinkleyDetector(BaseDriftDetector):
    """Page-Hinkley test for detecting change in the mean of a continuous sequence.

    Monitors cumulative deviation:
      m_t = running mean
      U_t = sum(x_i - m_t - delta)
      PH_t = U_t - min(U)
    Fires when PH_t > lambda_.
    """

    def __init__(self, delta: float = 0.005, lambda_: float = 0.5):
        self.delta = delta
        self.lambda_ = lambda_
        self.n: int = 0
        self.mean: float = 0.0
        self.sum_val: float = 0.0
        self.cum_dev: float = 0.0
        self.min_cum_dev: float = 0.0

    def update(self, val: float, clock_time: datetime) -> bool:
        self.n += 1
        self.sum_val += val
        self.mean = self.sum_val / self.n

        # Deviation from mean adjusted by delta
        dev = val - self.mean - self.delta
        self.cum_dev += dev
        if self.cum_dev < self.min_cum_dev:
            self.min_cum_dev = self.cum_dev

        ph_stat = self.cum_dev - self.min_cum_dev
        if ph_stat > self.lambda_:
            self.reset()
            return True
        return False

    def reset(self) -> None:
        self.n = 0
        self.sum_val = 0.0
        self.mean = 0.0
        self.cum_dev = 0.0
        self.min_cum_dev = 0.0


class TwoWindowMeanShiftDetector(BaseDriftDetector):
    """Detects shift between short reference window and longer background window."""

    def __init__(self, short_window: int = 12, long_window: int = 48, threshold_z: float = 2.5):
        self.short_window = short_window
        self.long_window = long_window
        self.threshold_z = threshold_z
        self._history: Deque[float] = deque(maxlen=long_window)

    def update(self, val: float, clock_time: datetime) -> bool:
        self._history.append(val)
        if len(self._history) < self.long_window:
            return False

        short_vals = list(self._history)[-self.short_window :]
        long_vals = list(self._history)

        mean_s = float(np.mean(short_vals))
        mean_l = float(np.mean(long_vals))
        std_l = float(np.std(long_vals))

        if std_l < 1e-4:
            return False

        z = abs(mean_s - mean_l) / (std_l / np.sqrt(self.short_window))
        if z > self.threshold_z:
            self.reset()
            return True
        return False

    def reset(self) -> None:
        self._history.clear()


def make_drift_detector(config: DriftConfig) -> BaseDriftDetector:
    """Instantiate drift detector according to config with River fallback."""
    if config.method.lower() == "adwin":
        try:
            from river.drift import ADWIN

            class RiverADWINAdapter(BaseDriftDetector):
                def __init__(self):
                    self._adwin = ADWIN(delta=config.delta)

                def update(self, val: float, clock_time: datetime) -> bool:
                    self._adwin.update(val)
                    return bool(self._adwin.drift_detected)

                def reset(self) -> None:
                    self._adwin = ADWIN(delta=config.delta)

            return RiverADWINAdapter()
        except ImportError:
            # Fallback to Page-Hinkley if river is not installed
            return PageHinkleyDetector(delta=config.delta, lambda_=config.lambda_)

    elif config.method.lower() == "two_window":
        return TwoWindowMeanShiftDetector()

    # Default: Page-Hinkley
    return PageHinkleyDetector(delta=config.delta, lambda_=config.lambda_)
