"""Demo Bundle Generator for Phase 4 (Assam Hero Window).

Produces a deterministic, small, versioned set of JSON artifacts in frontend/public/phase4/
enabling the Phase 5 React frontend to operate 100% offline without live backend services.

Artifacts:
  - summary.json: Bundle metadata, hashes, commit, provenance disclosures.
  - snapshots.json: Sequence of ForecastSnapshots across the 72h hero window.
  - explanations.json: ExplanationRecords at key milestones (lead, onset, peak) and transition events.
  - plans.json: Ranked intervention plans, resource accounting, and paired side-effects.
  - value_of_lead_time.json: Value-of-lead-time benefit curve and cost of waiting.
  - assumptions.json: Full Assumptions Register with provenance tags.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.city_config import load_city_config
from backend.app.explain.coordinator import explain_snapshot
from backend.app.forecast.config import ForecastConfig
from backend.app.forecast.engine import ForecastEngine
from backend.app.intervene.actions import (
    build_assumptions_register,
    filter_actions_for_city,
    load_interventions_config,
)
from backend.app.intervene.robust import (
    evaluate_effect_sensitivity,
    evaluate_model_uncertainty,
)
from backend.app.intervene.solver import generate_candidate_pool, solve_interventions
from backend.app.intervene.timing import evaluate_value_of_lead_time
from backend.app.replay.clock import ReplayClock
from backend.app.replay.stream import ReplayStream, StreamView
from backend.app.synth.generator import generate_city

BUNDLE_DIR = REPO_ROOT / "frontend" / "public" / "phase4"


def get_git_commit() -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "git-commit-unknown"


def build_demo_bundle(
    city_id: str = "upper_assam",
    seed: int = 1,
    duration_hours: int = 72,
    cadence_hours: int = 12,
) -> dict:
    """Build complete demo bundle artifacts."""
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)

    city_cfg = load_city_config(REPO_ROOT / "configs" / f"{city_id}.yaml")
    obs, _ = generate_city(
        city_cfg,
        seed,
        duration_hours,
        anchor_mode="off",
    )
    stream = ReplayStream(obs)
    clock = ReplayClock(city_cfg.start_time_utc)

    engine = ForecastEngine(
        city_config=city_cfg,
        forecast_config=ForecastConfig(rollouts=100),
        global_seed=seed,
        anchor_mode="off",
    )

    snapshots = []
    explanations = []
    key_milestones = {
        "lead": 12.0,
        "onset": 36.0,
        "peak": 60.0,
    }

    # Step through replay window at coarse cadence
    prev_snap = None
    step_times = list(range(0, duration_hours + 1, cadence_hours))
    decision_engine_state = None

    for idx, hour in enumerate(step_times):
        if idx > 0:
            clock.advance(cadence_hours)
        view = StreamView(stream, clock.now)
        snap = engine.step(clock.now, view, enable_trace=True)
        snapshots.append(snap.to_canonical_dict())

        # Check for key milestones or risk changes
        exp_rec = explain_snapshot(engine, subject="city", prev_snapshot=prev_snap)
        explanations.append(exp_rec.canonical_dict())
        prev_snap = snap

        if hour == 24 or (decision_engine_state is None and hour >= 24):
            decision_engine_state = {
                "decision_time": clock.now,
                "model": engine.learner.get_model(),
                "initial_beliefs": {n: (st.mean, st.variance) for n, st in engine.estimator.states.items()},
                "baseline_rollouts": engine.last_rollout_results,
                "noise_bank": engine.last_noise_bank,
            }

    if decision_engine_state is None:
        decision_engine_state = {
            "decision_time": clock.now,
            "model": engine.learner.get_model(),
            "initial_beliefs": {n: (st.mean, st.variance) for n, st in engine.estimator.states.items()},
            "baseline_rollouts": engine.last_rollout_results,
            "noise_bank": engine.last_noise_bank,
        }

    icfg = load_interventions_config()
    acts = filter_actions_for_city(icfg.actions, city_cfg)
    acts_by_id = {a.id: a for a in acts}
    zone_ids = [z.id for z in city_cfg.zones]
    candidates = generate_candidate_pool(acts, zone_ids=zone_ids)

    plans, _ = solve_interventions(
        candidates=candidates,
        actions_by_id=acts_by_id,
        budgets=icfg.default_budgets,
        model=decision_engine_state["model"],
        initial_beliefs=decision_engine_state["initial_beliefs"],
        baseline_rollouts=decision_engine_state["baseline_rollouts"],
        noise_bank=decision_engine_state["noise_bank"],
        decision_time=decision_engine_state["decision_time"],
        method="greedy",
        screening_rollouts=50,
        full_rollouts=100,
        horizon=48,
    )

    best_plan = next((p for p in plans if p.actions), plans[0] if plans else None)
    robustness = {}
    if best_plan and best_plan.feasibility and best_plan.actions:
        robustness["sensitivity"] = evaluate_effect_sensitivity(
            plan=best_plan,
            model=decision_engine_state["model"],
            initial_beliefs=decision_engine_state["initial_beliefs"],
            baseline_rollouts=decision_engine_state["baseline_rollouts"],
            actions_by_id=acts_by_id,
            noise_bank=decision_engine_state["noise_bank"],
            n_rollouts=100,
        )
        robustness["model_uncertainty"] = evaluate_model_uncertainty(
            plan=best_plan,
            model=decision_engine_state["model"],
            initial_beliefs=decision_engine_state["initial_beliefs"],
            baseline_rollouts=decision_engine_state["baseline_rollouts"],
            actions_by_id=acts_by_id,
            noise_bank=decision_engine_state["noise_bank"],
            n_rollouts=100,
        )

    # Value of lead time analysis
    lead_time_curve = {}
    if best_plan and best_plan.feasibility and best_plan.actions:
        lead_time_curve = evaluate_value_of_lead_time(
            plan=best_plan,
            model=decision_engine_state["model"],
            initial_beliefs=decision_engine_state["initial_beliefs"],
            baseline_rollouts=decision_engine_state["baseline_rollouts"],
            actions_by_id=acts_by_id,
            noise_bank=decision_engine_state["noise_bank"],
            delay_hours=[0.0, 3.0, 6.0, 12.0, 24.0],
            n_rollouts=100,
        )

    # Assumptions Register
    assumptions = build_assumptions_register(acts)

    # Write files canonically
    files_written = {}

    def _write_json(filename: str, payload: dict | list) -> str:
        p = BUNDLE_DIR / filename
        canonical_str = json.dumps(payload, indent=2, sort_keys=True)
        raw_bytes = canonical_str.encode("utf-8")
        p.write_bytes(raw_bytes)
        file_hash = hashlib.sha256(raw_bytes).hexdigest()
        files_written[filename] = {
            "size_bytes": len(raw_bytes),
            "sha256": file_hash,
        }
        return file_hash

    _write_json("snapshots.json", snapshots)
    _write_json("explanations.json", explanations)
    _write_json("plans.json", {
        "decision_time": clock.now.isoformat(),
        "budgets": icfg.default_budgets,
        "plans": [p.canonical_dict() for p in plans],
        "robustness": robustness,
    })
    _write_json("value_of_lead_time.json", lead_time_curve)
    _write_json("assumptions.json", {
        "catalog_version": icfg.version,
        "assumptions": [asm.canonical_dict() for asm in assumptions],
    })

    # Summary manifest
    summary = {
        "version": "1.0.0",
        "scenario": "Assam Floods July 2026 Hero Window",
        "city_id": city_id,
        "seed": seed,
        "anchor_mode": "off",
        "commit_hash": get_git_commit(),
        "generated_at_utc": "2026-10-26T00:00:00Z",  # fixed for determinism
        "provenance_disclosure": (
            "DOWNSTREAM INFRASTRUCTURE IS SIMULATED. "
            "ACTION EFFECT SIZES ARE ASSUMED. "
            "ESTIMATES UNDER LEARNED CAUSAL CANDIDATE MODEL."
        ),
        "files": files_written,
        "total_bundle_size_bytes": sum(f["size_bytes"] for f in files_written.values()),
    }
    _write_json("summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Build deterministic Phase 4 offline demo bundle.")
    parser.add_argument("--city", default="upper_assam", help="City configuration")
    parser.add_argument("--seed", type=int, default=1, help="Simulation seed")
    parser.add_argument("--duration", type=int, default=72, help="Replay duration in hours")
    parser.add_argument("--cadence", type=int, default=12, help="Snapshot cadence in hours")
    args = parser.parse_args()

    summary = build_demo_bundle(
        city_id=args.city,
        seed=args.seed,
        duration_hours=args.duration,
        cadence_hours=args.cadence,
    )
    print(f"Phase 4 demo bundle generated in {BUNDLE_DIR}")
    print(f"Total size: {summary['total_bundle_size_bytes']} bytes across {len(summary['files'])} files")


if __name__ == "__main__":
    main()
