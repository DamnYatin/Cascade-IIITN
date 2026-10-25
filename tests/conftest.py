"""Pytest fixtures and helpers for Assam Phase 1 acceptance tests."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parent.parent

from backend.app.city_config import load_city_config  # noqa: E402


@pytest.fixture(scope="session")
def upper_assam_config():
    """Hero city configuration (10 zones x 6 systems)."""
    cfg_path = REPO / "configs" / "upper_assam.yaml"
    if not cfg_path.exists():
        from scripts.build_assam_config import main as _build
        _build()
    return load_city_config(cfg_path)


@pytest.fixture(scope="session")
def north_bank_config():
    """Heldout city configuration (6 zones x 5 systems)."""
    cfg_path = REPO / "configs" / "north_bank_assam.yaml"
    if not cfg_path.exists():
        from scripts.build_assam_config import main as _build
        _build()
    return load_city_config(cfg_path)


def serialize_observations(obs):
    return json.dumps([o.model_dump() for o in obs], sort_keys=True, default=str)


def serialize_ground_truth(gt):
    payload = {
        "city_id": gt.city_id,
        "seed": gt.seed,
        "start_time_utc": gt.start_time_utc.isoformat(),
        "duration_hours": gt.duration_hours,
        "generator_family": gt.generator_family,
        "stress": gt.stress,
        "rain_input": gt.rain_input,
        "planted_edges": [e.model_dump() for e in gt.planted_edges],
        "decoy_pairs": list(gt.decoy_pairs),
        "critical_episodes": [
            {
                "node_id": e.node_id,
                "start_hour": e.start_hour,
                "end_hour": e.end_hour,
                "peak_stress": e.peak_stress,
            }
            for e in gt.critical_episodes
        ],
        "city_critical_episodes": list(gt.city_critical_episodes),
    }
    return json.dumps(payload, sort_keys=True, default=str)
