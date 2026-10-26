# The 72-Hour Warning: API Contract & Communication Specification

**Generated Automatically by `scripts/export_schemas.py` — Do Not Hand Edit.**

This document specifies the exact REST and WebSocket contracts for the FastAPI backend, 
supporting both the live backend and the 100% offline mode via `frontend/public/phase4/`.

---

## 1. REST Endpoints

### `GET /health`
- **Description:** Service health check.
- **Response:** `200 OK` `{"status": "ok", "service": "72-hour-warning-phase1"}`

### `GET /cities`
- **Description:** List configured scenario regions.
- **Response:** `200 OK` List of cities (`upper_assam`, `north_bank_assam`).

### `GET /forecast/latest?city=&seed=&rain_window=&anchor=`
- **Description:** Returns the most recent ForecastSnapshot.
- **Response:** `200 OK` `ForecastSnapshot` object.

### `GET /explain/latest?city=&seed=&zone=&rain_window=&anchor=`
- **Description:** Returns the complete causal ExplanationRecord for a zone or the city.
- **Response:** `200 OK` Validates against [`ExplanationRecord.json`](../frontend/public/schemas/ExplanationRecord.json).

### `GET /explain/changes?city=&seed=&limit=&subject=`
- **Description:** Returns recent risk-change log entries.
- **Response:** `200 OK` `{"changes": List[ExplanationRecord]}`

### `GET /explain/link?u=&v=&city=&seed=`
- **Description:** Returns evidence receipt and counterfactual removal effect for directed link `u -> v`.
- **Response:** `200 OK` Validates against [`EvidenceReceipt.json`](../frontend/public/schemas/EvidenceReceipt.json).

### `GET /intervene/actions?city=`
- **Description:** Returns available action catalog and auditable Assumptions Register.
- **Response:** `200 OK` `{"actions": List[Action], "assumptions": List[Assumption], "default_budgets": dict, "objective": dict}`

### `POST /intervene/plan`
- **Description:** Solves for ranked budget-feasible intervention schedules.
- **Request Body:**
  ```json
  {
    "city": "upper_assam",
    "seed": 1,
    "rain_window": "peak",
    "anchor": "off",
    "budgets": {"crews": 12.0, "boats": 8.0, "pumps": 6.0, "cost_lakh": 40.0},
    "method": "greedy",
    "mode": "fast",
    "horizon": 48
  }
  ```
- **Response:** `200 OK` `{"city": str, "elapsed_seconds": float, "plans": List[InterventionPlan]}`

### `POST /intervene/evaluate`
- **Description:** Paired evaluation of an explicit InterventionPlan under Common Random Numbers.
- **Request Body:** `{"city": str, "seed": int, "plan": InterventionPlan, "horizon": int}`
- **Response:** `200 OK` Validates against [`PlanOutcome.json`](../frontend/public/schemas/PlanOutcome.json).

---

## 2. WebSocket Real-Time Stream

**URL:** `WS /ws/stream?city=upper_assam&seed=1&speed=1.0&hours=72&forecast=1&explain=1&plan=1`

### Message Types
1. `type: "observations"`: Released raw sensor observations at current clock tick.
2. `type: "forecast"`: Emitted when `forecast=1` (contains `ForecastSnapshot`).
3. `type: "explanation"`: Emitted when `explain=1` (contains `ExplanationRecord`).
4. `type: "plan"`: Emitted when `plan=1` (contains top recommended `InterventionPlan`).

---

## 3. Exported JSON Schemas

- **`Action`**: [`frontend/public/schemas/Action.json`](frontend/public/schemas/Action.json)
- **`ActionInstance`**: [`frontend/public/schemas/ActionInstance.json`](frontend/public/schemas/ActionInstance.json)
- **`Assumption`**: [`frontend/public/schemas/Assumption.json`](frontend/public/schemas/Assumption.json)
- **`CascadeLoop`**: [`frontend/public/schemas/CascadeLoop.json`](frontend/public/schemas/CascadeLoop.json)
- **`ChainLink`**: [`frontend/public/schemas/ChainLink.json`](frontend/public/schemas/ChainLink.json)
- **`ConcurrentCluster`**: [`frontend/public/schemas/ConcurrentCluster.json`](frontend/public/schemas/ConcurrentCluster.json)
- **`DriverRecord`**: [`frontend/public/schemas/DriverRecord.json`](frontend/public/schemas/DriverRecord.json)
- **`EffectPatch`**: [`frontend/public/schemas/EffectPatch.json`](frontend/public/schemas/EffectPatch.json)
- **`EvidenceReceipt`**: [`frontend/public/schemas/EvidenceReceipt.json`](frontend/public/schemas/EvidenceReceipt.json)
- **`ExplanationRecord`**: [`frontend/public/schemas/ExplanationRecord.json`](frontend/public/schemas/ExplanationRecord.json)
- **`InterventionPlan`**: [`frontend/public/schemas/InterventionPlan.json`](frontend/public/schemas/InterventionPlan.json)
- **`PlanOutcome`**: [`frontend/public/schemas/PlanOutcome.json`](frontend/public/schemas/PlanOutcome.json)
- **`ResourceUse`**: [`frontend/public/schemas/ResourceUse.json`](frontend/public/schemas/ResourceUse.json)
- **`SideEffect`**: [`frontend/public/schemas/SideEffect.json`](frontend/public/schemas/SideEffect.json)
