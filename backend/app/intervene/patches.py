"""Parameter Patches Engine: Scheduled Patch Compilation and Dynamic Execution.

Implements:
  - Patch types: scale_term, add_bias, scale_edge, add_edge, cap_stress, exposure_change.
  - Activation delay and duration windowing: active for h in [start_hour, end_hour).
  - Parametric effect uncertainty drawn deterministically per rollout using Common Random Numbers (CRN).
  - Explicit propagation through learned cascade dynamics.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from backend.app.intervene.actions import Action, ActionInstance, resolve_patches_for_instance
from backend.app.intervene.records import EffectPatch, PatchType


@dataclass
class ScheduledPatch:
    """A concrete parameter patch bound to a time window and per-rollout effect values."""
    patch_type: PatchType
    target: str
    start_hour: float
    end_hour: float
    u: Optional[str] = None
    v: Optional[str] = None
    term: Optional[str] = None
    lag: Optional[float] = None
    nominal_value: float = 0.0
    # Pre-drawn values per rollout: shape (n_rollouts,)
    rollout_values: Optional[np.ndarray] = None
    is_side_effect: bool = False
    action_id: str = ""


def draw_patch_rollout_values(
    nominal_value: float,
    distribution: str,
    spread: float,
    n_rollouts: int,
    patch_seed: int,
) -> np.ndarray:
    """Draw deterministic per-rollout effect multipliers or offsets under CRN."""
    if spread <= 1e-4 or distribution == "constant":
        return np.full(n_rollouts, nominal_value, dtype=np.float64)

    rng = np.random.default_rng(patch_seed)
    if distribution == "triangular":
        low = max(0.0, nominal_value * (1.0 - spread))
        high = nominal_value * (1.0 + spread)
        mode = nominal_value
        return rng.triangular(low, mode, high, size=n_rollouts).astype(np.float64)
    elif distribution == "beta":
        # Centered around nominal
        alpha = 2.0
        beta = 2.0
        draws = rng.beta(alpha, beta, size=n_rollouts)
        # Scale to [nominal*(1-spread), nominal*(1+spread)]
        low = max(0.0, nominal_value * (1.0 - spread))
        high = nominal_value * (1.0 + spread)
        return (low + draws * (high - low)).astype(np.float64)

    return np.full(n_rollouts, nominal_value, dtype=np.float64)


def compile_scheduled_patches(
    actions_by_id: Dict[str, Action],
    action_instances: List[ActionInstance],
    n_rollouts: int = 300,
    global_seed: int = 42,
    issue_time: Optional[datetime] = None,
) -> List[ScheduledPatch]:
    """Compile ActionInstances into a unified list of ScheduledPatch objects."""
    scheduled: List[ScheduledPatch] = []
    base_seed = global_seed + (int(issue_time.timestamp()) & 0x7FFFFFFF if issue_time else 0)

    for inst_idx, inst in enumerate(action_instances):
        if inst.action_id not in actions_by_id:
            continue
        action = actions_by_id[inst.action_id]
        start_h = float(inst.start_time_offset + action.activation_delay)
        end_h = float(start_h + action.duration)

        b_patches, s_patches = resolve_patches_for_instance(action, inst)

        # Process benefit patches
        for p_idx, p in enumerate(b_patches):
            p_seed = int((base_seed + inst_idx * 100 + p_idx) & 0x7FFFFFFF)
            # Scale nominal value by units deployed if scalable
            nom_val = p.param_value
            if p.patch_type == PatchType.ADD_BIAS:
                nom_val = p.param_value * inst.units
            vals = draw_patch_rollout_values(
                nominal_value=nom_val,
                distribution=p.distribution,
                spread=p.uncertainty_spread,
                n_rollouts=n_rollouts,
                patch_seed=p_seed,
            )
            scheduled.append(
                ScheduledPatch(
                    patch_type=p.patch_type,
                    target=p.target,
                    start_hour=start_h,
                    end_hour=end_h,
                    u=p.u,
                    v=p.v,
                    term=p.term,
                    lag=p.lag,
                    nominal_value=nom_val,
                    rollout_values=vals,
                    is_side_effect=False,
                    action_id=action.id,
                )
            )

        # Process side-effect patches
        for p_idx, p in enumerate(s_patches):
            p_seed = int((base_seed + inst_idx * 100 + 50 + p_idx) & 0x7FFFFFFF)
            nom_val = p.param_value
            if p.patch_type == PatchType.ADD_BIAS:
                nom_val = p.param_value * inst.units
            vals = draw_patch_rollout_values(
                nominal_value=nom_val,
                distribution=p.distribution,
                spread=p.uncertainty_spread,
                n_rollouts=n_rollouts,
                patch_seed=p_seed,
            )
            scheduled.append(
                ScheduledPatch(
                    patch_type=p.patch_type,
                    target=p.target,
                    start_hour=start_h,
                    end_hour=end_h,
                    u=p.u,
                    v=p.v,
                    term=p.term,
                    lag=p.lag,
                    nominal_value=nom_val,
                    rollout_values=vals,
                    is_side_effect=True,
                    action_id=action.id,
                )
            )

    return scheduled


def apply_step_patches(
    s_next: np.ndarray,  # shape (n_rollouts, n_nodes)
    ring_buffer: np.ndarray,  # shape (max_lag + 1, n_rollouts, n_nodes)
    h: int,
    buffer_idx: int,
    max_lag: int,
    patches: List[ScheduledPatch],
    node_to_idx: Dict[str, int],
    n_rollouts: int,
) -> np.ndarray:
    """Apply active patches during one forecast rollout step h."""
    step_hour = float(h + 1)

    for patch in patches:
        if not (patch.start_hour <= step_hour <= patch.end_hour):
            continue

        vals = patch.rollout_values if patch.rollout_values is not None else np.full(n_rollouts, patch.nominal_value)

        # 1. Bias perturbation (e.g. standing load from trucks or shelter clinics)
        if patch.patch_type == PatchType.ADD_BIAS:
            if patch.target in node_to_idx:
                t_idx = node_to_idx[patch.target]
                s_next[:, t_idx] += vals

        # 2. Stress capping (e.g. medical surge capacity, generator backup)
        elif patch.patch_type == PatchType.CAP_STRESS:
            if patch.target in node_to_idx:
                t_idx = node_to_idx[patch.target]
                s_next[:, t_idx] = np.minimum(s_next[:, t_idx], vals)

        # 3. Add dynamic edge (e.g. evacuation -> transport congestion)
        elif patch.patch_type == PatchType.ADD_EDGE:
            if patch.u in node_to_idx and patch.v in node_to_idx:
                u_idx = node_to_idx[patch.u]
                v_idx = node_to_idx[patch.v]
                lag_steps = int(round(patch.lag or 1.0))
                lookup_idx = (buffer_idx + 1 - lag_steps) % (max_lag + 1)
                u_val = ring_buffer[lookup_idx, :, u_idx]
                s_next[:, v_idx] += vals * u_val

        # 4. Exposure change across zone
        elif patch.patch_type == PatchType.EXPOSURE_CHANGE:
            zone_prefix = f"{patch.target}:"
            for n_name, idx in node_to_idx.items():
                if n_name.startswith(zone_prefix) and ("health" in n_name or "emergency_response" in n_name):
                    # Scales stress update proportionally towards baseline
                    s_next[:, idx] = 0.10 + (s_next[:, idx] - 0.10) * vals

    return s_next
