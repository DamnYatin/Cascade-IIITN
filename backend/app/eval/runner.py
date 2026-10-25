"""Evaluation Runner with caching, parallel multiprocessing, and resume support.

Rule V8:
  - Separates the EXPENSIVE step (generate predictions) from the CHEAP step (score).
  - Caches predictions on disk keyed by (config_hash, city, family, seed, faults, rollouts, cadence, method, code_version).
  - Same key gives byte-identical predictions; any key change invalidates cache.
  - Resume after interruption skips already cached runs.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np

from backend.app.city_config import load_city_config
from backend.app.eval.events import TrueEpisode
from backend.app.eval.protocol import DEV_SEEDS, PROTOCOL_FAMILIES
from backend.app.eval.scenarios import build_scenario_instance
from backend.app.forecast.calibrate import Calibrator, IdentityCalibrator
from backend.app.forecast.config import ForecastConfig, load_forecast_config
from backend.app.forecast.engine import ForecastEngine
from backend.app.forecast.outlook import PersistenceDecayOutlook
from backend.app.replay.faults import FaultSpec
from backend.app.replay.stream import ReplayStream, StreamView
from backend.app.schemas import CityConfig, Observation

DEFAULT_CACHE_DIR = Path("eval/cache")


@dataclass
class EvalRunConfig:
    city_id: str = "upper_assam"
    family: str = "F-storm"
    seed: int = 42
    duration_hours: int = 168
    cadence_hours: int = 3
    rollouts: int = 100
    faults_str: str = "none"
    anchor_mode: str = "off"
    method: str = "forecaster"
    code_version: str = "phase3_v1"
    ablation_flags: Dict[str, Any] = field(default_factory=dict)
    calibrator_source: str = "none"

    def compute_signature(self, config_hash: str) -> str:
        """Compute deterministic SHA-256 cache signature."""
        sig_data = {
            "city_id": self.city_id,
            "family": self.family,
            "seed": self.seed,
            "duration": self.duration_hours,
            "cadence": self.cadence_hours,
            "rollouts": self.rollouts,
            "faults": self.faults_str,
            "anchor_mode": self.anchor_mode,
            "method": self.method,
            "code_version": self.code_version,
            "ablation": sorted(self.ablation_flags.items()),
            "calibrator": self.calibrator_source,
            "cfg_hash": config_hash,
        }
        canon = json.dumps(sig_data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _parse_faults(faults_str: str, seed: int) -> List[FaultSpec]:
    """Parse comma-separated fault names into FaultSpec objects."""
    if not faults_str or faults_str == "none":
        return []
    specs = []
    for f in faults_str.split(","):
        f = f.strip()
        if f:
            specs.append(FaultSpec(kind=f, start_hour=0, end_hour=10**9, probability=0.4))
    return specs


def run_single_evaluation(
    run_cfg: EvalRunConfig,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    use_cache: bool = True,
    calibrator: Optional[Calibrator] = None,
) -> Dict[str, Any]:
    """Execute a single evaluation run with disk caching and resume support."""
    # 1. Determine config hash and cache key
    city_yaml_path = Path(f"configs/{run_cfg.city_id}.yaml")
    if not city_yaml_path.exists():
        raise FileNotFoundError(f"Missing city config: {city_yaml_path}")
    city_config = load_city_config(city_yaml_path)

    f_cfg = load_forecast_config()
    f_cfg.rollouts = run_cfg.rollouts
    f_cfg.step_hours = run_cfg.cadence_hours
    cfg_hash = hashlib.sha256(
        f"{city_config.city_id}:{f_cfg.step_hours}:{f_cfg.rollouts}".encode()
    ).hexdigest()[:16]

    cache_key = run_cfg.compute_signature(cfg_hash)
    cache_file = cache_dir / f"{run_cfg.city_id}_{run_cfg.family}_{run_cfg.method}_s{run_cfg.seed}_{cache_key[:12]}.json"

    # Check cache
    if use_cache and cache_file.exists():
        try:
            with cache_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("cache_key") == cache_key:
                    return data
        except Exception:
            # If corrupt, recompute
            pass

    start_wall = time.perf_counter()

    # 2. Build scenario instance
    fault_specs = _parse_faults(run_cfg.faults_str, run_cfg.seed)
    scenario = build_scenario_instance(
        family=run_cfg.family,
        city_config=city_config,
        seed=run_cfg.seed,
        duration_hours=run_cfg.duration_hours,
        faults=fault_specs,
        anchor_mode=run_cfg.anchor_mode,
    )

    # 3. Create Forecaster or Baseline
    # (baselines will be imported and hooked dynamically in G4)
    calib = calibrator or IdentityCalibrator()
    engine = ForecastEngine(
        city_config=city_config,
        forecast_config=f_cfg,
        calibrator=calib,
        global_seed=run_cfg.seed,
        anchor_mode=run_cfg.anchor_mode,
    )

    # 4. Walk-forward step loop
    stream = ReplayStream(scenario.observations)
    stream_view = StreamView(stream, city_config.start_time_utc)
    hours: List[float] = []
    zone_p_crit_72: Dict[str, List[float]] = {z.id: [] for z in city_config.zones}
    zone_p_crit_12: Dict[str, List[float]] = {z.id: [] for z in city_config.zones}
    city_p_crit_72: List[float] = []
    drift_events_log: List[Dict[str, Any]] = []

    start_utc = city_config.start_time_utc
    for step_h in range(0, run_cfg.duration_hours + 1, run_cfg.cadence_hours):
        clock_dt = start_utc + timedelta(hours=step_h)
        stream_view.set_clock_time(clock_dt)

        snapshot = engine.step(clock_time=clock_dt, stream_view=stream_view)

        hours.append(float(step_h))
        for z in city_config.zones:
            p72 = snapshot.zone_probabilities.get(z.id, {}).get("72", {}).get("CRITICAL", 0.0)
            p12 = snapshot.zone_probabilities.get(z.id, {}).get("12", {}).get("CRITICAL", 0.0)
            zone_p_crit_72[z.id].append(float(p72))
            zone_p_crit_12[z.id].append(float(p12))

        c_p72 = snapshot.city_probabilities.get("72", {}).get("CRITICAL", 0.0)
        city_p_crit_72.append(float(c_p72))

        if snapshot.drift_events:
            drift_events_log.extend(snapshot.drift_events)

    elapsed_wall = time.perf_counter() - start_wall

    # Serialize true episodes
    serialized_episodes: Dict[str, List[Dict[str, Any]]] = {}
    for z_id, eps in scenario.true_zone_cascade_episodes.items():
        serialized_episodes[z_id] = [
            {
                "episode_id": ep.episode_id,
                "start_hour": ep.start_hour,
                "end_hour": ep.end_hour,
                "peak_value": ep.peak_value,
                "duration_hours": ep.duration_hours,
            }
            for ep in eps
        ]

    # Active learned edges from final snapshot
    final_edges = snapshot.top_edges

    result_data = {
        "cache_key": cache_key,
        "run_config": asdict(run_cfg),
        "city_id": run_cfg.city_id,
        "family": run_cfg.family,
        "seed": run_cfg.seed,
        "duration_hours": run_cfg.duration_hours,
        "cadence_hours": run_cfg.cadence_hours,
        "hours": hours,
        "zone_p_crit_72": zone_p_crit_72,
        "zone_p_crit_12": zone_p_crit_12,
        "city_p_crit_72": city_p_crit_72,
        "true_zone_cascade_episodes": serialized_episodes,
        "top_edges": final_edges,
        "drift_events": drift_events_log,
        "elapsed_wall_seconds": round(elapsed_wall, 3),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    # Save to disk cache
    cache_dir.mkdir(parents=True, exist_ok=True)
    with cache_file.open("w", encoding="utf-8") as f:
        json.dump(result_data, f, indent=2)

    return result_data


def run_batch_evaluations(
    configs: List[EvalRunConfig],
    cache_dir: Path = DEFAULT_CACHE_DIR,
    use_cache: bool = True,
    max_workers: int = 4,
) -> List[Dict[str, Any]]:
    """Run a batch of evaluation runs in parallel with Windows-safe process pool."""
    results: List[Dict[str, Any]] = []

    # If only 1 config or 1 worker, run sequentially
    if len(configs) == 1 or max_workers <= 1:
        for cfg in configs:
            results.append(run_single_evaluation(cfg, cache_dir=cache_dir, use_cache=use_cache))
        return results

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(run_single_evaluation, cfg, cache_dir, use_cache): cfg
            for cfg in configs
        }
        for fut in concurrent.futures.as_completed(futures):
            res = fut.result()
            results.append(res)

    return results
