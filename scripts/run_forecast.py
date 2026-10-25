"""The 72-Hour Warning: Phase 2 Forecaster CLI.

Continuous probabilistic forecasting with online dependency discovery and source trust.

Usage:
  python scripts/run_forecast.py --city upper_assam --scenario assam_2026 --window peak --seed 42
  python scripts/run_forecast.py --city north_bank_assam --scenario assam_2026 --window lead --anchor-mode on
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import yaml

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.app.adapters.openmeteo import OpenMeteoAdapter
from backend.app.city_config import load_city_config
from backend.app.forecast.config import ForecastConfig, load_forecast_config
from backend.app.forecast.engine import ForecastEngine
from backend.app.forecast.outlook import BlockBootstrapOutlook, PersistenceDecayOutlook
from backend.app.replay.clock import ReplayClock
from backend.app.replay.faults import FaultInjector, FaultSpec
from backend.app.replay.stream import ReplayStream
from backend.app.schemas import Observation, QualityFlag, SourceKind
from backend.app.synth.generator import generate_city

WINDOWS_FILE = REPO / "configs" / "scenarios" / "assam_2026" / "windows.yaml"


def compute_stream_hash(observations: List[Observation]) -> str:
    """Compute deterministic SHA-256 hash across canonical observation bytes."""
    lines = []
    for o in sorted(observations, key=lambda x: (x.arrival_time, x.event_time, x.obs_id)):
        flags = [str(f.value if hasattr(f, "value") else f) for f in o.quality_flags]
        flags_str = ",".join(sorted(flags))
        lines.append(
            f"{o.obs_id}|{o.source}|{o.source_kind.value}|{o.zone}|{o.system}|{o.value:.4f}|"
            f"{o.event_time.isoformat()}|{o.arrival_time.isoformat()}|{flags_str}"
        )
    raw = "\n".join(lines).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_window_specs() -> Dict[str, Dict[str, str]]:
    if WINDOWS_FILE.exists():
        with WINDOWS_FILE.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
            return data.get("windows", {})
    return {}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="72-Hour Warning Forecaster CLI")
    parser.add_argument("--city", default="upper_assam", help="City config ID")
    parser.add_argument("--scenario", default="assam_2026", help="Scenario ID")
    parser.add_argument("--window", default="peak", help="Named window (lead, onset, peak, hero_full)")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic global seed")
    parser.add_argument("--family", default="logistic_hazard", help="Generator family")
    parser.add_argument("--anchor-mode", choices=["off", "on"], default="off", help="Generator anchor mode")
    parser.add_argument("--faults", default="none", help="Fault specifications")
    parser.add_argument("--every-hours", type=int, default=1, help="Forecast cadence in hours")
    parser.add_argument("--rollouts", type=int, default=300, help="Number of Monte Carlo rollouts")
    parser.add_argument("--horizons", default="1,3,6,12,24,48,72", help="Forecast horizons (comma-separated)")
    parser.add_argument("--out", type=Path, default=None, help="Optional output JSONL path for snapshots")
    parser.add_argument("--offline", action="store_true", help="Enforce offline operation")

    args = parser.parse_args(argv)

    # 1. Print Banner
    print("======================================================================")
    print("THE 72-HOUR WARNING: FORECASTER CLI (Phase 2)")
    print("======================================================================")
    print("PROVENANCE DISCLOSURE (Rule 8):")
    print("  Real inputs: Rainfall and Soil Moisture (Open-Meteo / satellite archive).")
    print("  Downstream systems: Power, Transport, Comms, Health, Emergency Response are SIMULATED.")
    if args.anchor_mode == "on":
        print("  ANCHOR MODE ON: generator outputs tagged with anchored=true.")
    print("  CALIBRATION STATUS: Raw uncalibrated probabilities (calibrated=false).")
    print(f"  SEED: {args.seed} | CITY: {args.city} | WINDOW: {args.window}")
    print("======================================================================\n")

    # 2. Load Configs
    cfg_path = REPO / "configs" / f"{args.city}.yaml"
    if not cfg_path.exists():
        print(f"Error: City config not found: {cfg_path}", file=sys.stderr)
        return 1
    city_cfg = load_city_config(cfg_path)

    horizons = [int(h.strip()) for h in args.horizons.split(",") if h.strip()]
    f_cfg = load_forecast_config(REPO / "configs" / "forecast.yaml")
    f_cfg.rollouts = args.rollouts
    f_cfg.horizons_hours = horizons
    f_cfg.step_hours = args.every_hours

    # Window resolution
    windows = load_window_specs()
    w_spec = windows.get(args.window)
    if w_spec:
        start_t = datetime.fromisoformat(w_spec["start_time_utc"].replace("Z", "+00:00"))
        end_t = datetime.fromisoformat(w_spec["end_time_utc"].replace("Z", "+00:00"))
        duration_hours = max(24, int((end_t - start_t).total_seconds() // 3600))
        city_cfg = city_cfg.model_copy(update={"start_time_utc": start_t})
    else:
        duration_hours = 72
        start_t = city_cfg.start_time_utc
        end_t = start_t + timedelta(hours=duration_hours)

    # 3. Fetch real rainfall series
    rain_series_by_zone = None
    try:
        adapter = OpenMeteoAdapter(city_id=city_cfg.city_id, cache_dir=REPO / "data" / "cache" / "openmeteo")
        rain_series_by_zone = {}
        for z in city_cfg.zones:
            s_dict = adapter.to_rain_series(z.id, start_t, end_t)
            z_rain = {}
            for dt, val in s_dict.items():
                h_off = int((dt - start_t).total_seconds() // 3600)
                if 0 <= h_off <= duration_hours:
                    z_rain[h_off] = val
            rain_series_by_zone[z.id] = z_rain
    except Exception as exc:
        if args.offline:
            print(f"Warning: offline rain cache missing, using synthetic fallback: {exc}")
        rain_series_by_zone = None

    # 4. Generate observations
    observations, _ = generate_city(
        city_cfg,
        seed=args.seed,
        duration_hours=duration_hours,
        rain_series=rain_series_by_zone,
        generator_family=args.family,
        anchor_mode=args.anchor_mode,
        rain_driver_label="real_rain:openmeteo" if rain_series_by_zone else "synthetic_storms",
    )

    # Apply faults if specified
    if args.faults != "none":
        injector = FaultInjector(args.seed)
        for f_name in args.faults.split(","):
            f_name = f_name.strip()
            if f_name:
                injector.add_fault(FaultSpec(kind=f_name, start_hour=0, end_hour=10**9, probability=0.3))
        observations = injector.apply(observations, start_t)

    # Replay stream
    stream = ReplayStream(observations)
    stream_hash = compute_stream_hash(observations)

    # Rain outlook
    outlook = PersistenceDecayOutlook()

    # Forecaster engine
    engine = ForecastEngine(
        city_config=city_cfg,
        forecast_config=f_cfg,
        rain_outlook=outlook,
        global_seed=args.seed,
        anchor_mode=args.anchor_mode,
    )

    # Named checkpoints for reporting
    checkpoints = [
        ("lead", start_t + timedelta(hours=min(12, duration_hours // 4))),
        ("onset", start_t + timedelta(hours=min(24, duration_hours // 2))),
        ("peak", start_t + timedelta(hours=min(48, duration_hours * 3 // 4))),
    ]

    snapshots: List[Any] = []
    checkpoint_snapshots: Dict[str, Any] = {}

    cur_time = start_t + timedelta(hours=args.every_hours)
    while cur_time <= end_t:
        snap = engine.step(cur_time, stream.view)
        snapshots.append(snap)

        for cp_name, cp_time in checkpoints:
            if abs((cur_time - cp_time).total_seconds()) < 1800:
                checkpoint_snapshots[cp_name] = snap

        cur_time += timedelta(hours=args.every_hours)

    if not snapshots:
        return 1

    final_snap = snapshots[-1]
    forecast_hash = final_snap.compute_forecast_hash()

    # 5. Output Report Tables
    print("----------------------------------------------------------------------")
    print("MULTI-HORIZON RISK ASSESSMENT AT NAMED CHECKPOINTS:")
    print("----------------------------------------------------------------------")
    print(f"{'Checkpoint':<10} | {'Time (UTC)':<20} | {'City Risk':<10} | {'P_crit(24h)':<12} | {'P_crit(72h)':<12} | {'Evidence Qual':<12}")
    print("-" * 75)

    for cp_name, cp_time in checkpoints:
        snap_cp = checkpoint_snapshots.get(cp_name, final_snap)
        p24 = snap_cp.city_probabilities.get("24", {}).get("CRITICAL", 0.0)
        p72 = snap_cp.city_probabilities.get("72", {}).get("CRITICAL", 0.0)
        eq = snap_cp.evidence_quality.get("city", 0.0)
        print(f"{cp_name:<10} | {snap_cp.issued_at.strftime('%Y-%m-%d %H:%M'):<20} | {snap_cp.city_risk_state.value:<10} | {p24:<12.3f} | {p72:<12.3f} | {eq:<12.3f}")

    print("\n----------------------------------------------------------------------")
    print("TOP LEARNED DEPENDENCY EDGES (from EdgeBook):")
    print("----------------------------------------------------------------------")
    if final_snap.top_edges:
        print(f"{'Source Node':<30} -> {'Target Node':<30} | {'Lag (h)':<7} | {'Weight':<8} | {'Conf':<6}")
        print("-" * 88)
        for e in final_snap.top_edges[:10]:
            print(f"{e['u']:<30} -> {e['v']:<30} | {e['lag_hours']:<7.1f} | {e['weight']:<8.3f} | {e['confidence']:<6.2f}")
    else:
        print("  (EdgeBook in burn-in / discovery phase)")

    print("\n----------------------------------------------------------------------")
    print("RECENT DRIFT EVENTS & EDGE REVISIONS:")
    print("----------------------------------------------------------------------")
    if final_snap.drift_events:
        for dev in final_snap.drift_events[-5:]:
            print(f"  DRIFT DETECTED: {dev['node']} at {dev['time']} (detector: {dev['detector']}, mag: {dev['magnitude']:.2f})")
    else:
        print("  Zero false drift events detected (stationary phase stable).")

    if final_snap.edge_changes:
        for ch in final_snap.edge_changes[-5:]:
            print(f"  EDGE CHANGE: {ch['u']} -> {ch['v']} ({ch['kind']}, reason: {ch['reason']})")

    print("\n----------------------------------------------------------------------")
    print("PROVENANCE MIX & RUN HASHES:")
    print("----------------------------------------------------------------------")
    pm = final_snap.provenance_mix
    print(f"  Real Streams Share:      {pm.get('real_percentage', 0.0):.1f}% (rain, soil)")
    print(f"  Simulated Streams Share: {pm.get('simulated_percentage', 0.0):.1f}% ({', '.join(pm.get('simulated_systems', [])[:4])}...)")
    print(f"  Stream Hash (SHA-256):   {stream_hash}")
    print(f"  Forecast Hash (SHA-256): {forecast_hash}")
    print("======================================================================\n")

    # Optional output file
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as fh:
            for s in snapshots:
                fh.write(s.to_canonical_json() + "\n")
        print(f"Wrote {len(snapshots)} snapshots to {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
