# 72-Hour Warning: Cascading Crisis Early Warning System (Phase 1)

> **Scenario:** Upper Assam Floods, July–August 2026.
> **Mission:** Predict cascading urban and regional crises up to 72 hours ahead from messy, delayed, incomplete real-world observation streams.

---

## Overview

The 72-Hour Warning Phase 1 provides a replayable, deterministic, leakage-proof backbone that models the cascading impacts of extreme hydrometeorological events:
1. **Upstream Antecedent Wetness & Surge:** Heavy rain across Nagaland hill catchments (Mon, Mokokchung, Wokha).
2. **Hydrological Surge:** Flooding along the Dikhow, Disang, and Dhansiri rivers reaching Upper Assam plains (Charaideo, Sivasagar, Jorhat, Golaghat) in ~1.5–3.5 hours.
3. **Infrastructure Cascades:** Embankment breaches -> transport (road/rail cutoffs) -> power distribution failures -> health facility isolation -> emergency response strain.

All real data is ingested with documented latency gating (`arrival_time = event_time + latency_hours`), strictly timezone-aware in UTC, and isolated from ground truth.

---

## Quickstart

```powershell
# 1. Install dependencies
pip install -r requirements.txt

# 2. Build configs from geometry
python scripts/build_assam_config.py --offline

# 3. Run test suite
pytest -q

# 4. Run CLI replay for Upper Assam hero scenario
python scripts/run_replay.py --city upper_assam --seed 7 --hours 72 --rain-window peak

# 5. Start API server
python -m backend.app.api
```

---

## Documentation

- [docs/PHASE1.md](docs/PHASE1.md): Technical layout, endpoints, and schema contracts.
- [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md): Data lineage, satellite feeds, licence attributions, and latency matrix.
- [docs/ASSAM_MIGRATION.md](docs/ASSAM_MIGRATION.md): Full migration log, codebase provenance, and ambiguity resolutions.
- [docs/PLAYBOOK.md](docs/PLAYBOOK.md): Project architecture and leakage isolation guidelines.

---

## Attribution
- District boundaries & infrastructure features: © OpenStreetMap contributors (ODbL).
- Meteorological reanalysis: Open-Meteo & ECMWF Copernicus Climate Change Service.
- Satellite precipitation: NASA Global Precipitation Measurement (GPM) Mission.
- Ground truth event facts: Curated from `docs/sources/Assam_Floods_2026_Report.md`.
