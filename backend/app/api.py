"""Minimal FastAPI surface for Phase 1 (Assam hero scenario).

Endpoints:
  GET  /health
  GET  /cities                     -> available city configs (upper_assam, north_bank_assam)
  GET  /city/{city_id}             -> config summary
  WS   /ws/stream?city=&seed=&speed=&hours=&rain_window=&anchor= -> StreamMessage JSON as clock advances
  POST /faults                     -> toggle a fault on a replay session

Ground truth (backend.app.synth) is never exposed through this API; clients only
ever receive ``StreamMessage`` objects built from released observations.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import yaml

from .city_config import load_city_config
from .replay.clock import ReplayClock
from .replay.faults import FaultInjector, FaultSpec
from .replay.stream import ReplayStream, StreamView
from .schemas import StreamMessage
from .synth.generator import generate_city

APP_DIR = Path(__file__).resolve().parent.parent
CONFIGS_DIR = APP_DIR.parent / "configs"
WINDOWS_FILE = CONFIGS_DIR / "scenarios" / "assam_2026" / "windows.yaml"

app = FastAPI(title="The 72-Hour Warning — Assam Phase 1 Replay Backbone")

# In-memory session registry: key = f"{city_id}:{seed}:{window}:{anchor}".
_sessions: dict[str, "ReplaySession"] = {}
_risk_change_logs: dict[str, Any] = {}


class ReplaySession:
    def __init__(
        self,
        config,
        seed: int,
        duration_hours: int = 72,
        rain_series=None,
        generator_family: str = "logistic_hazard",
        anchor_mode: str = "off",
        rain_driver_label: str = "real_rain:openmeteo",
    ):
        self.config = config
        self.seed = seed
        self.anchor_mode = anchor_mode
        self.observations, self.ground_truth = generate_city(
            config,
            seed,
            duration_hours,
            rain_series=rain_series,
            generator_family=generator_family,
            anchor_mode=anchor_mode,
            rain_driver_label=rain_driver_label,
        )
        self.stream = ReplayStream(self.observations)
        self.clock = ReplayClock(config.start_time_utc)
        self.clock.speed = 1.0
        self.injector = FaultInjector(seed)
        self.view = StreamView(self.stream, self.clock.now)
        self.duration_hours = duration_hours
        self.faults_applied: list[str] = []
        self._released_ids: set = set()


def _step(session: ReplaySession, hours: float = 1.0) -> list:
    """Advance the clock, apply faults, return newly released observations."""
    session.clock.advance(hours)
    base = list(session.observations)
    modified = session.injector.apply(base, session.config.start_time_utc)
    released = []
    for obs in sorted(modified, key=lambda o: (o.arrival_time, o.event_time, o.obs_id)):
        if obs.arrival_time <= session.clock.now:
            released.append(obs)
    newly_released = [o for o in released if o.obs_id not in session._released_ids]
    session._released_ids.update(o.obs_id for o in newly_released)
    return newly_released


def _load_config(city_id: str):
    path = CONFIGS_DIR / f"{city_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"city config not found: {path}")
    return load_city_config(path)


def _load_windows() -> dict:
    if WINDOWS_FILE.exists():
        with WINDOWS_FILE.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data.get("windows", {})
    return {}


class FaultIn(BaseModel):
    kind: str
    target_zone: Optional[str] = None
    target_system: Optional[str] = None
    start_hour: int = 0
    end_hour: int = 10**9
    probability: float = 0.5
    delay_hours: float = 2.0
    stuck_value: float = 0.0
    spike_magnitude: float = 10.0
    burst_count: int = 20


@app.get("/health")
def health():
    return {"status": "ok", "service": "72-hour-warning-phase1"}


@app.get("/cities")
def cities():
    out = []
    # Explicitly whitelist only upper_assam and north_bank_assam
    allowed = ["upper_assam", "north_bank_assam"]
    for city_id in allowed:
        p = CONFIGS_DIR / f"{city_id}.yaml"
        if p.exists():
            cfg = load_city_config(p)
            out.append({
                "city_id": cfg.city_id,
                "zones": len(cfg.zones),
                "systems": [s.id for s in cfg.systems],
                "streams": [s.source for s in cfg.streams],
                "start_time_utc": cfg.start_time_utc.isoformat(),
            })
    return {"cities": out}


@app.get("/city/{city_id}")
def city(city_id: str):
    cfg = _load_config(city_id)
    return {
        "city_id": cfg.city_id,
        "zones": [{"id": z.id, "name": z.name, "neighbours": z.neighbours} for z in cfg.zones],
        "systems": [{"id": s.id, "unit": s.unit} for s in cfg.systems],
        "start_time_utc": cfg.start_time_utc.isoformat(),
        "critical_stress_threshold": cfg.critical_stress_threshold,
    }


@app.get("/forecast/latest")
def forecast_latest(city: str = "upper_assam", seed: int = 1, rain_window: str = "peak", anchor: str = "off"):
    """Return the latest ForecastSnapshot for a replay session."""
    cfg = _load_config(city)
    key = f"{city}:{seed}:{rain_window}:{anchor}"
    if key not in _sessions:
        _sessions[key] = ReplaySession(cfg, seed, duration_hours=24, anchor_mode=anchor)
    session = _sessions[key]

    from .forecast.engine import ForecastEngine
    from .forecast.config import ForecastConfig

    engine = ForecastEngine(
        city_config=cfg,
        forecast_config=ForecastConfig(rollouts=50),
        global_seed=seed,
        anchor_mode=anchor,
    )
    snapshot = engine.step(session.clock.now, session.view)
    return snapshot.to_canonical_dict()


@app.post("/faults")
def post_faults(city: str, seed: int, fault: FaultIn):
    """Add a fault to the replay session for (city, seed)."""
    cfg = _load_config(city)
    key = f"{city}:{seed}:default:off"
    if key not in _sessions:
        _sessions[key] = ReplaySession(cfg, seed)
    session = _sessions[key]
    spec = FaultSpec(**fault.model_dump())
    session.injector.add_fault(spec)
    session.faults_applied.append(fault.kind)
    return {
        "ok": True,
        "session": key,
        "fault": fault.kind,
        "faults_applied": session.faults_applied,
        "fault_log_entries": len(session.injector.fault_log),
    }


@app.websocket("/ws/stream")
async def ws_stream(websocket: WebSocket):
    await websocket.accept()
    try:
        city_id = websocket.query_params.get("city", "upper_assam")
        seed = int(websocket.query_params.get("seed", "1"))
        speed = float(websocket.query_params.get("speed", "1.0"))
        hours = int(websocket.query_params.get("hours", "72"))
        rain_window = websocket.query_params.get("rain_window", "peak")
        anchor_mode = websocket.query_params.get("anchor", "off")
        forecast_mode = int(websocket.query_params.get("forecast", "0"))
        explain_mode = int(websocket.query_params.get("explain", "0"))
        plan_mode = int(websocket.query_params.get("plan", "0"))
    except ValueError as exc:
        await websocket.close(code=4000, reason=str(exc))
        return

    try:
        cfg = _load_config(city_id)
    except Exception as exc:
        await websocket.close(code=4004, reason=f"Config error: {exc}")
        return

    windows = _load_windows()
    if rain_window in windows:
        w = windows[rain_window]
        start_ts = datetime.fromisoformat(w["start_time_utc"].replace("Z", "+00:00"))
        end_ts = datetime.fromisoformat(w["end_time_utc"].replace("Z", "+00:00"))
        hours = min(hours, int((end_ts - start_ts).total_seconds() // 3600))
        cfg = cfg.model_copy(update={"start_time_utc": start_ts})

    key = f"{city_id}:{seed}:{rain_window}:{anchor_mode}"
    if key not in _sessions:
        rain_series_by_zone = None
        if rain_window != "none":
            from .adapters.openmeteo import OpenMeteoAdapter
            try:
                adapter = OpenMeteoAdapter(city_id=cfg.city_id)
                end_eval_ts = cfg.start_time_utc + timedelta(hours=hours)
                rain_series_by_zone = {}
                for z in cfg.zones:
                    s_dict = adapter.to_rain_series(z.id, cfg.start_time_utc, end_eval_ts)
                    z_rain = {}
                    for dt, v in s_dict.items():
                        h_off = int((dt - cfg.start_time_utc).total_seconds() // 3600)
                        if 0 <= h_off <= hours:
                            z_rain[h_off] = v
                    rain_series_by_zone[z.id] = z_rain
            except Exception:
                rain_series_by_zone = None

        _sessions[key] = ReplaySession(
            cfg,
            seed,
            duration_hours=hours,
            rain_series=rain_series_by_zone,
            anchor_mode=anchor_mode,
            rain_driver_label="real_rain:openmeteo" if rain_series_by_zone else "synthetic_storms",
        )

    session = _sessions[key]
    session.clock.speed = speed

    # Optional forecast engine if forecast_mode == 1 or explain/plan requested
    forecast_engine = None
    if forecast_mode == 1 or explain_mode == 1 or plan_mode == 1:
        from .forecast.engine import ForecastEngine
        from .forecast.config import ForecastConfig

        forecast_engine = ForecastEngine(
            city_config=cfg,
            forecast_config=ForecastConfig(rollouts=50),
            global_seed=seed,
            anchor_mode=anchor_mode,
        )

    end_time = cfg.start_time_utc + timedelta(hours=hours)
    step_hours = 1.0

    try:
        while session.clock.now < end_time:
            released = _step(session, step_hours)
            msg = {
                "type": "observations",
                "clock_time": session.clock.now.isoformat(),
                "observations": [o.model_dump() for o in released],
                "meta": {
                    "city": city_id,
                    "seed": seed,
                    "released_count": len(released),
                    "faults": list(session.faults_applied),
                    "anchor_mode": session.anchor_mode,
                },
            }
            await websocket.send_text(json.dumps(msg, default=str))

            if forecast_engine is not None:
                snap = forecast_engine.step(
                    session.clock.now,
                    session.view,
                    enable_trace=bool(explain_mode == 1),
                )
                if forecast_mode == 1:
                    f_msg = {
                        "type": "forecast",
                        "clock_time": session.clock.now.isoformat(),
                        "forecast": snap.to_canonical_dict(),
                    }
                    await websocket.send_text(json.dumps(f_msg, default=str))

                if explain_mode == 1:
                    from .explain.coordinator import explain_snapshot
                    exp_rec = explain_snapshot(forecast_engine, subject="city")
                    e_msg = {
                        "type": "explanation",
                        "clock_time": session.clock.now.isoformat(),
                        "explanation": exp_rec.canonical_dict(),
                    }
                    await websocket.send_text(json.dumps(e_msg, default=str))

                if plan_mode == 1:
                    from .intervene.actions import load_interventions_config, filter_actions_for_city
                    from .intervene.solver import solve_interventions, generate_candidate_pool
                    icfg = load_interventions_config()
                    acts = filter_actions_for_city(icfg.actions, cfg)
                    acts_by_id = {a.id: a for a in acts}
                    zone_ids = [z.id for z in cfg.zones]
                    candidates = generate_candidate_pool(acts, zone_ids=zone_ids)
                    plans, _ = solve_interventions(
                        candidates=candidates,
                        actions_by_id=acts_by_id,
                        budgets=icfg.default_budgets,
                        model=forecast_engine.last_forward_model,
                        initial_beliefs=forecast_engine.last_initial_beliefs,
                        baseline_rollouts=forecast_engine.last_rollout_results,
                        noise_bank=forecast_engine.last_noise_bank,
                        decision_time=session.clock.now,
                        method="greedy",
                        screening_rollouts=50,
                        full_rollouts=50,
                        horizon=24,
                    )
                    best_plan = plans[0] if plans else None
                    p_msg = {
                        "type": "plan",
                        "clock_time": session.clock.now.isoformat(),
                        "plan": best_plan.canonical_dict() if best_plan else None,
                    }
                    await websocket.send_text(json.dumps(p_msg, default=str))

            await asyncio.sleep(max(0.001, 0.05 / speed))
    except WebSocketDisconnect:
        pass


# ===========================================================================
# Phase 3: Read-Only Evaluation Endpoints
# ===========================================================================
EVAL_SUMMARY_FILE = APP_DIR.parent / "eval" / "summary.json"
EVAL_RELIABILITY_FILE = APP_DIR.parent / "frontend" / "public" / "eval" / "reliability.json"
EVAL_CURVES_FILE = APP_DIR.parent / "frontend" / "public" / "eval" / "curves.json"
EVAL_MATRIX_FILE = APP_DIR.parent / "frontend" / "public" / "eval" / "matrix.json"


@app.get("/eval/summary")
def get_eval_summary() -> dict:
    """Return machine-readable headline evaluation summary."""
    if not EVAL_SUMMARY_FILE.exists():
        raise HTTPException(status_code=404, detail="Evaluation summary missing. Run scripts/eval_report.py first.")
    return json.loads(EVAL_SUMMARY_FILE.read_text(encoding="utf-8"))


@app.get("/eval/reliability")
def get_eval_reliability(horizon: Optional[str] = None, level: Optional[str] = None) -> dict:
    """Return reliability diagram data and calibration error."""
    if not EVAL_RELIABILITY_FILE.exists():
        raise HTTPException(status_code=404, detail="Reliability evaluation data missing.")
    data = json.loads(EVAL_RELIABILITY_FILE.read_text(encoding="utf-8"))
    if horizon:
        data["requested_horizon"] = horizon
    if level:
        data["requested_level"] = level
    return data


@app.get("/eval/curves")
def get_eval_curves() -> dict:
    """Return lead-time vs false-alarm trade-off curves."""
    if not EVAL_CURVES_FILE.exists():
        raise HTTPException(status_code=404, detail="Evaluation curve data missing.")
    return json.loads(EVAL_CURVES_FILE.read_text(encoding="utf-8"))


@app.get("/eval/matrix")
def get_eval_matrix() -> dict:
    """Return Playbook requirements matrix status."""
    if not EVAL_MATRIX_FILE.exists():
        raise HTTPException(status_code=404, detail="Requirements matrix data missing.")
    return json.loads(EVAL_MATRIX_FILE.read_text(encoding="utf-8"))


# ===========================================================================
# Phase 4: Causal Explanation & Counterfactual Intervention Endpoints
# ===========================================================================

@app.get("/explain/latest")
def get_explain_latest(
    city: str = "upper_assam",
    seed: int = 1,
    zone: Optional[str] = None,
    rain_window: str = "peak",
    anchor: str = "off",
):
    """Return current failure chain, branching tree, and causal drivers for a zone or the city."""
    cfg = _load_config(city)
    key = f"{city}:{seed}:{rain_window}:{anchor}"
    if key not in _sessions:
        _sessions[key] = ReplaySession(cfg, seed, duration_hours=24, anchor_mode=anchor)
    session = _sessions[key]

    from .forecast.engine import ForecastEngine
    from .forecast.config import ForecastConfig
    from .explain.coordinator import explain_snapshot
    from .explain.log import RiskChangeLog

    engine = ForecastEngine(
        city_config=cfg,
        forecast_config=ForecastConfig(rollouts=100),
        global_seed=seed,
        anchor_mode=anchor,
    )
    _ = engine.step(session.clock.now, session.view, enable_trace=True)

    subject = zone if zone else "city"
    record = explain_snapshot(engine, subject=subject)

    log_key = f"{city}:{seed}"
    if log_key not in _risk_change_logs:
        _risk_change_logs[log_key] = RiskChangeLog()
    _risk_change_logs[log_key].append(record)

    return record.canonical_dict()


@app.get("/explain/changes")
def get_explain_changes(
    city: str = "upper_assam",
    seed: int = 1,
    limit: int = 10,
    subject: Optional[str] = None,
):
    """Return bounded risk-change log entries for a replay session."""
    log_key = f"{city}:{seed}"
    if log_key not in _risk_change_logs:
        return {"changes": []}
    log = _risk_change_logs[log_key]
    entries = log.get_changes(subject=subject, limit=limit)
    return {"changes": [e.canonical_dict() for e in entries]}


@app.get("/explain/link")
def get_explain_link(
    u: str,
    v: str,
    city: str = "upper_assam",
    seed: int = 1,
    rain_window: str = "peak",
    anchor: str = "off",
):
    """Return evidence receipt and paired removal counterfactual for a directed link u -> v."""
    cfg = _load_config(city)
    key = f"{city}:{seed}:{rain_window}:{anchor}"
    if key not in _sessions:
        _sessions[key] = ReplaySession(cfg, seed, duration_hours=24, anchor_mode=anchor)
    session = _sessions[key]

    from .forecast.engine import ForecastEngine
    from .forecast.config import ForecastConfig
    from .explain.receipts import build_evidence_receipt
    from .explain.chains import evaluate_link_removal_counterfactual

    engine = ForecastEngine(
        city_config=cfg,
        forecast_config=ForecastConfig(rollouts=100),
        global_seed=seed,
        anchor_mode=anchor,
    )
    _ = engine.step(session.clock.now, session.view, enable_trace=True)

    receipt = build_evidence_receipt(
        node=v,
        parent_node=u,
        issued_at=session.clock.now,
        ledger=engine.ledger,
        edge_book=engine.learner.edge_book,
    )

    delta_p, delta_ttc = evaluate_link_removal_counterfactual(
        u=u,
        v=v,
        model=engine.learner.get_model(),
        initial_beliefs={n: (st.mean, st.variance) for n, st in engine.estimator.states.items()},
        baseline_results=engine.last_rollout_results,
        noise_bank=engine.last_noise_bank,
        global_seed=seed,
        horizon=48,
        n_rollouts=100,
    )
    receipt.paired_removal_effect = {
        "delta_p_critical": delta_p,
        "delta_median_ttc": delta_ttc,
    }

    return receipt.canonical_dict()


@app.get("/intervene/actions")
def get_intervene_actions(city: str = "upper_assam"):
    """Return available action library and Assumptions Register for a city."""
    cfg = _load_config(city)
    from .intervene.actions import load_interventions_config, filter_actions_for_city, build_assumptions_register
    icfg = load_interventions_config()
    filtered = filter_actions_for_city(icfg.actions, cfg)
    assumptions = build_assumptions_register(filtered)
    return {
        "city_id": city,
        "actions": [a.canonical_dict() for a in filtered],
        "assumptions": [asm.canonical_dict() for asm in assumptions],
        "default_budgets": icfg.default_budgets,
        "objective": icfg.objective,
    }


class PlanRequest(BaseModel):
    city: str = "upper_assam"
    seed: int = 1
    rain_window: str = "peak"
    anchor: str = "off"
    budgets: Optional[dict[str, float]] = None
    method: str = "greedy"
    mode: str = "fast"
    horizon: int = 48


@app.post("/intervene/plan")
def post_intervene_plan(req: PlanRequest):
    """Solve for ranked budget-feasible intervention plans."""
    cfg = _load_config(req.city)
    key = f"{req.city}:{req.seed}:{req.rain_window}:{req.anchor}"
    if key not in _sessions:
        _sessions[key] = ReplaySession(cfg, req.seed, duration_hours=24, anchor_mode=req.anchor)
    session = _sessions[key]

    from .forecast.engine import ForecastEngine
    from .forecast.config import ForecastConfig
    from .intervene.actions import load_interventions_config, filter_actions_for_city
    from .intervene.solver import solve_interventions, generate_candidate_pool

    engine = ForecastEngine(
        city_config=cfg,
        forecast_config=ForecastConfig(rollouts=100),
        global_seed=req.seed,
        anchor_mode=req.anchor,
    )
    _ = engine.step(session.clock.now, session.view, enable_trace=True)

    icfg = load_interventions_config()
    budgets = req.budgets if req.budgets is not None else icfg.default_budgets
    acts = filter_actions_for_city(icfg.actions, cfg)
    acts_by_id = {a.id: a for a in acts}
    zone_ids = [z.id for z in cfg.zones]
    candidates = generate_candidate_pool(acts, zone_ids=zone_ids)

    screening_n = 50 if req.mode == "fast" else 100
    full_n = 100 if req.mode == "fast" else 300

    plans, elapsed = solve_interventions(
        candidates=candidates,
        actions_by_id=acts_by_id,
        budgets=budgets,
        model=engine.learner.get_model(),
        initial_beliefs={n: (st.mean, st.variance) for n, st in engine.estimator.states.items()},
        baseline_rollouts=engine.last_rollout_results,
        noise_bank=engine.last_noise_bank,
        decision_time=session.clock.now,
        method=req.method,
        screening_rollouts=screening_n,
        full_rollouts=full_n,
        horizon=req.horizon,
    )

    return {
        "city": req.city,
        "elapsed_seconds": round(elapsed, 4),
        "plans": [p.canonical_dict() for p in plans],
    }


class EvaluatePlanRequest(BaseModel):
    city: str = "upper_assam"
    seed: int = 1
    rain_window: str = "peak"
    anchor: str = "off"
    plan: dict[str, Any]
    horizon: int = 48


@app.post("/intervene/evaluate")
def post_intervene_evaluate(req: EvaluatePlanRequest):
    """Evaluate paired counterfactual outcomes of an explicit intervention plan vs do-nothing."""
    cfg = _load_config(req.city)
    key = f"{req.city}:{req.seed}:{req.rain_window}:{req.anchor}"
    if key not in _sessions:
        _sessions[key] = ReplaySession(cfg, req.seed, duration_hours=24, anchor_mode=req.anchor)
    session = _sessions[key]

    from .forecast.engine import ForecastEngine
    from .forecast.config import ForecastConfig
    from .intervene.actions import load_interventions_config, filter_actions_for_city
    from .intervene.evaluate import evaluate_plan
    from .intervene.records import InterventionPlan

    engine = ForecastEngine(
        city_config=cfg,
        forecast_config=ForecastConfig(rollouts=100),
        global_seed=req.seed,
        anchor_mode=req.anchor,
    )
    _ = engine.step(session.clock.now, session.view, enable_trace=True)

    icfg = load_interventions_config()
    acts = filter_actions_for_city(icfg.actions, cfg)
    acts_by_id = {a.id: a for a in acts}

    plan_obj = InterventionPlan(**req.plan)
    outcome = evaluate_plan(
        plan=plan_obj,
        model=engine.learner.get_model(),
        initial_beliefs={n: (st.mean, st.variance) for n, st in engine.estimator.states.items()},
        baseline_rollouts=engine.last_rollout_results,
        actions_by_id=acts_by_id,
        noise_bank=engine.last_noise_bank,
        global_seed=req.seed,
        horizon=req.horizon,
        n_rollouts=100,
        budgets=icfg.default_budgets,
    )

    return outcome.canonical_dict()


def main():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
