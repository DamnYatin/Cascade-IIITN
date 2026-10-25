"""Phase 1 replay CLI.

Usage:
  python scripts/run_replay.py --city mumbai --seed 1 --hours 168 \
      --family logistic_hazard --faults spike,zone_blackout --rain-window none

Prints a developer summary: number of observations, mean delay, out-of-order
fraction, faults applied, and ground-truth CRITICAL episode counts.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from backend.app.city_config import load_city_config  # noqa: E402
from backend.app.adapters.imd_rain import IMDRainAdapter, PRESETS  # noqa: E402
from backend.app.replay.faults import FaultInjector, FaultSpec  # noqa: E402
from backend.app.replay.stream import ReplayStream  # noqa: E402
from backend.app.synth.generator import generate_city  # noqa: E402

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
            # blackout the first zone in the config during the middle of the horizon
            injector.add_fault(FaultSpec(kind="zone_blackout", target_zone=None,
                                       start_hour=0, end_hour=10**9, probability=1.0))
    return injector.faults


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run a Phase 1 replay.")
    ap.add_argument("--city", default="mumbai", help="city config id (mumbai | heldout)")
    ap.add_argument("--seed", type=int, default=1, help="master seed (deterministic)")
    ap.add_argument("--hours", type=int, default=168, help="simulated hours")
    ap.add_argument("--family", default="logistic_hazard",
                    help="logistic_hazard | threshold_nonlinear")
    ap.add_argument("--faults", default="",
                    help="comma-separated fault kinds")
    ap.add_argument("--rain-window", default="none",
                    help="none | mumbai_2019 | konkan_2021 (real rain as exogenous input)")
    ap.add_argument("--rain-csv", default="data/processed/maharashtra_climate.csv")
    args = ap.parse_args(argv)

    cfg_path = REPO / "configs" / f"{args.city}.yaml"
    if not cfg_path.exists():
        alt = REPO / "configs" / f"{args.city}_city.yaml"
        if alt.exists():
            cfg_path = alt
        else:
            print(f"city config not found: {cfg_path} (or {alt})", file=sys.stderr)
            return 2
    cfg = load_city_config(cfg_path)

    # --- real rain as exogenous series (optional) ---
    rain_series = None
    rain_note = "synthetic storms"
    if args.rain_window != "none":
        if args.rain_window not in PRESETS:
            print(f"unknown rain-window {args.rain_window!r}; options: none, "
                  f"{sorted(PRESETS)}", file=sys.stderr)
            return 2
        p = PRESETS[args.rain_window]
        adapter = IMDRainAdapter(REPO / args.rain_csv, seed=args.seed)
        adapter.load()
        start_d = datetime.strptime(p["start"], "%Y-%m-%d").date()
        end_d = datetime.strptime(p["end"], "%Y-%m-%d").date()
        dt_series = adapter.to_rain_series(
            p["districts"][0], start_d, end_d, seed=args.seed
        )
        start_ts = cfg.start_time_utc
        rain_series = {}
        for dt, v in dt_series.items():
            off = int((dt - start_ts).total_seconds() // 3600)
            if 0 <= off <= args.hours:
                rain_series[off] = rain_series.get(off, 0.0) + v
        rain_note = f"real rain ({args.rain_window})"

    # --- generate city (observations + hidden ground truth) ---
    observations, gt = generate_city(
        cfg, args.seed, args.hours,
        rain_series=rain_series,
        generator_family=args.family,
    )

    # --- apply faults ---
    injector = FaultInjector(args.seed)
    for f in _build_faults(args.faults, args.seed):
        injector.add_fault(f)
    faulted = injector.apply(list(observations), cfg.start_time_utc)

    # --- stream ---
    stream = ReplayStream(faulted)
    # Release everything at the end of the horizon to compute summary stats.
    end_time = cfg.start_time_utc + timedelta(hours=args.hours)
    released = stream.release_until(end_time + timedelta(hours=1))

    delays = [(o.arrival_time - o.event_time).total_seconds() / 3600.0 for o in released]
    mean_delay = sum(delays) / len(delays) if delays else 0.0

    # out-of-order fraction: observations whose event_time is earlier than the
    # previous released observation's event_time (arrival order != event order).
    out_of_order = 0
    prev_event = None
    for o in released:
        if prev_event is not None and o.event_time < prev_event:
            out_of_order += 1
        prev_event = o.event_time
    ooo_frac = out_of_order / len(released) if released else 0.0

    print("=" * 60)
    print("PHASE 1 REPLAY SUMMARY")
    print("=" * 60)
    print(f"city        : {cfg.city_id}")
    print(f"seed        : {args.seed}")
    print(f"family      : {args.family}")
    print(f"hours       : {args.hours}")
    print(f"rain input  : {rain_note}")
    print(f"zones x systems: {len(cfg.zones)} x {len(cfg.systems)} "
          f"= {len(cfg.zones) * len(cfg.systems)} nodes")
    print()
    print("stream:")
    print(f"  observations released : {len(released)}")
    print(f"  mean delay (h)        : {mean_delay:.3f}")
    print(f"  out-of-order fraction : {ooo_frac:.3f}")
    print(f"  fault kinds           : {args.faults or 'none'}")
    print(f"  fault log entries     : {len(injector.fault_log)}")
    print()
    print("GROUND TRUTH (developer only -- not on the stream):")
    print(f"  generator family      : {gt.generator_family}")
    print(f"  CRITICAL episodes     : {len(gt.critical_episodes)} (per node)")
    print(f"  city-critical ranges  : {len(gt.city_critical_episodes)}")
    print(f"  planted edges         : {len(gt.planted_edges)}")
    print(f"  decoy pairs           : {len(gt.decoy_pairs)}")
    by_node = {}
    for ep in gt.critical_episodes:
        by_node[ep.node_id] = by_node.get(ep.node_id, 0) + 1
    if by_node:
        top = sorted(by_node.items(), key=lambda kv: -kv[1])[:5]
        print(f"  top critical nodes    : {top}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
