"""Test E16: Held-Out Evaluation Lock and Audit Enforcement.

Rule V3:
  - Evaluation on held-out seeds must run once and only once.
  - Re-running held-out evaluation is strictly prohibited unless --allow-rerun is passed.
  - Lock file records protocol hash, commit hash, config hashes, and rerun counter.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from backend.app.eval.protocol import (
    HELDOUT_SEEDS,
    check_heldout_lock,
    write_heldout_lock,
)


def test_e16_heldout_lock_lifecycle(tmp_path: Path, monkeypatch):
    """E16: Verify held-out lock prevents unauthorized re-runs and records audits."""
    test_lock_file = tmp_path / "heldout_lock.json"
    monkeypatch.setattr("backend.app.eval.protocol.HELD_OUT_LOCK_PATH", test_lock_file)

    # 1. Initially no lock exists
    can_proceed, reruns, data = check_heldout_lock(allow_rerun=False)
    assert can_proceed is True
    assert reruns == 0
    assert data is None

    # 2. Write initial lock
    proto_hash = "mock_protocol_hash_123"
    commit_hash = "mock_commit_abc"
    cfg_hashes = {"upper_assam": "cfg_hash_1", "north_bank_assam": "cfg_hash_2"}

    lock_info = write_heldout_lock(
        protocol_hash=proto_hash,
        code_commit_hash=commit_hash,
        config_hashes=cfg_hashes,
        allow_rerun=False,
    )
    assert test_lock_file.exists()
    assert lock_info["rerun_count"] == 0
    assert lock_info["protocol_hash"] == proto_hash
    assert lock_info["heldout_seeds"] == HELDOUT_SEEDS

    # 3. Subsequent check without allow_rerun is refused
    can_proceed, reruns, data = check_heldout_lock(allow_rerun=False)
    assert can_proceed is False
    assert reruns == 0
    assert data is not None

    # 4. Attempting to overwrite lock without allow_rerun raises RuntimeError
    with pytest.raises(RuntimeError) as exc_info:
        write_heldout_lock(
            protocol_hash=proto_hash,
            code_commit_hash=commit_hash,
            config_hashes=cfg_hashes,
            allow_rerun=False,
        )
    assert "Held-out evaluation is locked" in str(exc_info.value)
    assert "--allow-rerun" in str(exc_info.value)

    # 5. Overwrite with allow_rerun=True succeeds and increments rerun_count
    lock_info_rerun = write_heldout_lock(
        protocol_hash=proto_hash,
        code_commit_hash=commit_hash,
        config_hashes=cfg_hashes,
        allow_rerun=True,
    )
    assert lock_info_rerun["rerun_count"] == 1

    can_proceed, reruns, data = check_heldout_lock(allow_rerun=True)
    assert can_proceed is True
    assert reruns == 2
