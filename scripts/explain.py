"""Command-Line Interface for Causal Explainability (Phase 4).

Prints:
  - Current risk state and top causal candidate drivers.
  - Predicted failure chain tree with ETAs, probabilities, learned lags, and weights.
  - Evidence receipts behind key links.
  - Detected reinforcing loops and interacting simultaneous cascades.
  - Mandatory honesty banners: downstream streams simulated; estimates under learned model.
"""
from __future__ import annotations

import argparse
from datetime import timedelta
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.city_config import load_city_config
from backend.app.explain.coordinator import explain_snapshot
from backend.app.forecast.config import ForecastConfig
from backend.app.forecast.engine import ForecastEngine
from backend.app.replay.clock import ReplayClock
from backend.app.replay.stream import ReplayStream, StreamView
from backend.app.synth.generator import generate_city

HONESTY_BANNER = """
================================================================================
THE 72-HOUR WARNING — CAUSAL EXPLANATIONS (PHASE 4)
HONESTY DISCLOSURE:
  - Real meteorological inputs are rainfall and soil moisture.
  - Downstream infrastructure (power, transport, comms, health, response) is SIMULATED.
  - Learned dependencies are CAUSAL CANDIDATES under the statistical model, NOT proven causes.
================================================================================
"""


def format_tree_text(node: dict, indent: int = 0) -> str:
    """Format hierarchical failure chain tree into a readable string."""
    pad = "  " * indent
    lines = []
    node_id = node.get("node", "root")
    p = node.get("probability_within_horizon", 0.0)
    cond = node.get("conditional", {})
    p50 = cond.get("p50")
    eta_str = f"ETA p50: +{p50:.1f}h" if p50 is not None else "ETA: inf"
    link_info = ""
    if node.get("link"):
        l = node["link"]
        link_info = f" [via {l['u']} lag={l['lag_hours']:.1f}h w={l['weight']:+.2f} conf={l['confidence']:.2f} p_link={l['p_link']:.2f}]"

    lines.append(f"{pad}├── {node_id} (P={p*100.0:.1f}%, {eta_str}){link_info}")
    for branch in node.get("branches", []):
        lines.append(format_tree_text(branch, indent + 1))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Explain cascade drivers and predicted failure chains.")
    parser.add_argument("--city", default="upper_assam", help="City configuration identifier")
    parser.add_argument("--seed", type=int, default=1, help="Simulation seed")
    parser.add_argument("--rain-window", default="peak", help="Rain window scenario (lead|onset|peak)")
    parser.add_argument("--anchor", default="off", help="Anchor mode (off|on)")
    parser.add_argument("--hour", type=float, default=24.0, help="Replay clock hour to evaluate")
    parser.add_argument("--zone", default=None, help="Specific zone to explain (default: city-level)")
    parser.add_argument("--output", default=None, help="Optional JSON output filepath")
    args = parser.parse_args()

    cfg_path = REPO_ROOT / "configs" / f"{args.city}.yaml"
    if not cfg_path.exists():
        print(f"Error: City config not found at {cfg_path}", file=sys.stderr)
        sys.exit(1)

    city_cfg = load_city_config(cfg_path)
    obs, _ = generate_city(
        city_cfg,
        args.seed,
        max(72, int(args.hour + 24)),
        anchor_mode=args.anchor,
    )
    stream = ReplayStream(obs)
    clock = ReplayClock(city_cfg.start_time_utc)
    target_time = city_cfg.start_time_utc + timedelta(hours=args.hour)
    clock.advance(args.hour)
    view = StreamView(stream, clock.now)

    engine = ForecastEngine(
        city_config=city_cfg,
        forecast_config=ForecastConfig(rollouts=150),
        global_seed=args.seed,
        anchor_mode=args.anchor,
    )
    _ = engine.step(clock.now, view, enable_trace=True)

    subject = args.zone if args.zone else "city"
    record = explain_snapshot(engine, subject=subject)

    print(HONESTY_BANNER)
    print(f"Issued At:      {record.issued_at.isoformat()}")
    print(f"Subject:        {record.subject} ({record.subject_kind})")
    print(f"Risk State:     {record.risk_state_from} -> {record.risk_state_to}")
    print(f"P(Critical 72h): {record.probability_before*100.0:.1f}% -> {record.probability_after*100.0:.1f}%")
    print(f"Confidence:     {record.confidence:.2f} ({record.confidence_category})")
    if record.abstentions:
        print(f"Abstentions:    {', '.join(record.abstentions)}")

    print("\n--- Hedged Summary ---")
    print(record.text)

    print("\n--- Top Causal Candidate Drivers ---")
    for idx, d in enumerate(record.drivers[:5], 1):
        print(f"  {idx}. [{d.driver_type}] {d.label}")
        print(f"     Contribution: {d.contribution:+.4f} (95% CI: [{d.ci_lower:+.4f}, {d.ci_upper:+.4f}]) Direction: {d.direction}")
        if d.evidence_receipt:
            rc = d.evidence_receipt
            print(f"     Receipt: {len(rc.observation_ids)} obs (sources: {rc.sources[:3]}), parent simulated={rc.simulated_parent_flag}")

    print("\n--- Predicted Failure Chain Tree ---")
    print(format_tree_text(record.chain_tree))

    if record.loops:
        print("\n--- Detected Reinforcing Feedback Loops ---")
        for loop in record.loops:
            print(f"  Loop {loop.loop_id}: {' -> '.join(loop.nodes)} (Amplification: {loop.amplification_factor:.2f}x, Weakest Link: {loop.weakest_link})")

    if record.concurrent_clusters:
        print("\n--- Interacting Concurrent Cascades ---")
        for cl in record.concurrent_clusters:
            print(f"  Cluster {cl.cluster_id}: roots={cl.root_nodes} converging={cl.converging_nodes}")
            print(f"    Joint P={cl.joint_p_critical:.2f} vs Independent P={cl.independent_p_critical:.2f} (Delta: {cl.interaction_delta:+.2f})")

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(record.canonical_json(), encoding="utf-8")
        print(f"\nSaved ExplanationRecord to {out_path}")


if __name__ == "__main__":
    main()
