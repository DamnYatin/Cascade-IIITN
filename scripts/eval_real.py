"""CLI script to run Real-Event Check on Assam 2026 (G7).

Rule V5:
  - Runs with anchor_mode='off'
  - Outputs results to eval/real_event_summary.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.eval.realcheck import evaluate_real_assam_event

REAL_EVENT_OUT_PATH = REPO_ROOT / "eval" / "real_event_summary.json"


def main():
    print("=== RUNNING REAL-EVENT EVALUATION ON ASSAM 2026 (ANCHOR_MODE=OFF) ===")
    results = evaluate_real_assam_event(
        city_id="upper_assam",
        anchor_mode="off",
        tau=0.15,
        k=1,
        tau_low=0.15,
        duration_hours=168,
        cadence_hours=3,
        rollouts=50,
    )
    with REAL_EVENT_OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    summary = results["evaluation_summary"]
    nc = results["negative_controls"]
    print(f"Successfully evaluated real Assam 2026 event:")
    print(f"  Total Labels: {summary['total_labels']}, Hits: {summary['hits']}, Late: {summary['late_alerts']}, Misses: {summary['misses']}")
    print(f"  POD: {summary['pod']}, Milestone Rank Correlation: {summary['milestone_rank_correlation']} (n={summary['rank_n']})")
    print(f"  Negative controls: {nc['unaffected_zones_alert_count']} alerts in {len(nc['unaffected_zones'])} unaffected zones")
    print(f"  Saved summary to: {REAL_EVENT_OUT_PATH}")


if __name__ == "__main__":
    main()
