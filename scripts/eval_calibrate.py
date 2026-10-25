"""CLI script to fit and save FrozenIsotonicCalibrator on CALIB_FIT_SEEDS.

Provenance:
  - Seeds: [21, 22, 23, 24]
  - City: upper_assam
  - Protocol hash and commit hash recorded in eval/calibrator_frozen.json
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.eval.calibrator_fitting import fit_frozen_calibrator


def get_git_commit() -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        return out
    except Exception:
        return "unknown"


def main():
    print("Fitting FrozenIsotonicCalibrator on CALIB_FIT_SEEDS {21, 22, 23, 24}...")
    commit = get_git_commit()
    calibrator = fit_frozen_calibrator(
        seeds=[21, 22, 23, 24],
        city_id="upper_assam",
        duration_hours=168,
        cadence_hours=3,
        rollouts=50,
        commit_hash=commit,
    )
    print(f"Successfully fitted and saved: eval/calibrator_frozen.json")
    print(f"Provenance: {calibrator.provenance}")
    print(f"Widening factor TTC: {calibrator.widening_factor_ttc}")


if __name__ == "__main__":
    main()
