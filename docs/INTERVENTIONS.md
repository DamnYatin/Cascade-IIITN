# Constrained Counterfactual Interventions & Assumptions Register

## 1. Overview & Honest Principle

> [!WARNING]
> **CRITICAL HONESTY NOTICE:**  
> There is **no empirical real-world ground truth data** on the exact quantitative counterfactual efficacy of municipal interventions during the Assam July 2026 flood event.  
> Every effect magnitude, resource cost, activation delay, and side-effect parameter in `configs/interventions.yaml` is an **assumed model parameter** or an **expert estimate needed**.  
> Grounding tags reference Section 12 of `docs/sources/Assam_Floods_2026_Report.md` exclusively for the **operational existence of that class of action** (e.g. army boat deployment, high-capacity pumps), **never for its quantitative causal magnitude**.

All action outcomes evaluated by the system represent:
$$\text{Estimated effect under the learned model with assumed action effects}$$

---

## 2. Action Catalog & Provenance

| Action ID | Action Title | Target System(s) | Provenance Level | Historical Report Grounding | Primary Benefit | Explicit Side-Effect |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `deploy_dewatering_pumps` | Deploy High-Capacity Dewatering Pumps | `river_embankment` | `grounded_category` | `[S36]` (Pumps in Sivasagar) | -40% rain accumulation rate | +0.05 standing load on local power/fuel |
| `embankment_sandbagging` | Embankment Reinforcement & Sandbagging | `river_embankment` | `grounded_category` | `[S13]`, `[S16]`, `[S24]` (Breach repairs) | -50% upstream surge gain | +0.08 transport congestion from material trucks |
| `traffic_diversion` | Traffic Diversion & Arterial Closure | `transport` | `grounded_category` | `[S12]`, `[S19]` (Highway submersions) | -60% embankment overflow transmission | +0.12 emergency response transit delay |
| `rail_service_diversion` | Rail Traffic Diversion & Track Protection | `transport` | `grounded_category` | `[S14]`, `[S19]` (Simaluguri tracks flooded) | Caps transport stress at 0.65 | +0.05 passenger crowding at relief stations |
| `backup_power_deployment` | Mobile Diesel Backup Generators | `power` | `grounded_category` | `[S14]`, `[S21]`, `[S37]` (Substation cutoffs) | Caps power stress at 0.50 | None |
| `mobile_comms_tower` | Cell-on-Wheels (COW) Unit | `comms` | `assumed` | None (Disaster standard) | -50% power outage coupling | None |
| `medical_surge_supplies` | Medical Surge Capacity & Pre-positioned Stock | `health` | `grounded_category` | `[S1]`, `[S33]`, `[S41]` (Health camps) | Caps health stress at 0.60 | None |
| `rescue_boat_prepositioning` | NDRF / SDRF Boat & Ambulance Pre-positioning | `emergency_response` | `grounded_category` | `[S11]`, `[S19]`, `[S22]` (62 SDRF boats) | -55% transit bottleneck delay | +0.04 road transport load from boat trailers |
| `staged_population_evacuation`| Staged Evacuation to High-Ground Relief Camps | `emergency_response`, `health`, `transport` | `grounded_category` | `[S5]`, `[S11]`, `[S45]` (300k in camps) | -65% population exposure load | +0.25 road gridlock + 0.08 camp clinic load |
| `early_school_closure` | Early School Closure & Bus Stand-Down | `transport`, `emergency_response` | `grounded_category` | `[S17]`, `[S18]`, `[S34]`, `[S50]` (Vacation extended) | -25% base traffic load on primary roads | +0.02 emergency response monitoring |

---

## 3. Assumptions Register

Every numerical value used in the planner is cataloged with its assumed dispersion and sensitivity notes:

| Parameter Key | Nominal Value | Uncertainty Range | Provenance | Sensitivity Analysis Behavior |
| :--- | :---: | :---: | :--- | :--- |
| `deploy_dewatering_pumps.activation_delay` | 2.0 h | [1.0, 3.0] h | `grounded_category` | If delay > 4h, water accumulates past embankment breach before pumps activate. |
| `deploy_dewatering_pumps.benefit.rain_gain` | 0.60x | [0.48, 0.72]x | `grounded_category` | At 0.72x (weaker pump), cascade break occurs 4.5h later. |
| `embankment_sandbagging.activation_delay` | 4.0 h | [2.0, 6.0] h | `grounded_category` | Sandbagging is labour intensive; delays above 6h miss the crest of upstream flash surges. |
| `embankment_sandbagging.benefit.upstream_gain` | 0.50x | [0.37, 0.62]x | `grounded_category` | High sensitivity: key driver in breaking cross-zone Nagaland-to-Assam propagation. |
| `traffic_diversion.benefit.scale_edge` | 0.40x | [0.30, 0.50]x | `grounded_category` | Reduces cascading to hospital supply lines. |
| `traffic_diversion.side_effect.emergency_delay` | +0.12 | [0.08, 0.16] | `assumed` | Essential trade-off: diverting traffic protects vehicles but delays ambulances. |
| `staged_population_evacuation.exposure_change` | 0.35x | [0.28, 0.42]x | `grounded_category` | Massive reduction in human vulnerability, but high resource consumption. |
| `staged_population_evacuation.side_effect.road_congestion` | +0.25 weight | [0.18, 0.32] | `grounded_category` | Propagates sharp transport stress spike within 1-2 hours of evacuation order. |
| `medical_surge_supplies.cap_stress` | 0.60 max | [0.50, 0.70] | `grounded_category` | Absorbs patient inflow up to field hospital capacity. |
| `rescue_boat_prepositioning.benefit.transport_delay` | 0.45x | [0.36, 0.54]x | `grounded_category` | Bypasses road blockages by water transit. |

---

## 4. Multi-Objective Net Benefit Formulation

The planner evaluates candidate plans using a multi-objective loss function under **Common Random Numbers (CRN)**:

$$\Delta \mathcal{L}(\text{plan}) = \mathbb{E}[\text{CriticalZoneHours}_{\text{do\_nothing}}] - \mathbb{E}[\text{CriticalZoneHours}_{\text{plan}}]$$

$$\text{Harm}(\text{plan}) = \sum_{v \in \mathcal{V}} w_v \cdot \max(0, P_{\text{plan}}(s_v \ge \text{critical}) - P_{\text{baseline}}(s_v \ge \text{critical}))$$

$$\text{NetBenefit} = \Delta \mathcal{L}(\text{plan}) - \lambda_{\text{side}} \cdot \text{Harm}(\text{plan}) - \lambda_{\text{cost}} \cdot \sum_{r} \frac{\text{Used}_r}{\text{Budget}_r}$$

Default weights in `configs/interventions.yaml`:
- $\lambda_{\text{side}} = 1.5$ (High penalty ensuring side-effects like evacuation congestion are not ignored)
- $\lambda_{\text{cost}} = 0.1$ (Regularisation penalty favoring cost-efficient interventions)

---

## 5. How to Modify or Re-Calibrate an Assumption

1. To modify an assumption, edit `configs/interventions.yaml`.
2. Update the `parameters:`, `benefit_patches:`, or `resource_costs:` block for the corresponding action.
3. If real field data becomes available (e.g. from local district authorities), update `provenance:` from `assumed` to `expert_estimate_needed` or `calibrated_field_study`.
4. Run sensitivity analysis (`scripts/plan_interventions.py --sensitivity`) to inspect how plan ranking varies across $\pm 50\%$ perturbations.
