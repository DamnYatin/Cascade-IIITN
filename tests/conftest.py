"""Pytest fixtures and helpers for Phase 1 acceptance tests."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

from backend.app.city_config import load_city_config  # noqa: E402
from backend.app.synth.generator import generate_city  # noqa: E402
from backend.app.replay.stream import ReplayStream  # noqa: E402
from backend.app.replay.clock import ReplayClock  # noqa: E402
from backend.app.adapters.imd_rain import IMDRainAdapter  # noqa: E402
from backend.app.adapters.imd_rain import DailyRow  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def ensure_rain_csv():
    """Ensure the fixture rainfall CSV exists (generated on demand, not committed).

    ``data/`` is gitignored, so a fresh clone regenerates the fixture here.
    """
    csv_path = REPO / "data" / "processed" / "maharashtra_climate.csv"
    if not csv_path.exists():
        from scripts.generate_rain_fixture import main as _gen  # noqa: E402

        _gen()
    return csv_path


@pytest.fixture(scope="session")
def mumbai_config():
    return load_city_config(REPO / "configs" / "mumbai.yaml")


@pytest.fixture(scope="session")
def heldout_config():
    return load_city_config(REPO / "configs" / "heldout_city.yaml")


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
            {"node_id": e.node_id, "start_hour": e.start_hour,
             "end_hour": e.end_hour, "peak_stress": e.peak_stress}
            for e in gt.critical_episodes
        ],
        "city_critical_episodes": list(gt.city_critical_episodes),
    }
    return json.dumps(payload, sort_keys=True, default=str)
