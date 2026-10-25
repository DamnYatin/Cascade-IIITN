"""Phase 1 replay CLI for Assam flood scenarios.

Usage:
  python scripts/run_replay.py --city upper_assam --seed 7 --hours 72 --rain-window peak
  python scripts/run_replay.py --city north_bank_assam --seed 1 --hours 48

Features:
  - Supports named scenario windows (warmup, lead, onset, peak, recession, hero_full).
  - Supports multiple real rain sources (openmeteo, imerg_late, era5land).
  - Honesty switch: --anchor off|on (default off).
  - Outputs per-stream provenance breakdown (real vs simulated, summing to 100%).
  - Outputs deterministic SHA-256 stream hash computed over canonical bytes.
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
from backend.app.adapters.imerg import IMERGAdapter
from backend.app.adapters.era5land import ERA5LandAdapter
from backend.app.city_config import load_city_config
from backend.app.replay.faults import FaultInjector, FaultSpec
from backend.app.replay.stream import ReplayStream
from backend.app.schemas import Observation, QualityFlag, SourceKind
from backend.app.synth.generator import generate_city

FAULT_KINDS = {
    "dropout", "stuck_at", "spike", "feed_delay",
    "contradictory_duplicate", "citizen_spam", "zone_blackout",
}


def _build_faults(spec: str, seed: int) -> list[FaultSpec]:
    faults = []
    if not spec:
        return faults
    injector = FaultInjector(seed)
    for kind in [k.strip() for k in spec.split(",") if k.strip() and k.strip() != "none"]:
        if kind not in FAULT_KINDS:
            raise ValueError(f"unknown fault kind {kind!r}; options: {sorted(FAULT_KINDS)}")
        if kind == "spike":
            injector.add_fault(FaultSpec(kind="spike", target_zone=None, start_hour=0,
                                       end_hour=10**9, probability=0.3, spike_magnitude=15.0))
        elif kind == "dropout":
            injector.add_fault(FaultSpec(kind="dropout", target_zone=None, start_hour=0,
                                       end_hour=10**9, probability=0.1))
        elif kind == "stuck_at":
            injector.add_fault(FaultSpec(kind="stuck_at", target_zone=None, start_hour=0,
                                       end_hour=10**9, probability=0.1, stuck_value=0.0))
        elif kind == "feed_delay":
            injector.add_fault(FaultSpec(kind="feed_delay", target_zone=None, start_hour=0,
                                       end_hour=10**9, probability=0.2, delay_hours=3.0))
        elif kind == "contradictory_duplicate":
            injector.add_fault(FaultSpec(kind="contradictory_duplicate", target_zone=None,
                                       start_hour=0, end_hour=10**9, probability=0.15))
        elif kind == "citizen_spam":
            injector.add_fault(FaultSpec(kind="citizen_spam", target_zone=None,
                                       start_hour=0, end_hour=10**9, probability=0.5,
                                       burst_count=30))
        elif kind == "zone_blackout":
            injector.add_fault(FaultSpec(kind="zone_blackout", target_zone=None,
                                       start_hour=0, end_hour=10**9, probability=1.0))
    return injector.faults


def compute_stream_hash(observations: list[Observation]) -> str:
    """Compute deterministic SHA-256 hash over canonical representation of observations."""
    canonical_items = []
    for obs in sorted(observations, key=lambda o: (o.arrival_time, o.event_time, o.node_id or "", o.obs_id)):
        canonical_items.append({
            "source": obs.source,
            "source_kind": obs.source_kind.value if hasattr(obs.source_kind, "value") else str(obs.source_kind),
            "zone": obs.zone,
            "system": obs.system,
            "value": round(float(obs.value), 4),
            "event_time": obs.event_time.isoformat(),
            "arrival_time": obs.arrival_time.isoformat(),
            "quality_flags": [str(f.value if hasattr(f, "value") else f) for f in obs.quality_flags],
        })
    canonical_bytes = json.dumps(canonical_items, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


def load_scenario_windows() -> dict:
    windows_path = REPO / "configs" / "scenarios" / "assam_2026" / "windows.yaml"
    if windows_path.exists():
        with windows_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data.get("windows", {})
    return {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run an Assam flood Phase 1 replay.")
    ap.add_argument("--city", default="upper_assam", help="city config id (upper_assam | north_bank_assam)")
    ap.add_argument("--scenario", default="assam_2026", help="scenario id")
    ap.add_argument("--seed", type=int, default=1, help="master seed (deterministic)")
    ap.add_argument("--hours", type=int, default=72, help="simulated hours")
    ap.add_argument("--family", default="logistic_hazard", help="logistic_hazard | threshold_nonlinear")
    ap.add_argument("--faults", default="", help="comma-separated fault kinds")
    ap.add_argument("--rain-window", default="peak",
                    help="none | warmup | lead | onset | peak | recession | hero_full")
    ap.add_argument("--rain-source", default="openmeteo",
                    help="openmeteo | imerg_late | era5land | all | none")
    ap.add_argument("--anchor", default="off", choices=["off", "on"], help="anchor honesty switch (off | on)")
    ap.add_argument("--offline", action="store_true", help="run strictly offline against cached data")
    args = ap.parse_args(argv)

    cfg_path = REPO / "configs" / f"{args.city}.yaml"
    if not cfg_path.exists():
        print(f"Error: city config not found: {cfg_path}", file=sys.stderr)
        return 2
    cfg = load_city_config(cfg_path)

    windows = load_scenario_windows()
    start_ts = cfg.start_time_utc
    duration_hours = args.hours

    if args.rain_window in windows:
        w = windows[args.rain_window]
        start_ts = datetime.fromisoformat(w["start_time_utc"].replace("Z", "+00:00"))
        end_ts = datetime.fromisoformat(w["end_time_utc"].replace("Z", "+00:00"))
        duration_hours = min(args.hours, int((end_ts - start_ts).total_seconds() // 3600))
        # Update config start_time_utc
        cfg = cfg.model_copy(update={"start_time_utc": start_ts})

    # --- Load real rain if specified ---
    rain_series_by_zone: dict[str, dict[int, float]] = {z.id: {} for z in cfg.zones}
    real_observations: list[Observation] = []
    rain_note = "synthetic storms"

    if args.rain_window != "none" and args.rain_source != "none":
        end_eval_ts = start_ts + timedelta(hours=duration_hours)
        adapter = OpenMeteoAdapter(city_id=cfg.city_id)
        try:
            for z in cfg.zones:
                s_dict = adapter.to_rain_series(z.id, start_ts, end_eval_ts)
                for dt, v in s_dict.items():
                    h_off = int((dt - start_ts).total_seconds() // 3600)
                    if 0 <= h_off <= duration_hours:
                        rain_series_by_zone[z.id][h_off] = v
                # Real rain observations
                obs_list = adapter.to_observations(z.id, start_ts, end_eval_ts)
                real_observations.extend(obs_list)
            rain_note = f"real rain ({args.rain_source}, window: {args.rain_window})"
        except FileNotFoundError as exc:
            if args.offline:
                print(f"Error running offline: {exc}", file=sys.stderr)
                return 2
            print(f"[NOTE] Cache not found ({exc}); proceeding with synthetic rain.", file=sys.stderr)
            rain_series_by_zone = None

    # --- Generate simulated city systems driven by real rain ---
    observations, gt = generate_city(
        cfg,
        seed=args.seed,
        duration_hours=duration_hours,
        rain_series=rain_series_by_zone,
        generator_family=args.family,
        anchor_mode=args.anchor,
        rain_driver_label=f"real_rain:{args.rain_source}" if rain_series_by_zone else "synthetic_storms",
    )

    # Combine real observations with simulated system observations
    all_observations = list(real_observations) + list(observations)

    # --- Apply faults ---
    injector = FaultInjector(args.seed)
    for f in _build_faults(args.faults, args.seed):
        injector.add_fault(f)
    faulted = injector.apply(all_observations, cfg.start_time_utc)

    # --- Replay Stream ---
    stream = ReplayStream(faulted)
    end_time = cfg.start_time_utc + timedelta(hours=duration_hours)
    released = stream.release_until(end_time + timedelta(hours=1))

    # --- Summary Statistics ---
    delays = [(o.arrival_time - o.event_time).total_seconds() / 3600.0 for o in released]
    mean_delay = sum(delays) / len(delays) if delays else 0.0

    out_of_order = 0
    prev_event = None
    for o in released:
        if prev_event is not None and o.event_time < prev_event:
            out_of_order += 1
        prev_event = o.event_time
    ooo_frac = out_of_order / len(released) if released else 0.0

    # Provenance Breakdown
    real_count = sum(1 for o in released if o.source_kind == SourceKind.REAL)
    sim_count = sum(1 for o in released if o.source_kind == SourceKind.SIMULATED)
    disagg_count = sum(1 for o in released if o.source_kind == SourceKind.DISAGGREGATED)
    total_obs = len(released)
    real_pct = (real_count / total_obs * 100.0) if total_obs else 0.0
    sim_pct = (sim_count / total_obs * 100.0) if total_obs else 0.0
    disagg_pct = (disagg_count / total_obs * 100.0) if total_obs else 0.0

    stream_hash = compute_stream_hash(released)

    print("=" * 65)
    print("THE 72-HOUR WARNING — ASSAM PHASE 1 REPLAY SUMMARY")
    print("=" * 65)
    print(f"city                   : {cfg.city_id}")
    print(f"seed                   : {args.seed}")
    print(f"family                 : {args.family}")
    print(f"anchor mode            : {args.anchor}")
    print(f"rain window            : {args.rain_window} ({rain_note})")
    print(f"start time (UTC)       : {cfg.start_time_utc.isoformat()}")
    print(f"simulated hours        : {duration_hours}")
    print(f"zones x systems        : {len(cfg.zones)} zones x {len(cfg.systems)} systems")
    print()
    print("PROVENANCE MATRIX:")
    print(f"  total observations   : {total_obs}")
    print(f"  real observations    : {real_count} ({real_pct:.1f}%)")
    print(f"  simulated observations: {sim_count} ({sim_pct:.1f}%)")
    if disagg_count:
        print(f"  disaggregated obs    : {disagg_count} ({disagg_pct:.1f}%)")
    print(f"  provenance total     : {real_pct + sim_pct + disagg_pct:.1f}%")
    print()
    print("STREAM METRICS:")
    print(f"  mean arrival delay   : {mean_delay:.2f} hours")
    print(f"  out-of-order arrival : {ooo_frac:.3f}")
    print(f"  faults applied       : {args.faults or 'none'}")
    print(f"  stream sha256 hash   : {stream_hash}")
    print()
    print("GROUND TRUTH (isolated from replay view):")
    print(f"  CRITICAL episodes    : {len(gt.critical_episodes)} (per node)")
    print(f"  city-critical ranges : {len(gt.city_critical_episodes)}")
    print(f"  planted edges        : {len(gt.planted_edges)}")
    print(f"  decoy pairs          : {len(gt.decoy_pairs)}")
    print("=" * 65)
    return 0


if __name__ == "__main__":
    sys.exit(main())
