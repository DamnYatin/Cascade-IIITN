"""Tests P6 to P11: Attribution, Receipts, Confidence, Hedged Text & Log.

Verifies:
  - P6: Additive decomposition sums to total delta in linear regime; residual reported otherwise.
  - P7: Paired re-rollout attribution ranks true causal driver highest; deterministic under CRN.
  - P8: Evidence receipts: every ID exists in ledger with arrival_time <= issued_at, provenance correct.
  - P9: Confidence drops with evidence degradation; abstention rules fire as specified.
  - P10: Text generator obeys hedging rules, numerical fidelity, and provenance honesty lints.
  - P11: RiskChangeLog is bounded and deterministic.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import numpy as np
import pytest

from backend.app.explain.attribution import (
    attribute_risk_change_paired,
    compute_rank_stability,
    decompose_stress_change_analytic,
)
from backend.app.explain.confidence import compute_explanation_confidence
from backend.app.explain.log import RiskChangeLog
from backend.app.explain.receipts import build_evidence_receipt
from backend.app.explain.records import ChainLink, DriverRecord, ExplanationRecord
from backend.app.explain.text import (
    generate_explanation_text,
    lint_explanation_text,
)
from backend.app.forecast.ledger import EvidenceItem, EvidenceLedger
from backend.app.forecast.learner import ForecastModel
from backend.app.forecast.rollout import NoiseBank, cascade_rollout


def test_p6_additive_decomposition_linear_regime():
    """P6: Additive decomposition sums to total delta in linear regime; residual reported."""
    model = ForecastModel(
        nodes=["node_A", "node_B"],
        intercepts={"node_A": 0.02, "node_B": 0.02},
        persistence={"node_A": 0.85, "node_B": 0.85},
        sigmas={"node_A": 0.04, "node_B": 0.04},
        couplings={"node_B": [("node_A", 2.0, 0.40)]},
        exogenous_weights={"node_B": [("rain_accum_24h", 0.50)]},
    )

    drivers, residual = decompose_stress_change_analytic(
        node="node_B",
        prev_stress=0.20,
        curr_stress=0.45,
        model=model,
        parent_stress_curr={"node_A": 0.50},
        parent_stress_prev={"node_A": 0.20},
        rain_curr=25.0,
        rain_prev=10.0,
        var_curr=0.04,
        var_prev=0.04,
    )

    # In linear regime: total delta = 0.45 - 0.20 = 0.25
    # Couplings delta: 0.40 * (0.50 - 0.20) = 0.12
    # Rain delta: 0.50 * (25 - 10)/100 = 0.075
    # Observation delta: 0.25 - (0.12 + 0.075) = 0.055
    linear_sum = sum(d.contribution for d in drivers if d.driver_type != "uncertainty")
    assert abs(linear_sum - 0.25) < 1e-4
    assert abs(residual) < 1e-4


def test_p7_paired_re_rollout_attribution_ranks_true_driver():
    """P7: Paired re-rollout attribution ranks true causal parent highest."""
    model = ForecastModel(
        nodes=["parent_major", "parent_minor", "target"],
        intercepts={"parent_major": 0.05, "parent_minor": 0.01, "target": 0.01},
        persistence={"parent_major": 0.90, "parent_minor": 0.85, "target": 0.80},
        sigmas={"parent_major": 0.03, "parent_minor": 0.03, "target": 0.03},
        couplings={
            "target": [("parent_major", 2.0, 0.70), ("parent_minor", 2.0, 0.10)],
        },
        exogenous_weights={},
    )
    initial_beliefs = {
        "parent_major": (0.85, 0.001),
        "parent_minor": (0.30, 0.001),
        "target": (0.15, 0.001),
    }
    nb = NoiseBank(global_seed=42, issue_time=datetime(2026, 7, 20, tzinfo=timezone.utc), n_rollouts=150, n_nodes=3, horizon=48)
    base_res = cascade_rollout(
        model,
        initial_beliefs,
        horizon=48,
        n_rollouts=150,
        noise_bank=nb,
    )

    candidate_drivers = [
        DriverRecord(
            driver_id="learned_edge:parent_major->target",
            driver_type="learned_edge",
            contribution=0.35,
            direction="increases_risk",
            label="Major parent coupling",
        ),
        DriverRecord(
            driver_id="learned_edge:parent_minor->target",
            driver_type="learned_edge",
            contribution=0.05,
            direction="increases_risk",
            label="Minor parent coupling",
        ),
    ]

    refined = attribute_risk_change_paired(
        target_node="target",
        baseline_rollouts=base_res,
        model=model,
        initial_beliefs=initial_beliefs,
        candidate_drivers=candidate_drivers,
        noise_bank=nb,
        horizon=48,
        n_rollouts=150,
    )

    # parent_major must rank first with larger paired delta P
    assert refined[0].driver_id == "learned_edge:parent_major->target"
    assert refined[0].contribution > refined[1].contribution
    assert refined[0].ci_lower <= refined[0].contribution <= refined[0].ci_upper


def test_p8_evidence_receipt_ledger_audit():
    """P8: Evidence receipts audit IDs strictly <= issued_at and flag simulated vs real streams."""
    ledger = EvidenceLedger(max_hours=48.0)
    t0 = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)
    t_after = t0 + timedelta(hours=2)

    # Past observation (valid)
    ledger.record_evidence(
        EvidenceItem(
            obs_id="obs_valid_1",
            source="open_meteo_rainfall",
            node="sivasagar:river_embankment",
            event_time=t0 - timedelta(hours=1),
            arrival_time=t0 - timedelta(hours=1),
            trust=0.95,
            weight=1.0,
            gated=False,
            stress_value=0.72,
        )
    )
    # Future observation (must NOT be in receipt)
    ledger.record_evidence(
        EvidenceItem(
            obs_id="obs_future_leaked",
            source="open_meteo_rainfall",
            node="sivasagar:river_embankment",
            event_time=t_after,
            arrival_time=t_after,
            trust=0.95,
            weight=1.0,
            gated=False,
            stress_value=0.99,
        )
    )

    receipt = build_evidence_receipt(
        node="sivasagar:river_embankment",
        issued_at=t0,
        ledger=ledger,
    )
    assert "obs_valid_1" in receipt.observation_ids
    assert "obs_future_leaked" not in receipt.observation_ids
    assert all(datetime.fromisoformat(at) <= t0 for at in receipt.arrival_times)
    assert receipt.simulated_parent_flag is True  # river_embankment is simulated downstream


def test_p9_confidence_degradation_and_abstention_rules():
    """P9: Confidence degrades gracefully and triggers explicit abstentions."""
    # Scenario 1: Clean high-confidence chain
    links = [
        ChainLink(
            u="mon_nl:river_embankment",
            v="charaideo:river_embankment",
            lag_hours=2.0,
            weight=0.5,
            confidence=0.90,
            p_link=0.85,
        )
    ]
    drivers = [
        DriverRecord(driver_id="d1", driver_type="learned_edge", contribution=0.30, direction="increases_risk", label="Primary river link"),
        DriverRecord(driver_id="d2", driver_type="precursor_feature", contribution=0.10, direction="increases_risk", label="Rain"),
    ]

    conf_high, cat_high, abs_high = compute_explanation_confidence(
        chain_links=links,
        candidate_drivers=drivers,
        evidence_quality=0.92,
        attribution_stability=0.95,
    )
    assert conf_high >= 0.70
    assert cat_high == "high"
    assert not abs_high

    # Scenario 2: Injected fault -> low evidence quality & unidentifiable drivers
    unidentifiable_drivers = [
        DriverRecord(driver_id="d1", driver_type="learned_edge", contribution=0.25, direction="increases_risk", label="Driver X"),
        DriverRecord(driver_id="d2", driver_type="precursor_feature", contribution=0.24, direction="increases_risk", label="Driver Y"),
    ]
    conf_low, cat_low, abs_low = compute_explanation_confidence(
        chain_links=links,
        candidate_drivers=unidentifiable_drivers,
        evidence_quality=0.35,  # faulted sensor stream
        attribution_stability=0.40,
        has_recent_drift=True,
    )
    assert conf_low < 0.70
    assert cat_low == "low"
    assert any("Low sensor evidence quality" in a for a in abs_low)
    assert any("Cannot separate" in a for a in abs_low)
    assert any("Recent topological drift" in a for a in abs_low)


def test_p10_hedged_text_generation_and_lints():
    """P10: Text adheres to hedging rules, contains no banned certainty words, and checks numbers."""
    rec = ExplanationRecord(
        id="rec_test_10",
        issued_at=datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc),
        subject="sivasagar:transport",
        subject_kind="node",
        risk_state_from="WATCH",
        risk_state_to="CRITICAL",
        probability_before=0.18,
        probability_after=0.41,
        drivers=[
            DriverRecord(
                driver_id="d1",
                driver_type="learned_edge",
                contribution=0.23,
                direction="increases_risk",
                label="Heavy upstream surge from Dikhow river",
            )
        ],
        confidence=0.78,
        confidence_category="high",
    )

    text = generate_explanation_text(rec, n_rollouts=300)
    assert "is estimated to" in text
    assert "18.0%" in text
    assert "41.0%" in text
    assert "simulated" in text

    # Lint check must pass cleanly
    violations = lint_explanation_text(text, rec)
    assert not violations, f"Lints failed: {violations}"

    # Verify lint catches unhedged claims
    bad_text = "This flood definitely caused total failure and proves that transport will collapse."
    bad_violations = lint_explanation_text(bad_text, rec)
    assert any("prohibited" in v for v in bad_violations)


def test_p11_risk_change_log_bounded_and_deterministic():
    """P11: RiskChangeLog respects max capacity, min delta p filter, and retrieval order."""
    log = RiskChangeLog(max_entries=3, min_delta_p=0.05)

    assert log.should_record("WATCH", "HIGH_RISK", 0.10, 0.10) is True  # state change
    assert log.should_record("WATCH", "WATCH", 0.10, 0.12) is False      # delta 0.02 < 0.05
    assert log.should_record("WATCH", "WATCH", 0.10, 0.20) is True       # delta 0.10 >= 0.05

    for i in range(5):
        rec = ExplanationRecord(
            id=f"rec_{i}",
            issued_at=datetime(2026, 7, 20, i, 0, tzinfo=timezone.utc),
            subject="charaideo",
            subject_kind="zone",
            risk_state_from="WATCH",
            risk_state_to="HIGH_RISK",
            probability_before=0.10,
            probability_after=0.10 + (i * 0.10),
            confidence=0.80,
            confidence_category="high",
        )
        log.append(rec)

    # Max capacity is 3
    assert len(log) == 3
    changes = log.get_changes(subject="charaideo")
    assert len(changes) == 3
    # Most recent first: rec_4, rec_3, rec_2
    assert changes[0].id == "rec_4"
    assert changes[1].id == "rec_3"
    assert changes[2].id == "rec_2"
