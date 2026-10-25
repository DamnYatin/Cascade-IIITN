"""Phase 2 tests: Risk-state mapper, hysteresis, and snapshot serialization (T24, T25)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
import pytest

from backend.app.forecast.config import MapperConfig
from backend.app.forecast.mapper import RiskStateMapper
from backend.app.forecast.records import ForecastSnapshot
from backend.app.schemas import RiskState


def test_t24_mapper_monotonicity_and_immediate_escalation():
    """T24: Mapper state is monotone in probability; escalation from NORMAL to CRITICAL is immediate."""
    cfg = MapperConfig(
        p_crit72_watch=0.05,
        p_crit72_high=0.20,
        p_crit12_critical=0.50,
        min_dwell_steps=3,
    )
    mapper = RiskStateMapper(cfg)

    # 1. Monotonicity checks
    s_norm = mapper.raw_map(p_crit_72=0.02, p_crit_12=0.01)
    s_watch = mapper.raw_map(p_crit_72=0.08, p_crit_12=0.05)
    s_high = mapper.raw_map(p_crit_72=0.30, p_crit_12=0.10)
    s_crit = mapper.raw_map(p_crit_72=0.60, p_crit_12=0.55)

    assert s_norm == RiskState.NORMAL
    assert s_watch == RiskState.WATCH
    assert s_high == RiskState.HIGH_RISK
    assert s_crit == RiskState.CRITICAL

    # 2. Immediate escalation: entity starts NORMAL, suddenly receives surge -> immediate CRITICAL
    state, alert = mapper.update("zone_test", raw_p_crit_72=0.70, raw_p_crit_12=0.60)
    assert state == RiskState.CRITICAL, f"Escalation was delayed instead of immediate: {state}"


def test_t24_mapper_hysteresis_delays_deescalation():
    """T24: De-escalation requires min_dwell_steps (3) consecutive steps below threshold."""
    cfg = MapperConfig(
        p_crit72_watch=0.05,
        p_crit72_high=0.20,
        p_crit12_critical=0.50,
        min_dwell_steps=3,
    )
    mapper = RiskStateMapper(cfg)

    # Step 1: Escalate to HIGH_RISK
    s1, _ = mapper.update("z1", raw_p_crit_72=0.35, raw_p_crit_12=0.10)
    assert s1 == RiskState.HIGH_RISK

    # Step 2: Input drops to WATCH level for 1 step -> must REMAIN HIGH_RISK due to dwell requirement
    s2, _ = mapper.update("z1", raw_p_crit_72=0.10, raw_p_crit_12=0.02)
    assert s2 == RiskState.HIGH_RISK, "Flapped to WATCH immediately without waiting dwell time!"

    # Step 3: Input stays at WATCH level for 2nd step -> still HIGH_RISK
    s3, _ = mapper.update("z1", raw_p_crit_72=0.10, raw_p_crit_12=0.02)
    assert s3 == RiskState.HIGH_RISK

    # Step 4: Input stays at WATCH level for 3rd step -> dwell condition met, de-escalates to WATCH
    s4, _ = mapper.update("z1", raw_p_crit_72=0.10, raw_p_crit_12=0.02)
    assert s4 == RiskState.WATCH


def test_t25_snapshot_serialization_provenance_and_calibrated_false():
    """T25: Snapshot serialisation round-trips; calibrated=false everywhere; lists simulated systems."""
    t_now = datetime(2026, 7, 20, 14, 0, tzinfo=timezone.utc)
    snap = ForecastSnapshot(
        issued_at=t_now,
        city_id="upper_assam",
        city_risk_state=RiskState.HIGH_RISK,
        city_probabilities={"24": {"HIGH_RISK": 0.45}, "72": {"CRITICAL": 0.32}},
        zone_risk_states={"sivasagar": RiskState.HIGH_RISK, "charaideo": RiskState.WATCH},
        zone_probabilities={
            "sivasagar": {"24": {"HIGH_RISK": 0.48}, "72": {"CRITICAL": 0.35}},
            "charaideo": {"24": {"HIGH_RISK": 0.22}, "72": {"CRITICAL": 0.12}},
        },
        evidence_quality={"city": 0.82, "sivasagar": 0.88, "charaideo": 0.79},
        cascade_summary=[
            {"stage": 1, "node": "sivasagar:river_embankment", "eta_p50": 6.0, "dominant_parent": "mon_nl:river_embankment"}
        ],
        provenance_mix={
            "real_percentage": 25.0,
            "simulated_percentage": 75.0,
            "simulated_systems": ["transport", "power", "comms", "health", "emergency_response"],
            "real_streams": ["rain_openmeteo", "soil_openmeteo"],
        },
        disclosure_string="Real inputs: rain & soil moisture. Downstream systems simulated.",
        burn_in=True,
        calibrated=False,
        oracle=False,
        config_hash="abc123hash",
    )

    # 1. Assert calibrated is false
    assert snap.calibrated is False
    assert snap.burn_in is True

    # 2. Canonical serialization round-trip
    canon_json = snap.to_canonical_json()
    hash1 = snap.compute_forecast_hash()
    assert isinstance(canon_json, str)
    assert len(hash1) == 64

    # Reload from JSON
    loaded_dict = json.loads(canon_json)
    snap_reloaded = ForecastSnapshot.model_validate(loaded_dict)
    assert snap_reloaded.city_id == "upper_assam"
    assert snap_reloaded.calibrated is False
    assert snap_reloaded.compute_forecast_hash() == hash1

    # 3. Provenance mix lists simulated systems explicitly
    assert "simulated_systems" in snap.provenance_mix
    sim_sys = snap.provenance_mix["simulated_systems"]
    assert "power" in sim_sys
    assert "transport" in sim_sys
