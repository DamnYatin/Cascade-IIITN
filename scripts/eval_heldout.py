"""Held-Out Evaluation Script for Phase 3 (G8).

Rule V3 Compliance:
  - Protocol and code commit hashes are locked in eval/heldout_lock.json.
  - Held-out seeds {101..105} are evaluated ONCE and only once.
  - No thresholds or hyperparameters are tuned on held-out seeds.
  - Generates final evaluation numbers for F-storm, F-quiet, and F-heldout-city.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.city_config import load_city_config
from backend.app.eval.alerts import AlertRun, attribute_alerts, detect_alert_runs
from backend.app.eval.events import TrueEpisode
from backend.app.eval.metrics import (
    bootstrap_metric_ci,
    brier_score,
    brier_skill_score,
    compute_reliability_bins,
    compute_warning_metrics,
    expected_calibration_error,
)
from backend.app.eval.protocol import (
    HELDOUT_SEEDS,
    PROTOCOL_FAMILIES,
    check_heldout_lock,
    compute_protocol_hash,
    write_heldout_lock,
)
from backend.app.eval.runner import EvalRunConfig, run_single_evaluation

HELDOUT_RESULTS_PATH = REPO_ROOT / "eval" / "heldout_results.json"
TUNED_CONFIG_PATH = REPO_ROOT / "configs" / "forecast_tuned.yaml"


def get_git_commit() -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        return out
    except Exception:
        return "unknown"


def compute_file_hash(p: Path) -> str:
    if not p.exists():
        return "missing"
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def run_heldout_evaluation(
    allow_rerun: bool = False,
    seeds: List[int] = HELDOUT_SEEDS,
    duration_hours: int = 168,
    cadence_hours: int = 3,
    rollouts: int = 50,
) -> Dict[str, Any]:
    print("=== EXECUTING HELD-OUT EVALUATION (PHASE 3 FREEZE) ===")

    # 1. Check lock
    can_proceed, reruns, lock_data = check_heldout_lock(allow_rerun=allow_rerun)
    if not can_proceed:
        raise RuntimeError(
            "Held-out evaluation is already LOCKED. "
            "To re-run with auditable tracking, pass --allow-rerun."
        )

    # 2. Compute hashes
    proto_hash = compute_protocol_hash()
    commit_hash = get_git_commit()
    cfg_hashes = {
        "upper_assam": compute_file_hash(REPO_ROOT / "configs" / "upper_assam.yaml"),
        "north_bank_assam": compute_file_hash(REPO_ROOT / "configs" / "north_bank_assam.yaml"),
        "forecast_tuned": compute_file_hash(TUNED_CONFIG_PATH),
    }

    # Write lock
    write_heldout_lock(
        protocol_hash=proto_hash,
        code_commit_hash=commit_hash,
        config_hashes=cfg_hashes,
        allow_rerun=allow_rerun,
    )

    # Load tuned operating points
    with TUNED_CONFIG_PATH.open("r", encoding="utf-8") as f:
        tuned_cfg_data = yaml.safe_load(f)
    methods_tuned = tuned_cfg_data.get("provenance", {}).get("all_methods_tuned", {})

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

    all_method_metrics: Dict[str, Any] = {}

    for method in methods:
        print(f"Evaluating {method} on held-out seeds {seeds} (F-storm)...")
        # Operating point for method
        op = methods_tuned.get(method, {"tau": 0.15, "k": 1, "tau_low": 0.15})
        tau = op["tau"]
        k = op["k"]
        tau_low = op["tau_low"]

        method_runs = []
        for seed in seeds:
            calib_source = "frozen" if method == "forecaster" else "none"
            rcfg = EvalRunConfig(
                city_id="upper_assam",
                family="F-storm",
                seed=seed,
                duration_hours=duration_hours,
                cadence_hours=cadence_hours,
                rollouts=rollouts,
                method=method,
                calibrator_source=calib_source,
            )
            r = run_single_evaluation(rcfg, use_cache=True)
            method_runs.append(r)

        # Compute metric aggregates across held-out runs
        all_probs: List[float] = []
        all_outcomes: List[float] = []
        all_hits = 0
        all_misses = 0
        all_late = 0
        all_fa = 0
        all_leads: List[float] = []
        all_zone_days = 0.0

        per_seed_data = []

        for r in method_runs:
            s_seed = r["seed"]
            hours = r["hours"]
            episodes_by_zone = r["true_zone_cascade_episodes"]
            num_zones = len(r["zone_p_crit_72"])
            z_days = (num_zones * float(r["duration_hours"])) / 24.0
            all_zone_days += z_days

            seed_hits = 0
            seed_misses = 0
            seed_fa = 0
            seed_leads = []

            for z_id, p_list in r["zone_p_crit_72"].items():
                eps_data = episodes_by_zone.get(z_id, [])
                true_eps = [
                    TrueEpisode(
                        episode_id=ep["episode_id"],
                        entity_type="zone_cascade",
                        entity_id=z_id,
                        level="CRITICAL",
                        start_hour=ep["start_hour"],
                        end_hour=ep["end_hour"],
                        peak_value=ep["peak_value"],
                    )
                    for ep in eps_data
                ]

                # Alert runs
                alert_runs = detect_alert_runs(
                    scores=p_list,
                    hours=hours,
                    tau=tau,
                    k=k,
                    tau_low=tau_low,
                    k_off=2,
                    entity_id=z_id,
                )

                # Attribute
                attr = attribute_alerts(alert_runs=alert_runs, episodes=true_eps, h_hit=72.0)
                seed_hits += len(attr.hits)
                seed_misses += len(attr.missed_episodes)
                seed_fa += len(attr.false_alarms)
                seed_leads.extend(attr.lead_times)

                # Pointwise outcomes for Brier/ECE
                for h, p in zip(hours, p_list):
                    occurs = any(0.0 < (ep.start_hour - h) <= 72.0 for ep in true_eps)
                    all_probs.append(float(p))
                    all_outcomes.append(1.0 if occurs else 0.0)

            all_hits += seed_hits
            all_misses += seed_misses
            all_fa += seed_fa
            all_leads.extend(seed_leads)

            per_seed_data.append({
                "seed": s_seed,
                "hits": seed_hits,
                "misses": seed_misses,
                "false_alarms": seed_fa,
                "lead_times": seed_leads,
            })

        # Summary numbers
        pod = all_hits / (all_hits + all_misses) if (all_hits + all_misses) > 0 else 0.0
        far_per_100 = (all_fa / all_zone_days) * 100.0 if all_zone_days > 0 else 0.0
        bs = brier_score(all_probs, all_outcomes)
        ece = expected_calibration_error(all_probs, all_outcomes, n_bins=10)
        median_lead = float(np.median(all_leads)) if all_leads else 0.0
        iqr_lead = float(np.percentile(all_leads, 75) - np.percentile(all_leads, 25)) if len(all_leads) >= 4 else 0.0

        # Blocked bootstrap 95% CIs
        # Group episodes by seed for lead times
        seed_lead_groups = [s["lead_times"] for s in per_seed_data if s["lead_times"]]
        if seed_lead_groups:
            def _lead_med(samples: List[float]) -> float:
                return float(np.median(samples)) if samples else 0.0
            ci_lead_low, ci_lead_high = bootstrap_metric_ci(
                all_leads, metric_fn=_lead_med, block_groups=seed_lead_groups, n_resamples=1000, seed=42
            )
        else:
            ci_lead_low, ci_lead_high = (0.0, 0.0)

        all_method_metrics[method] = {
            "operating_point": {"tau": tau, "k": k, "tau_low": tau_low},
            "brier_score": round(bs, 4),
            "ece": round(ece, 4),
            "pod": round(pod, 4),
            "far_per_100_zone_days": round(far_per_100, 3),
            "median_lead_time_hours": round(median_lead, 1),
            "iqr_lead_time_hours": round(iqr_lead, 1),
            "ci_95_lead_time": [round(ci_lead_low, 1), round(ci_lead_high, 1)],
            "n_episodes": all_hits + all_misses,
            "n_hits": all_hits,
            "n_false_alarms": all_fa,
        }
        print(f"  [{method}] POD={pod:.3f}, FAR={far_per_100:.2f}, Lead={median_lead:.1f}h [{ci_lead_low:.1f}, {ci_lead_high:.1f}]")

    # 3. F-quiet negative control (clean false alarm benchmark on held-out seeds)
    print("Evaluating F-quiet control on held-out seeds...")
    quiet_runs = []
    quiet_fa = 0
    quiet_zone_days = 0.0
    for seed in seeds:
        rcfg = EvalRunConfig(
            city_id="upper_assam",
            family="F-quiet",
            seed=seed,
            duration_hours=duration_hours,
            cadence_hours=cadence_hours,
            rollouts=rollouts,
            method="forecaster",
            calibrator_source="frozen",
        )
        r = run_single_evaluation(rcfg, use_cache=True)
        quiet_runs.append(r)
        hours = r["hours"]
        num_zones = len(r["zone_p_crit_72"])
        quiet_zone_days += (num_zones * float(r["duration_hours"])) / 24.0

        for z_id, p_list in r["zone_p_crit_72"].items():
            runs = detect_alert_runs(
                scores=p_list,
                hours=hours,
                tau=methods_tuned["forecaster"]["tau"],
                k=methods_tuned["forecaster"]["k"],
                tau_low=methods_tuned["forecaster"]["tau_low"],
                k_off=2,
                entity_id=z_id,
            )
            quiet_fa += len(runs)

    quiet_far_per_100 = (quiet_fa / quiet_zone_days) * 100.0 if quiet_zone_days > 0 else 0.0
    quiet_summary = {
        "family": "F-quiet",
        "description": "Zero true critical episodes control",
        "total_false_alarms": quiet_fa,
        "total_zone_days": round(quiet_zone_days, 1),
        "clean_far_per_100_zone_days": round(quiet_far_per_100, 3),
    }
    print(f"  F-quiet: {quiet_fa} false alarms across {quiet_zone_days:.1f} zone-days -> FAR={quiet_far_per_100:.3f}")

    # 4. F-heldout-city (Zero-code generalisation to north_bank_assam)
    print("Evaluating F-heldout-city (north_bank_assam)...")
    hb_hits = 0
    hb_misses = 0
    hb_fa = 0
    hb_leads = []
    hb_zone_days = 0.0

    for seed in seeds:
        rcfg = EvalRunConfig(
            city_id="north_bank_assam",
            family="F-heldout-city",
            seed=seed,
            duration_hours=duration_hours,
            cadence_hours=cadence_hours,
            rollouts=rollouts,
            method="forecaster",
            calibrator_source="frozen",
        )
        r = run_single_evaluation(rcfg, use_cache=True)
        hours = r["hours"]
        episodes_by_zone = r["true_zone_cascade_episodes"]
        num_zones = len(r["zone_p_crit_72"])
        hb_zone_days += (num_zones * float(r["duration_hours"])) / 24.0

        for z_id, p_list in r["zone_p_crit_72"].items():
            eps_data = episodes_by_zone.get(z_id, [])
            true_eps = [
                TrueEpisode(
                    episode_id=ep["episode_id"],
                    entity_type="zone_cascade",
                    entity_id=z_id,
                    level="CRITICAL",
                    start_hour=ep["start_hour"],
                    end_hour=ep["end_hour"],
                    peak_value=ep["peak_value"],
                )
                for ep in eps_data
            ]
            runs = detect_alert_runs(
                scores=p_list,
                hours=hours,
                tau=methods_tuned["forecaster"]["tau"],
                k=methods_tuned["forecaster"]["k"],
                tau_low=methods_tuned["forecaster"]["tau_low"],
                k_off=2,
                entity_id=z_id,
            )
            attr = attribute_alerts(alert_runs=runs, episodes=true_eps, h_hit=72.0)
            hb_hits += len(attr.hits)
            hb_misses += len(attr.missed_episodes)
            hb_fa += len(attr.false_alarms)
            hb_leads.extend(attr.lead_times)

    hb_pod = hb_hits / (hb_hits + hb_misses) if (hb_hits + hb_misses) > 0 else 0.0
    hb_far = (hb_fa / hb_zone_days) * 100.0 if hb_zone_days > 0 else 0.0
    hb_lead = float(np.median(hb_leads)) if hb_leads else 0.0

    generalisation_summary = {
        "heldout_city": "north_bank_assam",
        "topology": "6 zones x 5 systems",
        "pod": round(hb_pod, 4),
        "far_per_100_zone_days": round(hb_far, 3),
        "median_lead_time_hours": round(hb_lead, 1),
        "n_episodes": hb_hits + hb_misses,
        "gap_vs_upper_assam_lead": round(hb_lead - all_method_metrics["forecaster"]["median_lead_time_hours"], 1),
    }
    print(f"  F-heldout-city: POD={hb_pod:.3f}, FAR={hb_far:.2f}, Lead={hb_lead:.1f}h (Gap: {generalisation_summary['gap_vs_upper_assam_lead']}h)")

    final_results = {
        "protocol_hash": proto_hash,
        "commit_hash": commit_hash,
        "heldout_seeds": seeds,
        "rerun_count": reruns,
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "methods_f_storm": all_method_metrics,
        "quiet_control": quiet_summary,
        "generalisation": generalisation_summary,
    }

    with HELDOUT_RESULTS_PATH.open("w", encoding="utf-8") as f:
        json.dump(final_results, f, indent=2)

    print(f"\nSuccessfully written held-out results to: {HELDOUT_RESULTS_PATH}")
    return final_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-rerun", action="store_true", help="Allow audited re-run")
    args = parser.parse_args()
    run_heldout_evaluation(allow_rerun=args.allow_rerun)
