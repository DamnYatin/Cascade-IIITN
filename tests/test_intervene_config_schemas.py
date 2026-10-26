"""Tests P12 and Schema Serialization: Interventions Config, Actions, and Records.

Verifies:
  - P12: Config validation (bad actions fail with clear errors; missing-system actions
    are skipped with warnings; both cities load without code changes).
  - Schema roundtrip and canonical serialization determinism (sorted keys, rounded floats).
  - Assumptions Register extraction and provenance tagging.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import pytest
import yaml

from backend.app.city_config import load_city_config
from backend.app.explain.records import (
    ChainLink,
    DriverRecord,
    EvidenceReceipt,
    ExplanationRecord,
    CascadeLoop,
    ConcurrentCluster,
)
from backend.app.intervene.actions import (
    build_assumptions_register,
    filter_actions_for_city,
    instantiate_action,
    load_interventions_config,
    resolve_patches_for_instance,
    InterventionsConfig,
)
from backend.app.intervene.records import (
    Action,
    ActionInstance,
    Assumption,
    EffectPatch,
    InterventionPlan,
    PatchType,
    PlanOutcome,
    ProvenanceType,
    ResourceUse,
    SideEffect,
)
from tests.conftest import REPO


def test_p12_interventions_config_loads_and_validates():
    """P12: interventions.yaml loads, validates all schema fields, and extracts non-empty actions."""
    cfg_path = REPO / "configs" / "interventions.yaml"
    cfg = load_interventions_config(cfg_path)

    assert cfg.version == "1.0.0"
    assert len(cfg.actions) >= 10
    assert "crews" in cfg.default_budgets
    assert "cost_lakh" in cfg.default_budgets

    action_ids = [a.id for a in cfg.actions]
    assert "deploy_dewatering_pumps" in action_ids
    assert "embankment_sandbagging" in action_ids
    assert "traffic_diversion" in action_ids
    assert "staged_population_evacuation" in action_ids


def test_p12_both_city_configs_load_actions_with_missing_system_skipped(caplog):
    """P12: Filter actions against upper_assam and north_bank_assam; missing systems skipped with warnings."""
    cfg = load_interventions_config(REPO / "configs" / "interventions.yaml")

    # Upper Assam has: river_embankment, transport, emergency_response, power, comms, health
    upper_city = load_city_config(REPO / "configs" / "upper_assam.yaml")
    upper_systems = [s.id for s in upper_city.systems]
    upper_actions = filter_actions_for_city(cfg.actions, upper_systems)
    assert len(upper_actions) == 10  # All 10 supported

    # North Bank Assam lacks 'comms'
    nb_city = load_city_config(REPO / "configs" / "north_bank_assam.yaml")
    nb_systems = [s.id for s in nb_city.systems]
    assert "comms" not in nb_systems

    with caplog.at_level("WARNING"):
        nb_actions = filter_actions_for_city(cfg.actions, nb_systems)

    # mobile_comms_tower requires comms, so it should be skipped
    nb_ids = [a.id for a in nb_actions]
    assert "mobile_comms_tower" not in nb_ids
    assert len(nb_actions) == 9
    assert any("mobile_comms_tower" in rec.message for rec in caplog.records)


def test_p12_invalid_action_config_raises_error(tmp_path):
    """P12: Malformed action definitions fail validation with descriptive errors."""
    bad_yaml = {
        "version": "1.0.0",
        "actions": [
            {
                "id": "broken_action",
                "name": "Missing systems and patches",
                # missing required fields
            }
        ]
    }
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.dump(bad_yaml), encoding="utf-8")

    with pytest.raises(ValueError, match="Validation error"):
        load_interventions_config(p)


def test_assumptions_register_extraction():
    """Assumptions Register properly records all action parameters, costs, and provenance."""
    cfg = load_interventions_config(REPO / "configs" / "interventions.yaml")
    assumptions = build_assumptions_register(cfg)

    assert len(assumptions) > 20
    assert any(a.parameter_id == "deploy_dewatering_pumps.activation_delay" for a in assumptions)
    assert any("sandbagging" in a.action_id for a in assumptions)
    for a in assumptions:
        assert isinstance(a.assumed_value, float)
        assert len(a.uncertainty_range) == 2
        assert a.uncertainty_range[0] <= a.assumed_value <= a.uncertainty_range[1]
        assert a.provenance in (ProvenanceType.ASSUMED, ProvenanceType.EXPERT_ESTIMATE_NEEDED, ProvenanceType.GROUNDED_CATEGORY)


def test_action_instantiation_and_zone_resolution():
    """ActionInstance binds zone and resolves target templates."""
    cfg = load_interventions_config(REPO / "configs" / "interventions.yaml")
    action = next(a for a in cfg.actions if a.id == "traffic_diversion")

    instance = instantiate_action(action, zone="sivasagar", start_time_offset=2.0, units=1)
    assert instance.zone == "sivasagar"
    assert instance.start_time_offset == 2.0
    assert instance.resource_costs["crews"] == 2.0

    b_patches, s_patches = resolve_patches_for_instance(action, instance)
    assert len(b_patches) == 1
    assert b_patches[0].u == "sivasagar:river_embankment"
    assert b_patches[0].v == "sivasagar:transport"
    assert len(s_patches) == 1
    assert s_patches[0].target == "sivasagar:emergency_response"


def test_schema_canonical_serialization_determinism():
    """Canonical dict and json export are deterministic and float-rounded."""
    link = ChainLink(
        u="mon_nl:river_embankment",
        v="charaideo:river_embankment",
        lag_hours=1.5000001,
        weight=0.4500002,
        confidence=0.9500003,
        p_link=0.8800004,
    )
    d = link.canonical_dict()
    assert d["lag_hours"] == 1.5
    assert d["weight"] == 0.45
    assert d["confidence"] == 0.95

    now = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    rec = ExplanationRecord(
        id="test_rec_123",
        issued_at=now,
        subject="upper_assam",
        subject_kind="city",
        risk_state_from="WATCH",
        risk_state_to="CRITICAL",
        probability_before=0.150001,
        probability_after=0.620002,
        confidence=0.85,
        confidence_category="high",
        text="Heavy rainfall estimated to elevate embankment risk.",
    )
    h1 = rec.compute_hash()
    h2 = rec.compute_hash()
    assert h1 == h2
    assert len(h1) == 64
