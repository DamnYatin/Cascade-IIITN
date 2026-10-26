"""Export JSON Schemas and Generate API Contract Documentation (Phase 4).

Generates:
  1. JSON Schemas for public data models in frontend/public/schemas/:
     - ExplanationRecord, ChainLink, DriverRecord, EvidenceReceipt, CascadeLoop, ConcurrentCluster
     - Action, ActionInstance, InterventionPlan, PlanOutcome, SideEffect, ResourceUse, Assumption
  2. docs/API_CONTRACT.md: Complete machine-readable and human-readable API specification.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.explain.records import (
    CascadeLoop,
    ChainLink,
    ConcurrentCluster,
    DriverRecord,
    EvidenceReceipt,
    ExplanationRecord,
)
from backend.app.intervene.records import (
    Action,
    ActionInstance,
    Assumption,
    EffectPatch,
    InterventionPlan,
    PlanOutcome,
    ResourceUse,
    SideEffect,
)

SCHEMAS_DIR = REPO_ROOT / "frontend" / "public" / "schemas"
DOCS_CONTRACT_PATH = REPO_ROOT / "docs" / "API_CONTRACT.md"

MODELS = [
    ExplanationRecord,
    ChainLink,
    DriverRecord,
    EvidenceReceipt,
    CascadeLoop,
    ConcurrentCluster,
    Action,
    ActionInstance,
    EffectPatch,
    InterventionPlan,
    PlanOutcome,
    SideEffect,
    ResourceUse,
    Assumption,
]


def export_schemas() -> dict[str, Path]:
    """Export Pydantic model JSON schemas to frontend/public/schemas/."""
    SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
    exported = {}

    for model in MODELS:
        name = model.__name__
        file_path = SCHEMAS_DIR / f"{name}.json"
        schema_dict = model.model_json_schema()
        file_path.write_text(json.dumps(schema_dict, indent=2, sort_keys=True), encoding="utf-8")
        exported[name] = file_path

    return exported


def generate_api_contract_md(exported_schemas: dict[str, Path]) -> str:
    """Generate comprehensive docs/API_CONTRACT.md documentation."""
    lines = [
        "# The 72-Hour Warning: API Contract & Communication Specification",
        "",
        "**Generated Automatically by `scripts/export_schemas.py` — Do Not Hand Edit.**",
        "",
        "This document specifies the exact REST and WebSocket contracts for the FastAPI backend, ",
        "supporting both the live backend and the 100% offline mode via `frontend/public/phase4/`.",
        "",
        "---",
        "",
        "## 1. REST Endpoints",
        "",
        "### `GET /health`",
        "- **Description:** Service health check.",
        "- **Response:** `200 OK` `{\"status\": \"ok\", \"service\": \"72-hour-warning-phase1\"}`",
        "",
        "### `GET /cities`",
        "- **Description:** List configured scenario regions.",
        "- **Response:** `200 OK` List of cities (`upper_assam`, `north_bank_assam`).",
        "",
        "### `GET /forecast/latest?city=&seed=&rain_window=&anchor=`",
        "- **Description:** Returns the most recent ForecastSnapshot.",
        "- **Response:** `200 OK` `ForecastSnapshot` object.",
        "",
        "### `GET /explain/latest?city=&seed=&zone=&rain_window=&anchor=`",
        "- **Description:** Returns the complete causal ExplanationRecord for a zone or the city.",
        "- **Response:** `200 OK` Validates against [`ExplanationRecord.json`](../frontend/public/schemas/ExplanationRecord.json).",
        "",
        "### `GET /explain/changes?city=&seed=&limit=&subject=`",
        "- **Description:** Returns recent risk-change log entries.",
        "- **Response:** `200 OK` `{\"changes\": List[ExplanationRecord]}`",
        "",
        "### `GET /explain/link?u=&v=&city=&seed=`",
        "- **Description:** Returns evidence receipt and counterfactual removal effect for directed link `u -> v`.",
        "- **Response:** `200 OK` Validates against [`EvidenceReceipt.json`](../frontend/public/schemas/EvidenceReceipt.json).",
        "",
        "### `GET /intervene/actions?city=`",
        "- **Description:** Returns available action catalog and auditable Assumptions Register.",
        "- **Response:** `200 OK` `{\"actions\": List[Action], \"assumptions\": List[Assumption], \"default_budgets\": dict, \"objective\": dict}`",
        "",
        "### `POST /intervene/plan`",
        "- **Description:** Solves for ranked budget-feasible intervention schedules.",
        "- **Request Body:**",
        "  ```json",
        "  {",
        "    \"city\": \"upper_assam\",",
        "    \"seed\": 1,",
        "    \"rain_window\": \"peak\",",
        "    \"anchor\": \"off\",",
        "    \"budgets\": {\"crews\": 12.0, \"boats\": 8.0, \"pumps\": 6.0, \"cost_lakh\": 40.0},",
        "    \"method\": \"greedy\",",
        "    \"mode\": \"fast\",",
        "    \"horizon\": 48",
        "  }",
        "  ```",
        "- **Response:** `200 OK` `{\"city\": str, \"elapsed_seconds\": float, \"plans\": List[InterventionPlan]}`",
        "",
        "### `POST /intervene/evaluate`",
        "- **Description:** Paired evaluation of an explicit InterventionPlan under Common Random Numbers.",
        "- **Request Body:** `{\"city\": str, \"seed\": int, \"plan\": InterventionPlan, \"horizon\": int}`",
        "- **Response:** `200 OK` Validates against [`PlanOutcome.json`](../frontend/public/schemas/PlanOutcome.json).",
        "",
        "---",
        "",
        "## 2. WebSocket Real-Time Stream",
        "",
        "**URL:** `WS /ws/stream?city=upper_assam&seed=1&speed=1.0&hours=72&forecast=1&explain=1&plan=1`",
        "",
        "### Message Types",
        "1. `type: \"observations\"`: Released raw sensor observations at current clock tick.",
        "2. `type: \"forecast\"`: Emitted when `forecast=1` (contains `ForecastSnapshot`).",
        "3. `type: \"explanation\"`: Emitted when `explain=1` (contains `ExplanationRecord`).",
        "4. `type: \"plan\"`: Emitted when `plan=1` (contains top recommended `InterventionPlan`).",
        "",
        "---",
        "",
        "## 3. Exported JSON Schemas",
        "",
    ]

    for model_name, path in sorted(exported_schemas.items()):
        rel_path = path.relative_to(REPO_ROOT).as_posix()
        lines.append(f"- **`{model_name}`**: [`{rel_path}`]({rel_path})")

    content = "\n".join(lines) + "\n"
    DOCS_CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOCS_CONTRACT_PATH.write_text(content, encoding="utf-8")
    return content


def main():
    schemas = export_schemas()
    generate_api_contract_md(schemas)
    print(f"Exported {len(schemas)} JSON schemas to {SCHEMAS_DIR}")
    print(f"Generated API contract at {DOCS_CONTRACT_PATH}")


if __name__ == "__main__":
    main()
