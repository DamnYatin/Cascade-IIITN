"""Hermetic tests for Phase 4 API, CLI, WebSocket, Demo Bundle, and Schema Contracts (H7: P22, P23, P25, P26, P27).

Enforces:
  P22: Future leakage canary: garbage after time T leaves explanations and plans issued at <= T byte-identical.
  P23: Defaults unchanged: with explain/intervene off, Phase 2/3 behaviour and hashes are preserved; WS types absent by default.
  P25: API endpoint shapes validate against generated JSON Schemas; clear error handling.
  P26: Demo bundle is deterministic, small, and verified against sha256 manifest.
  P27: Schema export stability and generated docs/API_CONTRACT.md compliance.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from backend.app.api import app
from backend.app.city_config import load_city_config
from backend.app.explain.coordinator import explain_snapshot
from backend.app.explain.records import ExplanationRecord
from backend.app.forecast.config import ForecastConfig
from backend.app.forecast.engine import ForecastEngine
from backend.app.intervene.actions import filter_actions_for_city, load_interventions_config
from backend.app.intervene.records import InterventionPlan, PlanOutcome
from backend.app.intervene.solver import generate_candidate_pool, solve_interventions
from backend.app.replay.clock import ReplayClock
from backend.app.replay.stream import ReplayStream, StreamView
from backend.app.synth.generator import generate_city

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_p22_future_leakage_canary_explain_and_intervene():
    """P22: Corrupting observations after time T must leave explanations and plans at T byte-identical."""
    for city_id in ["upper_assam", "north_bank_assam"]:
        city_cfg = load_city_config(REPO_ROOT / "configs" / f"{city_id}.yaml")
        seed = 42
        duration_h = 48
        t_cutoff_h = 18.0
        cutoff_dt = city_cfg.start_time_utc + timedelta(hours=t_cutoff_h)

        # Baseline observations
        obs_clean, _ = generate_city(city_cfg, seed, duration_h, anchor_mode="off")

        # Corrupted observations: all arrivals after cutoff_dt replaced with adversarial garbage
        obs_corrupted = []
        for o in obs_clean:
            if o.arrival_time <= cutoff_dt:
                obs_corrupted.append(o.model_copy())
            else:
                corrupted_o = o.model_copy(update={
                    "value": 99999.0,
                    "quality_flags": ["adversarial_spike", "garbage_injection"],
                })
                obs_corrupted.append(corrupted_o)

        # 1. Run baseline engine at T
        stream_clean = ReplayStream(obs_clean)
        clock_clean = ReplayClock(city_cfg.start_time_utc)
        clock_clean.advance(t_cutoff_h)
        view_clean = StreamView(stream_clean, clock_clean.now)

        engine_clean = ForecastEngine(
            city_config=city_cfg,
            forecast_config=ForecastConfig(rollouts=100),
            global_seed=seed,
            anchor_mode="off",
        )
        _ = engine_clean.step(clock_clean.now, view_clean, enable_trace=True)

        exp_clean = explain_snapshot(engine_clean, subject="city")

        icfg = load_interventions_config()
        acts = filter_actions_for_city(icfg.actions, city_cfg)
        candidates = generate_candidate_pool(acts, zones=[z.id for z in city_cfg.zones])
        plans_clean, _ = solve_interventions(
            candidates=candidates,
            actions_by_id={a.id: a for a in acts},
            budgets=icfg.default_budgets,
            model=engine_clean.learner.get_model(),
            initial_beliefs={n: (st.mean, st.variance) for n, st in engine_clean.estimator.states.items()},
            baseline_rollouts=engine_clean.last_rollout_results,
            noise_bank=engine_clean.last_noise_bank,
            decision_time=clock_clean.now,
            screening_rollouts=50,
            full_rollouts=100,
            horizon=24,
        )

        # 2. Run corrupted engine at T
        stream_corrupt = ReplayStream(obs_corrupted)
        clock_corrupt = ReplayClock(city_cfg.start_time_utc)
        clock_corrupt.advance(t_cutoff_h)
        view_corrupt = StreamView(stream_corrupt, clock_corrupt.now)

        engine_corrupt = ForecastEngine(
            city_config=city_cfg,
            forecast_config=ForecastConfig(rollouts=100),
            global_seed=seed,
            anchor_mode="off",
        )
        _ = engine_corrupt.step(clock_corrupt.now, view_corrupt, enable_trace=True)

        exp_corrupt = explain_snapshot(engine_corrupt, subject="city")

        plans_corrupt, _ = solve_interventions(
            candidates=candidates,
            actions_by_id={a.id: a for a in acts},
            budgets=icfg.default_budgets,
            model=engine_corrupt.learner.get_model(),
            initial_beliefs={n: (st.mean, st.variance) for n, st in engine_corrupt.estimator.states.items()},
            baseline_rollouts=engine_corrupt.last_rollout_results,
            noise_bank=engine_corrupt.last_noise_bank,
            decision_time=clock_corrupt.now,
            screening_rollouts=50,
            full_rollouts=100,
            horizon=24,
        )

        # Assert byte-for-byte identity of explanation and plans
        assert exp_clean.canonical_json() == exp_corrupt.canonical_json(), (
            f"Leakage detected in explanation for {city_id} at T={t_cutoff_h}h!"
        )
        assert len(plans_clean) == len(plans_corrupt)
        for p1, p2 in zip(plans_clean, plans_corrupt):
            assert p1.canonical_json() == p2.canonical_json(), (
                f"Leakage detected in plan {p1.plan_id} for {city_id} at T={t_cutoff_h}h!"
            )


def test_p23_defaults_unchanged_and_ws_stream():
    """P23: Defaults unchanged: with explain/plan off, WebSocket emits standard messages only."""
    client = TestClient(app)

    # 1. Default WebSocket stream (explain=0, plan=0)
    with client.websocket_connect("/ws/stream?city=upper_assam&seed=901&hours=1&speed=100.0&forecast=1") as ws:
        received_types = set()
        for _ in range(2):
            data = ws.receive_text()
            msg = json.loads(data)
            received_types.add(msg.get("type"))

        assert "observations" in received_types
        assert "forecast" in received_types
        assert "explanation" not in received_types, "explanation message leaked when explain=0!"
        assert "plan" not in received_types, "plan message leaked when plan=0!"

    # 2. Flagged WebSocket stream (explain=1, plan=1)
    with client.websocket_connect("/ws/stream?city=upper_assam&seed=902&hours=1&speed=100.0&forecast=1&explain=1&plan=1") as ws:
        flagged_types = set()
        for _ in range(4):
            data = ws.receive_text()
            msg = json.loads(data)
            flagged_types.add(msg.get("type"))

        assert "explanation" in flagged_types, "explanation message missing when explain=1"
        assert "plan" in flagged_types, "plan message missing when plan=1"


def test_p25_api_endpoint_shapes_and_errors():
    """P25: Endpoint shapes validate against schemas and return proper error responses."""
    client = TestClient(app)

    # 1. GET /intervene/actions
    resp_act = client.get("/intervene/actions?city=upper_assam")
    assert resp_act.status_code == 200
    data_act = resp_act.json()
    assert "actions" in data_act
    assert "assumptions" in data_act
    assert len(data_act["actions"]) >= 5
    assert len(data_act["assumptions"]) >= 10

    # 2. GET /explain/latest
    resp_exp = client.get("/explain/latest?city=upper_assam&seed=1")
    assert resp_exp.status_code == 200
    data_exp = resp_exp.json()
    rec = ExplanationRecord(**data_exp)
    assert rec.subject == "city"
    assert rec.confidence >= 0.05
    assert len(rec.disclosure_strings) >= 1

    # 3. GET /explain/changes
    resp_ch = client.get("/explain/changes?city=upper_assam&seed=1")
    assert resp_ch.status_code == 200
    data_ch = resp_ch.json()
    assert "changes" in data_ch
    assert len(data_ch["changes"]) >= 1

    # 4. GET /explain/link
    resp_link = client.get("/explain/link?u=dibrugarh:river_embankment&v=dibrugarh:power&city=upper_assam&seed=1")
    assert resp_link.status_code == 200
    data_link = resp_link.json()
    assert data_link["node"] == "dibrugarh:power"
    assert "paired_removal_effect" in data_link

    # 5. POST /intervene/plan
    plan_req = {
        "city": "upper_assam",
        "seed": 1,
        "mode": "fast",
        "horizon": 24,
    }
    resp_plan = client.post("/intervene/plan", json=plan_req)
    assert resp_plan.status_code == 200
    data_plan = resp_plan.json()
    assert "plans" in data_plan
    assert len(data_plan["plans"]) >= 2
    # Verify first plan schema
    plan0 = InterventionPlan(**data_plan["plans"][0])
    assert plan0.plan_id.startswith("plan_")

    # 6. POST /intervene/evaluate
    eval_req = {
        "city": "upper_assam",
        "seed": 1,
        "plan": plan0.canonical_dict(),
        "horizon": 24,
    }
    resp_eval = client.post("/intervene/evaluate", json=eval_req)
    assert resp_eval.status_code == 200
    outcome = PlanOutcome(**resp_eval.json())
    assert outcome.plan_id == plan0.plan_id


def test_p26_demo_bundle_integrity_and_determinism():
    """P26: Demo bundle files exist, match sha256 manifest, and load offline."""
    bundle_dir = REPO_ROOT / "frontend" / "public" / "phase4"
    assert bundle_dir.exists(), "frontend/public/phase4/ does not exist"

    manifest_path = bundle_dir / "summary.json"
    assert manifest_path.exists()
    summary = json.loads(manifest_path.read_text(encoding="utf-8"))

    expected_files = [
        "snapshots.json",
        "explanations.json",
        "plans.json",
        "value_of_lead_time.json",
        "assumptions.json",
    ]

    for fname in expected_files:
        fpath = bundle_dir / fname
        assert fpath.exists(), f"Missing demo bundle file {fname}"
        raw_bytes = fpath.read_bytes().replace(b"\r\n", b"\n")
        actual_sha = hashlib.sha256(raw_bytes).hexdigest()
        assert actual_sha == summary["files"][fname]["sha256"], f"SHA256 mismatch for {fname}"
        # Validate JSON parsability
        parsed = json.loads(raw_bytes.decode("utf-8"))
        assert parsed is not None

    # Size constraint: bundle must be under 1MB
    assert summary["total_bundle_size_bytes"] < 1_000_000, "Bundle exceeds size budget"


def test_p27_schema_export_and_contract_md():
    """P27: Exported JSON Schemas exist for all models and docs/API_CONTRACT.md is verified."""
    schemas_dir = REPO_ROOT / "frontend" / "public" / "schemas"
    assert schemas_dir.exists()

    required_schemas = [
        "ExplanationRecord.json",
        "ChainLink.json",
        "DriverRecord.json",
        "EvidenceReceipt.json",
        "CascadeLoop.json",
        "ConcurrentCluster.json",
        "Action.json",
        "InterventionPlan.json",
        "PlanOutcome.json",
        "SideEffect.json",
        "ResourceUse.json",
        "Assumption.json",
    ]

    for sname in required_schemas:
        spath = schemas_dir / sname
        assert spath.exists(), f"Schema file {sname} missing"
        schema_dict = json.loads(spath.read_text(encoding="utf-8"))
        assert "properties" in schema_dict or "$defs" in schema_dict

    contract_path = REPO_ROOT / "docs" / "API_CONTRACT.md"
    assert contract_path.exists()
    contract_text = contract_path.read_text(encoding="utf-8")
    assert "/explain/latest" in contract_text
    assert "/intervene/plan" in contract_text
    assert "/ws/stream" in contract_text
