"""Pre-registered evaluation protocol, seed sets, scenario families, and held-out lock.

Rule V3 compliance:
  - Before running held-out seeds, the protocol specification and hashes are frozen.
  - Held-out evaluation writes eval/heldout_lock.json.
  - Re-running held-out evaluation requires --allow-rerun, which records and logs rerun counts.
  - Dev, calibration-fit, and held-out seeds are mathematically disjoint.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

# Pre-registered seed sets
DEV_SEEDS: List[int] = [11, 12, 13]
CALIB_FIT_SEEDS: List[int] = [21, 22, 23, 24]
HELDOUT_SEEDS: List[int] = [101, 102, 103, 104, 105]

# Enforce disjointness rule statically
assert len(set(DEV_SEEDS) & set(CALIB_FIT_SEEDS)) == 0, "Dev and calib-fit seeds must be disjoint"
assert len(set(DEV_SEEDS) & set(HELDOUT_SEEDS)) == 0, "Dev and held-out seeds must be disjoint"
assert len(set(CALIB_FIT_SEEDS) & set(HELDOUT_SEEDS)) == 0, "Calib-fit and held-out seeds must be disjoint"

HELD_OUT_LOCK_PATH = Path("eval/heldout_lock.json")


@dataclass
class FamilySpec:
    family_id: str
    description: str
    city_id: str
    duration_hours: int
    cadence_hours: int
    rollouts: int
    faults: List[str] = field(default_factory=list)
    anchor_mode: str = "off"
    is_real_event: bool = False
    is_illustrative: bool = False


PROTOCOL_FAMILIES: Dict[str, FamilySpec] = {
    "F-storm": FamilySpec(
        family_id="F-storm",
        description="Synthetic multi-storm rain driving upper_assam. Primary statistical yardstick.",
        city_id="upper_assam",
        duration_hours=168,
        cadence_hours=3,
        rollouts=100,
    ),
    "F-quiet": FamilySpec(
        family_id="F-quiet",
        description="Low-rain control driving upper_assam. No true critical episodes. Pure false-alarm rate.",
        city_id="upper_assam",
        duration_hours=168,
        cadence_hours=3,
        rollouts=100,
    ),
    "F-drift": FamilySpec(
        family_id="F-drift",
        description="F-storm with planted dynamics change at hour 72 to measure drift latency and learning.",
        city_id="upper_assam",
        duration_hours=168,
        cadence_hours=3,
        rollouts=100,
    ),
    "F-faulted": FamilySpec(
        family_id="F-faulted",
        description="F-storm replays under sensor faults (dropout, stuck-at, spike, delay, duplicate, spam, blackout).",
        city_id="upper_assam",
        duration_hours=168,
        cadence_hours=3,
        rollouts=100,
        faults=["dropout", "stuck_at", "spike", "feed_delay", "contradictory_duplicate", "citizen_spam", "zone_blackout"],
    ),
    "F-heldout-city": FamilySpec(
        family_id="F-heldout-city",
        description="The north_bank_assam topology (6 zones x 5 systems) under identical frozen configuration.",
        city_id="north_bank_assam",
        duration_hours=168,
        cadence_hours=3,
        rollouts=100,
    ),
    "F-real": FamilySpec(
        family_id="F-real",
        description="Real Assam 2026 rain/soil series (hero window), downstream simulated, anchor_mode=off. Illustrative only.",
        city_id="upper_assam",
        duration_hours=168,
        cadence_hours=3,
        rollouts=100,
        anchor_mode="off",
        is_real_event=True,
        is_illustrative=True,
    ),
}


def compute_protocol_hash() -> str:
    """Compute deterministic SHA-256 hash of pre-registered protocol."""
    proto_data = {
        "dev_seeds": sorted(DEV_SEEDS),
        "calib_fit_seeds": sorted(CALIB_FIT_SEEDS),
        "heldout_seeds": sorted(HELDOUT_SEEDS),
        "families": {
            k: {
                "id": v.family_id,
                "city": v.city_id,
                "duration": v.duration_hours,
                "cadence": v.cadence_hours,
                "rollouts": v.rollouts,
                "anchor_mode": v.anchor_mode,
            }
            for k, v in sorted(PROTOCOL_FAMILIES.items())
        },
        "target_far": 1.0,
        "h_hit": 72.0,
        "merge_gap_hours": 6.0,
    }
    canon = json.dumps(proto_data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def check_heldout_lock(allow_rerun: bool = False) -> Tuple[bool, int, Optional[Dict[str, Any]]]:
    """Check if held-out evaluation is locked.

    Returns:
        (can_proceed, rerun_count, lock_data)
    """
    if not HELD_OUT_LOCK_PATH.exists():
        return (True, 0, None)

    content = HELD_OUT_LOCK_PATH.read_text(encoding="utf-8")
    data = json.loads(content)
    reruns = int(data.get("rerun_count", 0))

    if not allow_rerun:
        return (False, reruns, data)

    return (True, reruns + 1, data)


def write_heldout_lock(
    protocol_hash: str,
    code_commit_hash: str,
    config_hashes: Dict[str, str],
    allow_rerun: bool = False,
) -> Dict[str, Any]:
    """Write or update held-out lock file with protocol, code, and config hashes."""
    rerun_count = 0
    if HELD_OUT_LOCK_PATH.exists():
        old_data = json.loads(HELD_OUT_LOCK_PATH.read_text(encoding="utf-8"))
        if not allow_rerun:
            raise RuntimeError(
                "Held-out evaluation is locked. Use --allow-rerun to execute a recorded rerun."
            )
        rerun_count = int(old_data.get("rerun_count", 0)) + 1

    lock_data = {
        "locked": True,
        "protocol_hash": protocol_hash,
        "code_commit_hash": code_commit_hash,
        "config_hashes": config_hashes,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "rerun_count": rerun_count,
        "heldout_seeds": HELDOUT_SEEDS,
    }

    HELD_OUT_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    HELD_OUT_LOCK_PATH.write_text(json.dumps(lock_data, indent=2, sort_keys=True), encoding="utf-8")
    return lock_data
