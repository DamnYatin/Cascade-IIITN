"""Operating point and threshold tuning script for Phase 3 Evaluation.

Selects optimal (tau, k, tau_low) on DEV SEEDS {11, 12, 13} following pre-registered rule:
  - Maximize POD subject to FAR_zone_days <= 1.0
  - Tie-break by larger median lead time
  - Saves tuned mapper thresholds to configs/forecast_tuned.yaml with provenance.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.eval.protocol import DEV_SEEDS, compute_protocol_hash
from backend.app.eval.runner import EvalRunConfig, run_batch_evaluations, run_single_evaluation
from backend.app.eval.sweeps import SweepPoint, evaluate_threshold_point, select_operating_point
from backend.app.forecast.config import load_forecast_config

TUNED_CONFIG_PATH = REPO_ROOT / "configs" / "forecast_tuned.yaml"


def get_git_commit() -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        return out
    except Exception:
        return "unknown"


def tune_dev_operating_points(
    seeds: List[int] = DEV_SEEDS,
    city_id: str = "upper_assam",
    duration_hours: int = 168,
    cadence_hours: int = 3,
    rollouts: int = 50,
) -> Dict[str, Any]:
    """Execute threshold sweep on dev seeds across all methods and select operating points."""
    print(f"=== TUNING OPERATING POINTS ON DEV SEEDS {seeds} ===")
    methods = [
        "forecaster",
        "b1_isolated",
        "b2_rainrule",
        "b3_climatology",
        "b4_static_graph",
        "b5_prior_only",
        "b6_no_trust",
        "b7_persistence_outlook",
    ]

    method_runs: Dict[str, List[Dict[str, Any]]] = {}

    for method in methods:
        print(f"Running DEV simulations for method: {method}...")
        runs = []
        for seed in seeds:
            calib_source = "frozen" if method == "forecaster" else "none"
            run_cfg = EvalRunConfig(
                city_id=city_id,
                family="F-storm",
                seed=seed,
                duration_hours=duration_hours,
                cadence_hours=cadence_hours,
                rollouts=rollouts,
                method=method,
                calibrator_source=calib_source,
            )
            res = run_single_evaluation(run_cfg, use_cache=True)
            runs.append(res)
        method_runs[method] = runs

    # Candidate grid for sweeps
    taus = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60]
    ks = [1, 2, 3]

    tuned_results: Dict[str, Any] = {}

    for method, runs in method_runs.items():
        # Combine all zone scores and true episodes across dev seeds
        zone_scores_all: Dict[str, Tuple[List[float], List[float]]] = {}
        zone_episodes_all: Dict[str, List[Any]] = {}

        total_hours = 0.0
        for r in runs:
            seed = r["seed"]
            hours = r["hours"]
            total_hours += float(r["duration_hours"])
            for z_id, p_list in r["zone_p_crit_72"].items():
                k_key = f"{seed}_{z_id}"
                zone_scores_all[k_key] = (p_list, hours)
                # Parse episodes
                from backend.app.eval.events import TrueEpisode
                eps = [
                    TrueEpisode(
                        episode_id=f"{seed}_{ep['episode_id']}",
                        entity_type="zone_cascade",
                        entity_id=k_key,
                        level="CRITICAL",
                        start_hour=ep["start_hour"],
                        end_hour=ep["end_hour"],
                        peak_value=ep["peak_value"],
                    )
                    for ep in r["true_zone_cascade_episodes"].get(z_id, [])
                ]
                zone_episodes_all[k_key] = eps

        sweep_points: List[SweepPoint] = []
        for tau in taus:
            for k in ks:
                for delta in [0.0, 0.10]:
                    tau_low = max(0.05, tau - delta)
                    pt = evaluate_threshold_point(
                        zone_scores=zone_scores_all,
                        zone_episodes=zone_episodes_all,
                        tau=tau,
                        k=k,
                        tau_low=tau_low,
                        total_duration_hours=total_hours / len(runs),
                    )
                    sweep_points.append(pt)

        best_pt, feasible = select_operating_point(sweep_points, target_far=1.0)
        tuned_results[method] = {
            "tau": best_pt.tau,
            "k": best_pt.k,
            "tau_low": best_pt.tau_low,
            "pod": best_pt.pod,
            "far_per_100_zone_days": best_pt.far_per_100_zone_days,
            "lead_time_median": best_pt.lead_time_median,
            "feasible_under_target_far": feasible,
            "total_points_swept": len(sweep_points),
        }
        print(f"  [{method}] Selected tau={best_pt.tau}, k={best_pt.k}, tau_low={best_pt.tau_low} -> POD={best_pt.pod:.3f}, FAR={best_pt.far_per_100_zone_days:.2f}, Lead={best_pt.lead_time_median:.1f}h (Feasible: {feasible})")

    # Generate configs/forecast_tuned.yaml
    base_cfg = load_forecast_config()
    fc_tuned = tuned_results["forecaster"]

    tuned_yaml_data = base_cfg.model_dump()
    tuned_yaml_data["mapper"]["alert_tau"] = fc_tuned["tau"]
    tuned_yaml_data["mapper"]["alert_k"] = fc_tuned["k"]

    provenance = {
        "dev_seeds": DEV_SEEDS,
        "protocol_hash": compute_protocol_hash(),
        "commit_hash": get_git_commit(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "all_methods_tuned": tuned_results,
    }
    tuned_yaml_data["provenance"] = provenance

    with TUNED_CONFIG_PATH.open("w", encoding="utf-8") as f:
        yaml.dump(tuned_yaml_data, f, sort_keys=False)

    print(f"\nWrote pre-registered tuned configuration to: {TUNED_CONFIG_PATH}")
    return tuned_results


if __name__ == "__main__":
    tune_dev_operating_points()
