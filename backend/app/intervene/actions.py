"""Action loader, validator, and Assumptions Register builder for Interventions.

Enforces:
  - Strict validation of action schemas, costs, delays, and patch definitions.
  - Graceful skipping of actions referencing systems absent in a city topology (logged warning).
  - Explicit Assumptions Register extraction with auditable provenance classification.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import yaml
from pydantic import BaseModel, Field, ValidationError

from backend.app.intervene.records import (
    Action,
    ActionInstance,
    Assumption,
    EffectPatch,
    PatchType,
    ProvenanceType,
)

logger = logging.getLogger(__name__)


class InterventionsConfig(BaseModel):
    """Configuration container for intervention catalog and solver objectives."""
    version: str = Field(default="1.0.0")
    default_budgets: Dict[str, float] = Field(default_factory=dict)
    objective: Dict[str, float] = Field(default_factory=dict)
    actions: List[Action] = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> InterventionsConfig:
        if not path.exists():
            raise FileNotFoundError(f"Interventions config not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Invalid YAML root in {path}: expected dict")

        try:
            return cls(**data)
        except ValidationError as e:
            raise ValueError(f"Validation error in {path}:\n{e}") from e


def load_interventions_config(path: Optional[Path] = None) -> InterventionsConfig:
    """Convenience helper to load and validate interventions YAML config."""
    if path is None:
        path = Path("configs/interventions.yaml")
    return InterventionsConfig.load(path)


def filter_actions_for_city(
    actions: List[Action],
    available_systems: Any,
    available_zones: Optional[List[str]] = None,
) -> List[Action]:
    """Filter action catalog against systems present in a city configuration.

    Actions requiring systems absent in the city topology are skipped with a logged warning,
    guaranteeing zero code changes across diverse city topologies.
    """
    if hasattr(available_systems, "systems"):
        if available_zones is None and hasattr(available_systems, "zones"):
            available_zones = [z.id for z in available_systems.zones]
        available_systems = [s.id for s in available_systems.systems]
    system_set = set(available_systems)
    filtered = []

    for action in actions:
        missing_systems = [sys for sys in action.systems if sys not in system_set]
        if missing_systems:
            logger.warning(
                "Skipping action '%s' (%s): required system(s) %s not present in city topology.",
                action.id,
                action.name,
                missing_systems,
            )
            continue
        filtered.append(action)

    return filtered


def build_assumptions_register(config: Any) -> List[Assumption]:
    """Extract every assumed number across all actions into an auditable Assumptions Register."""
    assumptions: List[Assumption] = []
    actions_list = config.actions if hasattr(config, "actions") else config

    for action in actions_list:
        # 1. Action activation delay
        assumptions.append(
            Assumption(
                parameter_id=f"{action.id}.activation_delay",
                action_id=action.id,
                description=f"Activation lead time required for {action.name}",
                assumed_value=float(action.activation_delay),
                uncertainty_range=(
                    max(0.0, float(action.activation_delay) * 0.5),
                    float(action.activation_delay) * 1.5,
                ),
                provenance=action.provenance,
                grounded_in=action.grounded_in,
                sensitivity_notes="Higher delay directly reduces time window where cascade can be averted.",
            )
        )

        # 2. Resource costs
        for r_name, r_cost in sorted(action.resource_costs.items()):
            assumptions.append(
                Assumption(
                    parameter_id=f"{action.id}.cost.{r_name}",
                    action_id=action.id,
                    description=f"{r_name.capitalize()} cost per unit for {action.name}",
                    assumed_value=float(r_cost),
                    uncertainty_range=(float(r_cost) * 0.8, float(r_cost) * 1.25),
                    provenance=ProvenanceType.EXPERT_ESTIMATE_NEEDED,
                    grounded_in=action.grounded_in,
                    sensitivity_notes="Determines feasible deployment count under fixed budget limits.",
                )
            )

        # 3. Benefit patches
        for idx, patch in enumerate(action.benefit_patches):
            spread = patch.uncertainty_spread
            val = patch.param_value
            assumptions.append(
                Assumption(
                    parameter_id=f"{action.id}.benefit_{idx}_{patch.patch_type.value}",
                    action_id=action.id,
                    description=f"Benefit magnitude ({patch.patch_type.value}) on {patch.target}",
                    assumed_value=float(val),
                    uncertainty_range=(
                        max(0.0, float(val) * (1.0 - spread)),
                        float(val) * (1.0 + spread),
                    ),
                    provenance=action.provenance,
                    grounded_in=action.grounded_in,
                    sensitivity_notes=f"Model assumption with ±{spread*100:.0f}% parametric uncertainty.",
                )
            )

        # 4. Side-effect patches
        for idx, patch in enumerate(action.side_effect_patches):
            spread = patch.uncertainty_spread
            val = patch.param_value
            assumptions.append(
                Assumption(
                    parameter_id=f"{action.id}.side_effect_{idx}_{patch.patch_type.value}",
                    action_id=action.id,
                    description=f"Negative side-effect magnitude on {patch.target}",
                    assumed_value=float(val),
                    uncertainty_range=(
                        max(0.0, float(val) * (1.0 - spread)),
                        float(val) * (1.0 + spread),
                    ),
                    provenance=action.provenance,
                    grounded_in=action.grounded_in,
                    sensitivity_notes="Adverse impact that penalises net benefit objective.",
                )
            )

    return assumptions


def instantiate_action(
    action: Action,
    zone: str,
    target_node: Optional[str] = None,
    start_time_offset: float = 0.0,
    units: int = 1,
) -> ActionInstance:
    """Create a concrete ActionInstance for a specific zone/node target and start time."""
    if units > action.max_units:
        raise ValueError(f"Requested {units} units exceeds action.max_units ({action.max_units}) for {action.id}")
    if action.availability_by_zone is not None and zone not in action.availability_by_zone:
        raise ValueError(f"Zone '{zone}' is not eligible for action '{action.id}'")

    costs = {k: v * units for k, v in action.resource_costs.items()}
    inst_id = f"{action.id}:{zone}:t+{start_time_offset:.0f}h:u{units}"

    return ActionInstance(
        instance_id=inst_id,
        action_id=action.id,
        zone=zone,
        target_node=target_node or f"{zone}:{action.systems[0]}",
        start_time_offset=start_time_offset,
        units=units,
        resource_costs=costs,
    )


def resolve_patches_for_instance(
    action: Action,
    instance: ActionInstance,
) -> Tuple[List[EffectPatch], List[EffectPatch]]:
    """Resolve '{zone}' placeholder tokens into concrete zone identifiers."""
    zone = instance.zone or ""

    def _resolve(patches: List[EffectPatch]) -> List[EffectPatch]:
        resolved = []
        for p in patches:
            p_dict = p.model_dump()
            p_dict["target"] = p.target.replace("{zone}", zone)
            if p.u:
                p_dict["u"] = p.u.replace("{zone}", zone)
            if p.v:
                p_dict["v"] = p.v.replace("{zone}", zone)
            resolved.append(EffectPatch(**p_dict))
        return resolved

    return _resolve(action.benefit_patches), _resolve(action.side_effect_patches)
