"""Phase 2 tests: Causal normalization, features, ledger, and isolation."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
import pytest

from backend.app.city_config import load_city_config
from backend.app.forecast.config import load_forecast_config, ForecastConfig
from backend.app.forecast.features import (
    CausalStressNormalizer,
    CausalExogenousFeatureBuilder,
    get_city_nodes,
    is_upstream_driver,
)
from backend.app.forecast.ledger import EvidenceItem, EvidenceLedger
from backend.app.schemas import Observation, QualityFlag, SourceKind
from tests.conftest import REPO


UPPER_ASSAM_YAML = REPO / "configs" / "upper_assam.yaml"
NORTH_BANK_YAML = REPO / "configs" / "north_bank_assam.yaml"


def test_forecast_config_loads_defaults():
    cfg = load_forecast_config(REPO / "configs" / "forecast.yaml")
    assert cfg.step_hours == 1
    assert cfg.horizons_hours == [1, 3, 6, 12, 24, 48, 72]
    assert cfg.rollouts == 300
    assert cfg.stress_levels.watch == 0.40
    assert cfg.stress_levels.high_risk == 0.60
    assert cfg.stress_levels.critical == 0.80
    assert cfg.candidate_lags_hours == [1, 2, 3, 6, 12, 24]


def test_causal_normalization_future_isolation(upper_assam_config):
    """T4: Mutating data with arrival_time > T does NOT alter normalized values at or before T."""
    t0 = upper_assam_config.start_time_utc
    t_cutoff = t0 + timedelta(hours=10)

    normalizer_a = CausalStressNormalizer(upper_assam_config)
    normalizer_b = CausalStressNormalizer(upper_assam_config)

    # Stream of 20 observations (one per hour)
    obs_list = []
    for h in range(20):
        t = t0 + timedelta(hours=h)
        obs_list.append(
            Observation(
                source="sensor_1",
                source_kind=SourceKind.SIMULATED,
                zone="sivasagar",
                system="river_embankment",
                value=10.0 + h * 2.0,
                event_time=t,
                arrival_time=t + timedelta(minutes=15),
            )
        )

    # Run normalizer_a with true observations
    res_a = []
    for o in obs_list:
        normalizer_a.update_history(o)
        if o.arrival_time <= t_cutoff:
            s, m = normalizer_a.normalize(o, clock_time=t_cutoff)
            res_a.append((o.obs_id, s, m))

    # Run normalizer_b with corruptions AFTER t_cutoff
    res_b = []
    for o in obs_list:
        if o.arrival_time > t_cutoff:
            o_corrupt = o.model_copy(update={"value": 99999.0})
            normalizer_b.update_history(o_corrupt)
        else:
            normalizer_b.update_history(o)
            s, m = normalizer_b.normalize(o, clock_time=t_cutoff)
            res_b.append((o.obs_id, s, m))

    assert res_a == res_b, "Causal normalization leaked future data!"


def test_causal_exogenous_features_future_isolation(upper_assam_config):
    """T4: Exogenous feature builder at T is identical when future data is corrupted."""
    t0 = upper_assam_config.start_time_utc
    t_eval = t0 + timedelta(hours=12)

    builder_a = CausalExogenousFeatureBuilder(upper_assam_config)
    builder_b = CausalExogenousFeatureBuilder(upper_assam_config)

    # Ingest 24 hours of rain and soil observations
    for h in range(24):
        t = t0 + timedelta(hours=h)
        rain_obs = Observation(
            source="openmeteo_rain",
            source_kind=SourceKind.REAL,
            zone="sivasagar",
            system="river_embankment",
            value=5.0 if h < 12 else 50.0,
            event_time=t,
            arrival_time=t + timedelta(hours=1),
        )
        soil_obs = Observation(
            source="openmeteo_soil",
            source_kind=SourceKind.REAL,
            zone="sivasagar",
            system="river_embankment",
            value=0.35 if h < 12 else 0.85,
            event_time=t,
            arrival_time=t + timedelta(hours=1),
        )
        builder_a.ingest(rain_obs)
        builder_a.ingest(soil_obs)

        # For builder_b, corrupt observations where arrival_time > t_eval
        if rain_obs.arrival_time > t_eval:
            rain_corrupt = rain_obs.model_copy(update={"value": 9999.0})
            soil_corrupt = soil_obs.model_copy(update={"value": 1.0})
            builder_b.ingest(rain_corrupt)
            builder_b.ingest(soil_corrupt)
        else:
            builder_b.ingest(rain_obs)
            builder_b.ingest(soil_obs)

    feats_a, masks_a = builder_a.get_features("sivasagar", clock_time=t_eval)
    feats_b, masks_b = builder_b.get_features("sivasagar", clock_time=t_eval)

    assert masks_a == masks_b
    for k in feats_a:
        if math.isnan(feats_a[k]):
            assert math.isnan(feats_b[k])
        else:
            assert feats_a[k] == pytest.approx(feats_b[k])


def test_evidence_ledger_bounded_and_retrieves_ids():
    ledger = EvidenceLedger(max_hours=48.0, max_items_per_node=100)
    t0 = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)

    # Record 60 hourly items
    for h in range(60):
        t = t0 + timedelta(hours=h)
        item = EvidenceItem(
            obs_id=f"obs_{h}",
            source="openmeteo",
            node="sivasagar:river_embankment",
            event_time=t,
            arrival_time=t + timedelta(minutes=10),
            trust=0.9,
            weight=1.0,
            gated=(h % 10 == 0),
            stress_value=0.5,
        )
        ledger.record_evidence(item)

    # Prune at t0 + 60h (max_hours = 48)
    ledger.prune(t0 + timedelta(hours=60))

    # Evidence for should only include within window
    now = t0 + timedelta(hours=60)
    ev = ledger.evidence_for("sivasagar:river_embankment", now, window_hours=6.0)
    assert len(ev) <= 7

    # Evidence IDs for prediction (ungated)
    ids = ledger.evidence_ids_for_prediction("sivasagar:river_embankment", now, window_hours=24.0, max_ids=5)
    assert len(ids) == 5
    assert all(not id_.endswith("_0") for id_ in ids)  # h % 10 == 0 are gated


def test_get_city_nodes_upper_and_north_bank(upper_assam_config, north_bank_config):
    nodes_ua = get_city_nodes(upper_assam_config)
    nodes_nb = get_city_nodes(north_bank_config)

    # 7 core Assam zones have 6 systems (42), 3 upstream Nagaland zones have 3 systems (9) -> 51 nodes
    assert len(nodes_ua) == 51
    assert len(nodes_nb) == 30  # 6 zones x 5 systems

    assert is_upstream_driver("mon_nl", upper_assam_config)
    assert not is_upstream_driver("sivasagar", upper_assam_config)
