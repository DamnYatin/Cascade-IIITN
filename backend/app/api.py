"""Minimal FastAPI surface for Phase 1.

Endpoints:
  GET  /health
  GET  /cities                     -> available city configs
  GET  /city/{city_id}             -> config summary
  WS   /ws/stream?city=&seed=&speed=   -> StreamMessage JSON as clock advances
  POST /faults                     -> toggle a fault on a replay session

Ground truth (backend.app.synth) is never exposed through this API; clients only
ever receive ``StreamMessage`` objects built from released observations.
"""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .city_config import load_city_config
from .replay.clock import ReplayClock
from .replay.faults import FaultInjector, FaultSpec
from .replay.stream import ReplayStream, StreamView
from .synth.generator import generate_city

APP_DIR = Path(__file__).resolve().parent.parent
CONFIGS_DIR = APP_DIR.parent / "configs"

app = FastAPI(title="The 72-Hour Warning — Phase 1 Replay Backbone")

# In-memory session registry: key = f"{city_id}:{seed}".
# Keeps a WS connection and the POST /faults endpoint able to address the same
# replay. Ground truth is stored in the session but never emitted over WS.
_sessions: dict[str, "ReplaySession"] = {}


class ReplaySession:
    def __init__(self, config, seed: int, duration_hours: int = 168,
                 rain_series=None, generator_family: str = "logistic_hazard"):
        self.config = config
        self.seed = seed
        self.observations, self.ground_truth = generate_city(
            config, seed, duration_hours,
            rain_series=rain_series,
            generator_family=generator_family,
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
    released = [o for o in released if o.obs_id not in session._released_ids]
    session._released_ids.update(o.obs_id for o in released)
    return released


def _load_config(city_id: str):
    path = CONFIGS_DIR / f"{city_id}.yaml"
    return load_city_config(path)


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
    if CONFIGS_DIR.exists():
        for p in sorted(CONFIGS_DIR.glob("*.yaml")):
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


@app.post("/faults")
def post_faults(city: str, seed: int, fault: FaultIn):
    """Add a fault to the replay session for (city, seed), creating it if needed."""
    cfg = _load_config(city)
    key = f"{city}:{seed}"
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
        city = websocket.query_params.get("city", "mumbai")
        seed = int(websocket.query_params.get("seed", "1"))
        speed = float(websocket.query_params.get("speed", "1.0"))
        hours = int(websocket.query_params.get("hours", "168"))
        rain_window = websocket.query_params.get("rain_window", None)
    except ValueError as exc:
        await websocket.close(code=4000, reason=str(exc))
        return

    cfg = _load_config(city)
    key = f"{city}:{seed}"
    if key not in _sessions:
        rain_series = None
        if rain_window:
            from .adapters.imd_rain import IMDRainAdapter, PRESETS
            p = PRESETS[rain_window]
            adapter = IMDRainAdapter(seed=seed)
            dt_series = adapter.to_rain_series(
                p["districts"][0], p["start"], p["end"], seed=seed
            )
            start_ts = cfg.start_time_utc
            rain_series = {}
            for dt, v in dt_series.items():
                off = int((dt - start_ts).total_seconds() // 3600)
                rain_series[off] = rain_series.get(off, 0.0) + v
        _sessions[key] = ReplaySession(
            cfg, seed, duration_hours=hours,
            rain_series=rain_series,
        )
    session = _sessions[key]
    session.clock.speed = speed

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
                    "city": city,
                    "seed": seed,
                    "released_count": len(released),
                    "faults": list(session.faults_applied),
                },
            }
            await websocket.send_text(json.dumps(msg, default=str))
            await asyncio.sleep(max(0.001, 0.05 / speed))
    except WebSocketDisconnect:
        pass


def main():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
