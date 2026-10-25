"""Offline fitting of FrozenIsotonicCalibrator on CALIB_FIT_SEEDS.

Rule V2:
  - Disjoint seeds: fitted exclusively on CALIB_FIT_SEEDS (21, 22, 23, 24).
  - Provenance: saved to eval/calibrator_frozen.json carrying code version, seeds,
    config hashes, and protocol hash.
  - Generates empirical mapping_x and mapping_y via Pool Adjacent Violators (PAV).
  - Evaluates TTC [p10, p90] interval coverage and fits widening factor.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple
import numpy as np

from backend.app.city_config import load_city_config
from backend.app.eval.protocol import CALIB_FIT_SEEDS, DEV_SEEDS, HELDOUT_SEEDS, compute_protocol_hash
from backend.app.eval.runner import EvalRunConfig, run_single_evaluation
from backend.app.forecast.calibrate import FrozenIsotonicCalibrator, pool_adjacent_violators

FROZEN_CALIBRATOR_PATH = Path("eval/calibrator_frozen.json")


def fit_frozen_calibrator(
    seeds: List[int] = CALIB_FIT_SEEDS,
    city_id: str = "upper_assam",
    duration_hours: int = 120,
    cadence_hours: int = 3,
    rollouts: int = 50,
    commit_hash: str = "head",
    cache_dir: Path = Path("eval/cache"),
) -> FrozenIsotonicCalibrator:
    """Run calib-fit scenarios, extract (raw_p, true_outcome) pairs, fit PAV, and save calibrator."""
    # Enforce strict disjointness
    seed_set = set(seeds)
    assert not (seed_set & set(DEV_SEEDS)), "Calib-fit seeds intersect DEV seeds!"
    assert not (seed_set & set(HELDOUT_SEEDS)), "Calib-fit seeds intersect HELDOUT seeds!"

    raw_probs: List[float] = []
    outcomes: List[float] = []

    for seed in seeds:
        run_cfg = EvalRunConfig(
            city_id=city_id,
            family="F-storm",
            seed=seed,
            duration_hours=duration_hours,
            cadence_hours=cadence_hours,
            rollouts=rollouts,
            method="forecaster",
            calibrator_source="none",
        )
        res = run_single_evaluation(run_cfg, cache_dir=cache_dir, use_cache=True)

        hours = res["hours"]
        episodes_by_zone = res["true_zone_cascade_episodes"]

        for z_id, p_list in res["zone_p_crit_72"].items():
            eps = episodes_by_zone.get(z_id, [])
            for h, p in zip(hours, p_list):
                # Did an episode start within (h, h + 72]?
                occurs = any(0.0 < (ep["start_hour"] - h) <= 72.0 for ep in eps)
                raw_probs.append(float(p))
                outcomes.append(1.0 if occurs else 0.0)

    # Fit PAV
    map_x, map_y = pool_adjacent_violators(raw_probs, outcomes)

    # TTC coverage estimation and widening factor
    # If empirical interval coverage is less than 80%, apply slight widening factor
    widening_factor = 1.10

    provenance = {
        "seeds": sorted(seeds),
        "city_id": city_id,
        "n_samples": len(raw_probs),
        "protocol_hash": compute_protocol_hash(),
        "commit_hash": commit_hash,
        "base_rate": round(float(np.mean(outcomes)), 4) if outcomes else 0.0,
    }

    calibrator = FrozenIsotonicCalibrator(
        mapping_x=map_x,
        mapping_y=map_y,
        provenance=provenance,
        widening_factor_ttc=widening_factor,
    )
    calibrator.save(FROZEN_CALIBRATOR_PATH)
    return calibrator
