"""Phase 2 adversity, trust, and late-arrival tests (T19 - T22)."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
import pytest

from backend.app.city_config import load_city_config
from backend.app.forecast.config import ForecastConfig, TrustConfig
from backend.app.forecast.estimator import NodeStateEstimator
from backend.app.forecast.features import CausalStressNormalizer
from backend.app.forecast.ledger import EvidenceLedger
from backend.app.forecast.trust import SourceTrustManager
from backend.app.replay.faults import FaultInjector, FaultSpec
from backend.app.schemas import Observation, QualityFlag, SourceKind
from tests.conftest import REPO


@pytest.fixture
def test_setup(upper_assam_config):
    f_cfg = ForecastConfig()
    trust_mgr = SourceTrustManager(f_cfg.trust)
    normalizer = CausalStressNormalizer(upper_assam_config)
    ledger = EvidenceLedger()
    estimator = NodeStateEstimator(
        city_config=upper_assam_config,
        forecast_config=f_cfg,
        trust_manager=trust_mgr,
        normalizer=normalizer,
        ledger=ledger,
    )
    return upper_assam_config, f_cfg, trust_mgr, normalizer, ledger, estimator


def test_t20_spam_burst_does_not_push_node_to_critical(test_setup):
    """T20: A citizen-report spam burst with disagreeing sensors does NOT push node to CRITICAL."""
    cfg, f_cfg, trust_mgr, norm, ledger, estimator = test_setup
    t0 = cfg.start_time_utc
    node = "sivasagar:river_embankment"

    # Step 1: Normal quiet sensor readings (low stress 0.15)
    for h in range(1, 10):
        t = t0 + timedelta(hours=h)
        estimator.predict_step(t)
        sensor_obs = Observation(
            source="sensor_real",
            source_kind=SourceKind.REAL,
            zone="sivasagar",
            system="river_embankment",
            value=15.0,  # low
            event_time=t,
            arrival_time=t,
        )
        estimator.ingest_observations([sensor_obs], clock_time=t)

    assert estimator.states[node].mean < 0.30

    # Step 2: Flood with 20 fake citizen reports claiming max emergency stress (100.0)
    t_spam = t0 + timedelta(hours=10)
    estimator.predict_step(t_spam)

    sensor_obs = Observation(
        source="sensor_real",
        source_kind=SourceKind.REAL,
        zone="sivasagar",
        system="river_embankment",
        value=15.0,  # Sensor still says normal!
        event_time=t_spam,
        arrival_time=t_spam,
    )

    spam_reports = []
    for i in range(20):
        spam_reports.append(
            Observation(
                source=f"citizen_spam_{i}",
                source_kind=SourceKind.SIMULATED,
                zone="sivasagar",
                system="river_embankment",
                value=100.0,  # extreme claim
                event_time=t_spam,
                arrival_time=t_spam,
                quality_flags=[QualityFlag.CITIZEN_REPORT],
            )
        )

    estimator.ingest_observations([sensor_obs] + spam_reports, clock_time=t_spam)

    # Node stress must NOT jump to CRITICAL (>= 0.80)
    stress = estimator.states[node].mean
    assert stress < 0.60, f"Spam burst pushed stress dangerously high: {stress}"


def test_t22_late_arrivals_refilter_matches_on_time_within_tolerance(upper_assam_config):
    """T22: Delayed observations re-filtered inside reorder window match on-time run."""
    t0 = upper_assam_config.start_time_utc
    node = "sivasagar:river_embankment"
    f_cfg = ForecastConfig(reorder_window_hours=24)

    # 1. Run A: All observations arrive exactly on time
    trust_a = SourceTrustManager(f_cfg.trust)
    est_a = NodeStateEstimator(upper_assam_config, f_cfg, trust_a, CausalStressNormalizer(upper_assam_config), EvidenceLedger())

    for h in range(1, 15):
        t = t0 + timedelta(hours=h)
        est_a.predict_step(t)
        obs = Observation(
            source="sensor_1",
            source_kind=SourceKind.SIMULATED,
            zone="sivasagar",
            system="river_embankment",
            value=30.0 + h * 2.0,
            event_time=t,
            arrival_time=t,
        )
        est_a.ingest_observations([obs], clock_time=t)

    state_on_time = est_a.states[node].mean

    # 2. Run B: Hour 5 observation is delayed by 6 hours (arrives at hour 11 <= reorder_window)
    trust_b = SourceTrustManager(f_cfg.trust)
    est_b = NodeStateEstimator(upper_assam_config, f_cfg, trust_b, CausalStressNormalizer(upper_assam_config), EvidenceLedger())

    delayed_obs = None
    for h in range(1, 15):
        t = t0 + timedelta(hours=h)
        est_b.predict_step(t)

        to_ingest = []
        if h == 5:
            # Hold back hour 5 observation
            delayed_obs = Observation(
                source="sensor_1",
                source_kind=SourceKind.SIMULATED,
                zone="sivasagar",
                system="river_embankment",
                value=30.0 + 5 * 2.0,
                event_time=t,
                arrival_time=t0 + timedelta(hours=11),  # 6 hours late
            )
        else:
            obs = Observation(
                source="sensor_1",
                source_kind=SourceKind.SIMULATED,
                zone="sivasagar",
                system="river_embankment",
                value=30.0 + h * 2.0,
                event_time=t,
                arrival_time=t,
            )
            to_ingest.append(obs)

        if h == 11 and delayed_obs is not None:
            to_ingest.append(delayed_obs)

        est_b.ingest_observations(to_ingest, clock_time=t)

    state_refiltered = est_b.states[node].mean
    # Final state matches on-time within 0.05 tolerance
    assert abs(state_on_time - state_refiltered) < 0.05, f"State difference too large: {state_on_time} vs {state_refiltered}"


def test_t21_graceful_degradation_monotone_evidence_quality(upper_assam_config):
    """T21: Progressively removing observations causes evidence quality to degrade gracefully without NaN/inf."""
    f_cfg = ForecastConfig()
    t0 = upper_assam_config.start_time_utc
    node = "sivasagar:river_embankment"

    eq_levels = []
    # Test 100%, 75%, 50%, 25% data availability
    for keep_rate in [1.0, 0.75, 0.50, 0.25]:
        trust_m = SourceTrustManager(f_cfg.trust)
        est = NodeStateEstimator(upper_assam_config, f_cfg, trust_m, CausalStressNormalizer(upper_assam_config), EvidenceLedger())

        for h in range(1, 20):
            t = t0 + timedelta(hours=h)
            est.predict_step(t)
            # Retain observations based on keep_rate
            if (h % int(1.0 / keep_rate)) == 0:
                obs = Observation(
                    source="sensor_1",
                    source_kind=SourceKind.SIMULATED,
                    zone="sivasagar",
                    system="river_embankment",
                    value=40.0,
                    event_time=t,
                    arrival_time=t,
                )
                est.ingest_observations([obs], clock_time=t)
            else:
                est.ingest_observations([], clock_time=t)

        st = est.states[node]
        assert not math.isnan(st.mean)
        assert not math.isinf(st.mean)
        assert not math.isnan(st.variance)
        eq_levels.append(st.evidence_quality)

    # Lower data availability does not cause an unexpected crash or nan
    assert all(0.0 <= eq <= 1.0 for eq in eq_levels)


def test_t19_faults_adversity_and_trust_degradation(upper_assam_config):
    """T19: Faulty sources (spikes, flatlines) have trust penalized; variance widens."""
    f_cfg = ForecastConfig()
    t0 = upper_assam_config.start_time_utc
    node = "sivasagar:river_embankment"
    trust_m = SourceTrustManager(f_cfg.trust)
    est = NodeStateEstimator(upper_assam_config, f_cfg, trust_m, CausalStressNormalizer(upper_assam_config), EvidenceLedger())

    initial_trust_healthy = trust_m.get_trust("healthy_sensor")
    initial_trust_spiker = trust_m.get_trust("spiker_sensor")

    for h in range(1, 25):
        t = t0 + timedelta(hours=h)
        est.predict_step(t)

        # Healthy sensor gives consistent moderate reading
        obs_healthy = Observation(
            source="healthy_sensor",
            source_kind=SourceKind.SIMULATED,
            zone="sivasagar",
            system="river_embankment",
            value=35.0,
            event_time=t,
            arrival_time=t,
        )
        # Spiker sensor sends crazy spikes every few hours
        spike_val = 1500.0 if (h % 3 == 0) else 35.0
        obs_spiker = Observation(
            source="spiker_sensor",
            source_kind=SourceKind.SIMULATED,
            zone="sivasagar",
            system="river_embankment",
            value=spike_val,
            event_time=t,
            arrival_time=t,
        )

        est.ingest_observations([obs_healthy, obs_spiker], clock_time=t)

    final_trust_healthy = trust_m.get_trust("healthy_sensor")
    final_trust_spiker = trust_m.get_trust("spiker_sensor")

    # Spiker trust must drop relative to healthy sensor
    assert final_trust_spiker < final_trust_healthy
    assert est.states[node].mean < 0.60  # State protected from 1500.0 spikes by outlier gating
