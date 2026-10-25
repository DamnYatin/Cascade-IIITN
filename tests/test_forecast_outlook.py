"""Phase 2 tests: Rain outlook models, causality, and oracle lockout (T5, T6)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
import numpy as np
import pytest

from backend.app.forecast.outlook import (
    BlockBootstrapOutlook,
    ForecastProductOutlook,
    OracleOutlook,
    PersistenceDecayOutlook,
)
from backend.app.schemas import Observation, SourceKind


def test_t5_oracle_lockout_enforced():
    """T5: OracleOutlook raises PermissionError unless FORECAST_ALLOW_ORACLE=1 and diagnostic=True."""
    # Ensure env variable is not set
    if "FORECAST_ALLOW_ORACLE" in os.environ:
        del os.environ["FORECAST_ALLOW_ORACLE"]

    # 1. Attempt without env and without diagnostic
    with pytest.raises(PermissionError, match="locked out"):
        OracleOutlook(future_rain_series={}, diagnostic=False)

    # 2. Attempt with diagnostic=True but no env
    with pytest.raises(PermissionError, match="locked out"):
        OracleOutlook(future_rain_series={}, diagnostic=True)

    # 3. Attempt with env set but diagnostic=False
    os.environ["FORECAST_ALLOW_ORACLE"] = "1"
    try:
        with pytest.raises(PermissionError, match="locked out"):
            OracleOutlook(future_rain_series={}, diagnostic=False)

        # 4. Success only when BOTH are present
        oracle = OracleOutlook(future_rain_series={}, diagnostic=True)
        assert oracle.is_oracle is True
    finally:
        del os.environ["FORECAST_ALLOW_ORACLE"]


def test_t5_forecast_product_raises_not_implemented():
    """ForecastProductOutlook raises NotImplementedError as intended."""
    prod = ForecastProductOutlook()
    rng = np.random.default_rng(42)
    with pytest.raises(NotImplementedError):
        prod.sample("sivasagar", datetime.now(timezone.utc), horizon_hours=72, n=10, rng=rng)


def test_t6_outlook_causality_persistence_decay():
    """T6: PersistenceDecayOutlook output at issue_time T is unchanged when future observations are altered."""
    t0 = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
    t_eval = t0 + timedelta(hours=12)

    outlook_a = PersistenceDecayOutlook()
    outlook_b = PersistenceDecayOutlook()

    # Generate 24 hours of observations
    for h in range(24):
        t = t0 + timedelta(hours=h)
        obs_a = Observation(
            source="openmeteo_rain",
            source_kind=SourceKind.REAL,
            zone="sivasagar",
            system="river_embankment",
            value=8.0,
            event_time=t,
            arrival_time=t + timedelta(hours=1),
        )
        outlook_a.ingest(obs_a)

        # For outlook_b, alter observations after t_eval
        if obs_a.arrival_time > t_eval:
            obs_b = obs_a.model_copy(update={"value": 500.0})
        else:
            obs_b = obs_a
        outlook_b.ingest(obs_b)

    rng_a = np.random.default_rng(12345)
    rng_b = np.random.default_rng(12345)

    samples_a = outlook_a.sample("sivasagar", issue_time=t_eval, horizon_hours=24, n=50, rng=rng_a)
    samples_b = outlook_b.sample("sivasagar", issue_time=t_eval, horizon_hours=24, n=50, rng=rng_b)

    assert np.allclose(samples_a, samples_b), "PersistenceDecayOutlook leaked data arriving after issue_time!"


def test_t6_outlook_causality_block_bootstrap():
    """T6: BlockBootstrapOutlook output at issue_time T is unchanged when future observations are altered."""
    t0 = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
    t_eval = t0 + timedelta(hours=36)

    outlook_a = BlockBootstrapOutlook(block_hours=6)
    outlook_b = BlockBootstrapOutlook(block_hours=6)

    # Ingest 48 hours of observations
    for h in range(48):
        t = t0 + timedelta(hours=h)
        obs_a = Observation(
            source="openmeteo_rain",
            source_kind=SourceKind.REAL,
            zone="sivasagar",
            system="river_embankment",
            value=float(h % 12),
            event_time=t,
            arrival_time=t,
        )
        outlook_a.ingest(obs_a)

        if obs_a.arrival_time > t_eval:
            obs_b = obs_a.model_copy(update={"value": 999.0})
        else:
            obs_b = obs_a
        outlook_b.ingest(obs_b)

    rng_a = np.random.default_rng(999)
    rng_b = np.random.default_rng(999)

    samples_a = outlook_a.sample("sivasagar", issue_time=t_eval, horizon_hours=24, n=30, rng=rng_a)
    samples_b = outlook_b.sample("sivasagar", issue_time=t_eval, horizon_hours=24, n=30, rng=rng_b)

    assert np.allclose(samples_a, samples_b), "BlockBootstrapOutlook leaked data arriving after issue_time!"
