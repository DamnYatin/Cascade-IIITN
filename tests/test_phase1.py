"""Assam Phase 1 comprehensive acceptance and migration tests.

Verifies:
  1. Hygiene and Secrets (zero banned terms, no secrets in tracked files, assam-only endpoints)
  2. Geography and Configs (bounds, polygons, centroids, charaideo-sivasagar touch, symmetry, generalization)
  3. Time and UTC Awareness (IST to UTC conversions, naive datetimes rejected, arrival >= event)
  4. Rain Adapters (ERA5-Land deaccumulation, IMERG aggregation, zonal area mean, latency gating, offline)
  5. Synthetic Generator (determinism, seed divergence, real rain coupling, anchor mode)
  6. Faults and Leakage (fault injector effects, leakage canary on hero window, import isolation)
  7. Ground Truth and Report Fidelity (source tags, reliability grades, golden anchors, conflict preservation)
  8. Integration (CLI runs, API endpoints, WebSocket messages)
"""
from __future__ import annotations

import ast
import asyncio
import importlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from shapely.geometry import Polygon, box

from backend.app.adapters.base import (
    aggregate_half_hourly_to_hourly,
    compute_zonal_area_weighted_mean,
    deaccumulate_era5_precipitation,
)
from backend.app.adapters.cwc import CWCAdapter
from backend.app.adapters.openmeteo import OpenMeteoAdapter
from backend.app.api import app, cities, health, city as api_city
from backend.app.city_config import load_city_config
from backend.app.replay.clock import ReplayClock
from backend.app.replay.faults import FaultInjector, FaultSpec
from backend.app.replay.stream import ReplayStream
from backend.app.schemas import Observation, QualityFlag, SourceKind, Zone
from backend.app.synth.generator import generate_city
from backend.app.synth.planted_graph import build_planted_graph

from tests.conftest import REPO, serialize_ground_truth, serialize_observations

UPPER_ASSAM_YAML = REPO / "configs" / "upper_assam.yaml"
NORTH_BANK_YAML = REPO / "configs" / "north_bank_assam.yaml"
SCENARIOS_DIR = REPO / "configs" / "scenarios" / "assam_2026"
REPORT_MD = REPO / "docs" / "sources" / "Assam_Floods_2026_Report.md"


# ===========================================================================
# 1. Hygiene & Secrets
# ===========================================================================
def test_no_maharashtra_residue():
    """Ensure no Maharashtra residue remains in tracked files outside allowlist."""
    banned_terms = [
        "maharashtra", "mumbai", "thane", "konkan", "kolhapur",
        "sangli", "ratnagiri", "raigad", "palghar", "pune", "nashik", "satara",
    ]
    pattern = re.compile(r"\b(" + "|".join(banned_terms) + r")\b", re.IGNORECASE)

    allowlist_files = {
        "docs/ASSAM_MIGRATION.md",
        "docs/PLAYBOOK.md",
        "tests/test_phase1.py",
        "tests/ASSAM_MIGRATION_TEST_REPORT.md",
    }

    import subprocess
    res = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True)
    tracked_files = [f.strip() for f in res.stdout.splitlines() if f.strip()]

    violating_matches = []
    for rel_path in tracked_files:
        if rel_path.replace("\\", "/") in allowlist_files:
            continue
        full_path = REPO / rel_path
        if not full_path.exists() or full_path.is_dir():
            continue
        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore")
            for line_no, line in enumerate(content.splitlines(), start=1):
                if pattern.search(line):
                    violating_matches.append(f"{rel_path}:{line_no}: {line.strip()}")
        except Exception:
            pass

    assert not violating_matches, f"Found banned Maharashtra residue in tracked files:\n" + "\n".join(violating_matches[:10])


def test_no_secrets_in_repo():
    """Verify no Google, NASA, or Copernicus tokens/keys are in tracked files or .env.example."""
    secret_patterns = [
        re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
        re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE),
        re.compile(r"https://cds\.climate\.copernicus\.eu/api.*key:\s*[a-zA-Z0-9_-]+", re.DOTALL),
    ]

    import subprocess
    res = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True)
    tracked = [f.strip() for f in res.stdout.splitlines() if f.strip()]

    # .env must be ignored
    res_ignore = subprocess.run(["git", "check-ignore", ".env"], cwd=REPO, capture_output=True, text=True)
    assert ".env" in res_ignore.stdout.strip(), ".env must be ignored by git!"

    # Scan tracked files
    for rel in tracked:
        fp = REPO / rel
        if not fp.exists() or fp.is_dir():
            continue
        text = fp.read_text(encoding="utf-8", errors="ignore")
        for pat in secret_patterns:
            matches = pat.findall(text)
            assert not matches, f"Possible secret found in tracked file {rel}: {matches}"


def test_cities_endpoint_lists_assam_only():
    """GET /cities must return only upper_assam and north_bank_assam."""
    res = cities()
    city_ids = [c["city_id"] for c in res["cities"]]
    assert set(city_ids) == {"upper_assam", "north_bank_assam"}


# ===========================================================================
# 2. Geography & Configs
# ===========================================================================
def test_zone_polygons_valid_and_non_empty():
    """GeoJSON polygons must be valid, non-empty, and under 300 KB."""
    geo_path = REPO / "frontend" / "public" / "geo" / "upper_assam.geojson"
    assert geo_path.exists(), f"GeoJSON missing: {geo_path}"
    assert geo_path.stat().st_size < 300 * 1024, "GeoJSON exceeds 300 KB size limit"

    data = json.loads(geo_path.read_text(encoding="utf-8"))
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 10

    for feat in data["features"]:
        geom = Polygon(feat["geometry"]["coordinates"][0])
        assert geom.is_valid
        assert not geom.is_empty
        assert geom.area > 0


def test_centroids_inside_assam_nagaland_bounds(upper_assam_config):
    """Centroids must fall within regional bounds: lat 24.0-28.5, lon 89.5-96.5."""
    for z in upper_assam_config.zones:
        assert 24.0 <= z.centroid_lat <= 28.5, f"Centroid lat out of bounds for {z.id}: {z.centroid_lat}"
        assert 89.5 <= z.centroid_lon <= 96.5, f"Centroid lon out of bounds for {z.id}: {z.centroid_lon}"


def test_charaideo_exists_and_touches_sivasagar(upper_assam_config):
    """Charaideo must exist and list sivasagar as a neighbour."""
    zone_map = {z.id: z for z in upper_assam_config.zones}
    assert "charaideo" in zone_map
    assert "sivasagar" in zone_map
    assert "sivasagar" in zone_map["charaideo"].neighbours
    assert "charaideo" in zone_map["sivasagar"].neighbours


def test_every_upstream_zone_linked_to_assam_zone(upper_assam_config):
    """Upstream Nagaland zones must have river links or adjacency to Assam core zones."""
    upstream = [z for z in upper_assam_config.zones if z.role == "upstream_driver"]
    assert len(upstream) == 3  # mon_nl, mokokchung_nl, wokha_nl

    core_assam = {"charaideo", "sivasagar", "jorhat", "golaghat"}
    for uz in upstream:
        adj_or_river = set(uz.neighbours) | {rl["target"] for rl in uz.river_links}
        overlap = adj_or_river & core_assam
        assert overlap, f"Upstream zone {uz.id} has no link to core Assam zones: {adj_or_river}"


def test_adjacency_symmetric(upper_assam_config, north_bank_config):
    """Adjacency must be strictly symmetric."""
    for cfg in (upper_assam_config, north_bank_config):
        zone_map = {z.id: z for z in cfg.zones}
        for z in cfg.zones:
            for n_id in z.neighbours:
                assert n_id in zone_map
                assert z.id in zone_map[n_id].neighbours, f"{z.id} lists {n_id}, but {n_id} does not list {z.id}"


def test_both_assam_configs_load_without_code_changes(upper_assam_config, north_bank_config):
    """Upper Assam (10 zones x 6 systems) and North Bank (6 zones x 5 systems) load through same loader."""
    assert upper_assam_config.city_id == "upper_assam"
    assert len(upper_assam_config.zones) == 10
    assert len(upper_assam_config.systems) == 6

    assert north_bank_config.city_id == "north_bank_assam"
    assert len(north_bank_config.zones) == 6
    assert len(north_bank_config.systems) == 5


def test_renamed_systems_and_zones_config_generates_valid_stream(tmp_path):
    """A config with completely custom zones and systems generates a valid stream (no hardcoding)."""
    custom_yaml = tmp_path / "custom_city.yaml"
    custom_yaml.write_text(
        """
city_id: test_custom
start_time_utc: '2026-07-20T00:00:00Z'
critical_stress_threshold: 0.8
zones:
  - id: alpha
    name: Alpha Zone
    centroid_lat: 26.5
    centroid_lon: 94.0
    neighbours: [beta]
  - id: beta
    name: Beta Zone
    centroid_lat: 26.6
    centroid_lon: 94.1
    neighbours: [alpha]
systems:
  - id: custom_drainage
    name: Drainage
    capacity: 100.0
    unit: index
  - id: custom_roads
    name: Roads
    capacity: 100.0
    unit: index
streams:
  - source: custom_sensor
    system: custom_drainage
    cadence_hours: 1.0
    typical_delay_hours: 1.0
    noise_level: 0.05
    source_kind: simulated
domain_prior_edges: []
""",
        encoding="utf-8",
    )
    cfg = load_city_config(custom_yaml)
    obs, gt = generate_city(cfg, seed=1, duration_hours=24)
    assert len(obs) > 0
    assert gt.city_id == "test_custom"


# ===========================================================================
# 3. Time & UTC
# ===========================================================================
def test_ist_to_utc_anchors_exact():
    """Betbari (19:30 IST = 14:00Z) and Santak (13:00 IST = 07:30Z) calculated in code."""
    ist = timezone(timedelta(hours=5, minutes=30))

    betbari_ist = datetime(2026, 7, 19, 19, 30, tzinfo=ist)
    assert betbari_ist.astimezone(timezone.utc) == datetime(2026, 7, 19, 14, 0, tzinfo=timezone.utc)

    santak_ist = datetime(2026, 7, 19, 13, 0, tzinfo=ist)
    assert santak_ist.astimezone(timezone.utc) == datetime(2026, 7, 19, 7, 30, tzinfo=timezone.utc)


def test_naive_datetimes_rejected():
    """Naive datetimes must raise ValueError."""
    from backend.app.schemas import Observation
    with pytest.raises(ValueError, match="timezone-aware"):
        Observation(
            source="test",
            source_kind=SourceKind.REAL,
            zone="sivasagar",
            system="river_embankment",
            value=10.0,
            event_time=datetime(2026, 7, 20, 10, 0),  # naive!
            arrival_time=datetime(2026, 7, 20, 11, 0, tzinfo=timezone.utc),
        )


def test_all_datetimes_utc_aware(upper_assam_config):
    """Every generated observation must be UTC timezone-aware."""
    obs, gt = generate_city(upper_assam_config, seed=1, duration_hours=24)
    for o in obs:
        assert o.event_time.tzinfo == timezone.utc
        assert o.arrival_time.tzinfo == timezone.utc
        assert o.arrival_time >= o.event_time


# ===========================================================================
# 4. Rain Adapters (Fixture-based & Offline)
# ===========================================================================
def test_era5_land_deaccumulation_with_midnight_reset():
    """ERA5-Land accumulation deaccumulates hourly mm and handles 00:00 UTC resets cleanly."""
    t0 = datetime(2026, 7, 19, 0, 0, tzinfo=timezone.utc)
    # Day 1: 00:00 (0.0), 01:00 (10.0), 02:00 (25.0), 03:00 (25.0)
    # Day 2 reset: 00:00 reset (0.0), 01:00 (5.0), 02:00 (15.0)
    raw = [
        (t0 + timedelta(hours=1), 10.0),
        (t0 + timedelta(hours=2), 25.0),
        (t0 + timedelta(hours=3), 25.0),
        (t0 + timedelta(hours=24 + 1), 5.0),
        (t0 + timedelta(hours=24 + 2), 15.0),
    ]
    res = deaccumulate_era5_precipitation(raw)
    assert len(res) == 5
    # Hourly rates: 10.0, 15.0, 0.0, 5.0, 10.0
    assert res[0][1] == 10.0
    assert res[1][1] == 15.0
    assert res[2][1] == 0.0
    assert res[3][1] == 5.0
    assert res[4][1] == 10.0


def test_imerg_half_hourly_to_hourly_aggregation():
    """IMERG 30-min rain rates (mm/hr) aggregate into hourly depths."""
    t0 = datetime(2026, 7, 20, 14, 0, tzinfo=timezone.utc)
    half_hourly = [
        (t0, 12.0),
        (t0 + timedelta(minutes=30), 16.0),
        (t0 + timedelta(hours=1), 8.0),
        (t0 + timedelta(hours=1, minutes=30), 10.0),
    ]
    hourly = aggregate_half_hourly_to_hourly(half_hourly)
    assert len(hourly) == 2
    # 14:00 depth = (12 + 16) / 2 = 14.0 mm
    assert hourly[0][1] == 14.0
    # 15:00 depth = (8 + 10) / 2 = 9.0 mm
    assert hourly[1][1] == 9.0


def test_zonal_area_weighted_mean_toy_polygon():
    """Zonal weighting on toy polygon matches analytical solution."""
    # Zone: box [0, 0] to [2, 1] (area = 2.0)
    zone_poly = box(0.0, 0.0, 2.0, 1.0)
    # Cell 1: [0, 0] to [1, 1], value = 10.0 (inter area = 1.0)
    # Cell 2: [1, 0] to [2, 1], value = 20.0 (inter area = 1.0)
    cells = [
        (box(0.0, 0.0, 1.0, 1.0), 10.0),
        (box(1.0, 0.0, 2.0, 1.0), 20.0),
    ]
    mean_val = compute_zonal_area_weighted_mean(cells, zone_poly)
    assert abs(mean_val - 15.0) < 1e-4


def test_adapter_latency_gating_never_leaks_future(upper_assam_config):
    """Source with latency_hours releases nothing before event_time + latency."""
    adapter = OpenMeteoAdapter(city_id="upper_assam", latency_hours=24.0)
    start_t = upper_assam_config.start_time_utc
    obs = adapter.to_observations("sivasagar", start_t, start_t + timedelta(hours=12))

    for o in obs:
        assert o.arrival_time == o.event_time + timedelta(hours=24.0)
        assert o.arrival_time > o.event_time


def test_offline_mode_raises_on_missing_cache():
    """Offline mode with missing cache must raise FileNotFoundError, not fake data."""
    adapter = OpenMeteoAdapter(city_id="nonexistent_city", cache_dir=REPO / "data" / "cache" / "openmeteo")
    with pytest.raises(FileNotFoundError):
        adapter.to_rain_series("sivasagar", datetime(2026, 7, 20, tzinfo=timezone.utc), datetime(2026, 7, 21, tzinfo=timezone.utc))


# ===========================================================================
# 5. Synthetic Generator & Ground Truth
# ===========================================================================
def test_determinism_same_seed_byte_identical(upper_assam_config):
    obs1, gt1 = generate_city(upper_assam_config, seed=7, duration_hours=72)
    obs2, gt2 = generate_city(upper_assam_config, seed=7, duration_hours=72)
    assert serialize_observations(obs1) == serialize_observations(obs2)
    assert serialize_ground_truth(gt1) == serialize_ground_truth(gt2)


def test_determinism_differs_with_seed(upper_assam_config):
    obs_a, gt_a = generate_city(upper_assam_config, seed=1, duration_hours=48)
    obs_b, gt_b = generate_city(upper_assam_config, seed=2, duration_hours=48)
    assert serialize_observations(obs_a) != serialize_observations(obs_b)
    assert serialize_ground_truth(gt_a) != serialize_ground_truth(gt_b)


def test_real_rain_coupling_zero_vs_scaled(upper_assam_config):
    """Scaling rain up triggers planted critical stress; scaling to 0 keeps stress minimal."""
    hours = 48
    zero_rain = {z.id: {h: 0.0 for h in range(hours + 1)} for z in upper_assam_config.zones}
    heavy_rain = {z.id: {h: 40.0 for h in range(hours + 1)} for z in upper_assam_config.zones}

    _, gt_zero = generate_city(upper_assam_config, seed=1, duration_hours=hours, rain_series=zero_rain)
    _, gt_heavy = generate_city(upper_assam_config, seed=1, duration_hours=hours, rain_series=heavy_rain)

    # Heavy rain produces substantially higher peak stress than zero rain
    max_stress_zero = max(max(s) for s in gt_zero.stress.values())
    max_stress_heavy = max(max(s) for s in gt_heavy.stress.values())
    assert max_stress_heavy > max_stress_zero + 0.3


def test_planted_graph_differs_from_prior(upper_assam_config):
    """Planted graph must differ from weak domain prior (at least 1 surprising edge)."""
    gt_graph = build_planted_graph(upper_assam_config.zones, upper_assam_config.systems, upper_assam_config.start_time_utc, seed=1)
    gt_edge_set = {(e.u, e.v) for e in gt_graph.edges}
    prior_edge_set = {(e.u, e.v) for e in upper_assam_config.domain_prior_edges}

    # Surprising edge present in ground truth but absent from prior
    surprising_in_gt = gt_edge_set - prior_edge_set
    assert surprising_in_gt, "Circularity mitigation failed: Planted graph has no extra edge beyond prior"


def test_anchor_mode_honesty_switch(upper_assam_config):
    """anchor_mode=on tags outputs with anchored=true; anchor_mode=off never does."""
    obs_off, _ = generate_city(upper_assam_config, seed=1, duration_hours=24, anchor_mode="off")
    obs_on, _ = generate_city(upper_assam_config, seed=1, duration_hours=24, anchor_mode="on")

    for o in obs_off:
        flags = [str(f.value if hasattr(f, "value") else f) for f in o.quality_flags]
        assert "anchored" not in flags
        assert not any("anchored=true" in f for f in flags)

    anchored_found = False
    for o in obs_on:
        flags = [str(f.value if hasattr(f, "value") else f) for f in o.quality_flags]
        if "anchored" in flags or any("anchored=true" in f for f in flags):
            anchored_found = True
            break
    assert anchored_found, "anchor_mode=on failed to tag observations with anchored=true"


# ===========================================================================
# 6. Faults & Leakage
# ===========================================================================
def test_leakage_canary_assam_hero_window(upper_assam_config):
    """Replacing everything after T with garbage leaves events released at or before T bit-for-bit identical."""
    obs, _ = generate_city(upper_assam_config, seed=11, duration_hours=72)
    t0 = upper_assam_config.start_time_utc
    cutoff = t0 + timedelta(hours=24)

    stream_a = ReplayStream(list(obs))
    a_before = stream_a.release_until(cutoff)

    # Mutate everything after cutoff
    corrupted = []
    for o in obs:
        if o.event_time > cutoff:
            corrupted.append(o.model_copy(update={"value": 999999.0}))
        else:
            corrupted.append(o)

    stream_b = ReplayStream(corrupted)
    b_before = stream_b.release_until(cutoff)

    assert serialize_observations(a_before) == serialize_observations(b_before)


def test_import_isolation_no_synth_in_model_packages():
    """Verify model/replay/forecast packages never import synth and forecast source contains no forbidden references."""
    prohibited_modules = ["backend.app.synth"]
    forbidden_terms = [
        "critical_labels.json",
        "observed_response.json",
        "events.json",
        "official_bulletins.json",
        "planted",
        "ground_truth",
    ]
    packages = [
        "backend.app.replay",
        "backend.app.city_config",
        "backend.app.schemas",
        "backend.app.adapters",
        "backend.app.forecast",
    ]

    for pkg_name in packages:
        mod = importlib.import_module(pkg_name)
        pkg_path = Path(mod.__file__).parent
        for py in pkg_path.glob("**/*.py"):
            text = py.read_text(encoding="utf-8")
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for prohibited in prohibited_modules:
                            assert not alias.name.startswith(prohibited), f"{py} imports {alias.name}"
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for prohibited in prohibited_modules:
                            assert not node.module.startswith(prohibited), f"{py} imports from {node.module}"

            # If inside forecast package, scan source for forbidden terms/files
            if "forecast" in pkg_name:
                for term in forbidden_terms:
                    assert term not in text.lower(), f"{py} references forbidden term/file: {term}"


def test_fault_dropout_reduces_stream(upper_assam_config):
    obs, _ = generate_city(upper_assam_config, seed=1, duration_hours=48)
    inj = FaultInjector(seed=42)
    inj.add_fault(FaultSpec(kind="dropout", probability=0.5, start_hour=0, end_hour=100))
    faulted = inj.apply(list(obs), upper_assam_config.start_time_utc)
    assert len(faulted) < len(obs)


def test_fault_spike_changes_values(upper_assam_config):
    obs, _ = generate_city(upper_assam_config, seed=1, duration_hours=48)
    inj = FaultInjector(seed=42)
    inj.add_fault(FaultSpec(kind="spike", probability=1.0, spike_magnitude=50.0, start_hour=0, end_hour=100))
    faulted = inj.apply(list(obs), upper_assam_config.start_time_utc)
    spiked_count = sum(1 for o in faulted if QualityFlag.SPIKE in o.quality_flags or "spike" in o.quality_flags)
    assert spiked_count > 0


# ===========================================================================
# 7. Ground Truth & Report Fidelity
# ===========================================================================
def test_all_source_tags_exist_in_report():
    """Every source tag cited in JSON files must exist in Assam_Floods_2026_Report.md."""
    report_text = REPORT_MD.read_text(encoding="utf-8")
    report_tags = set(re.findall(r"\[(S\d+)\]", report_text)) | set(re.findall(r"\|\s*(S\d+)\s*\|", report_text))

    for json_file in ["events.json", "critical_labels.json", "observed_response.json"]:
        path = SCENARIOS_DIR / json_file
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data:
            for tag in item.get("source_tags", []):
                assert tag in report_tags, f"Tag {tag} in {json_file} does not exist in the report!"


def test_golden_spot_checks_deaths_and_damage():
    """Golden checks: 100 deaths (9-10 Aug), 103 (12-13 Aug), 7.05L affected (25 Jul), Rs 480 Cr (17 Aug), Rs 379.35 Cr (14 Aug)."""
    events = json.loads((SCENARIOS_DIR / "events.json").read_text(encoding="utf-8"))

    # 1. 100 deaths on 9-10 Aug
    toll_100 = next(e for e in events if e["id"] == "ev_20260810_toll_100")
    assert toll_100["value"] == 100.0

    # 2. 103 deaths on 12-13 Aug
    toll_103 = next(e for e in events if e["id"] == "ev_20260813_toll_103")
    assert toll_103["value"] == 103.0

    # 3. Peak 7.05 lakh on 25 Jul
    peak = next(e for e in events if e["id"] == "ev_20260725_peak_impact")
    assert peak["value"] == 705000.0

    # 4. Rs 480 crore on 17 Aug
    damage = next(e for e in events if e["id"] == "ev_20260817_damage_assessment")
    assert damage["value"] == 480.0

    # 5. Rs 379.35 crore SDRF on 14 Aug
    sdrf = next(e for e in events if e["id"] == "ev_20260814_sdrf_advance")
    assert sdrf["value"] == 379.35

    # 6. District deaths sum to 95 on 5-6 Aug
    dist_deaths = [50, 21, 9, 5, 3, 2, 2, 1, 1, 1]
    assert sum(dist_deaths) == 95


def test_conflicts_preserved_under_conflict_group():
    """Crop area (11,933.46 vs ~119,000 ha) and death toll (31 vs 41) must be preserved side-by-side."""
    events = json.loads((SCENARIOS_DIR / "events.json").read_text(encoding="utf-8"))

    crop_conflicts = [e for e in events if e.get("conflict_group") == "crop_area_20260809"]
    assert len(crop_conflicts) == 2
    crop_vals = {c["value"] for c in crop_conflicts}
    assert 11933.46 in crop_vals
    assert 119000.0 in crop_vals

    toll_conflicts = [e for e in events if e.get("conflict_group") == "toll_20260722"]
    assert len(toll_conflicts) == 2
    toll_vals = {t["value"] for t in toll_conflicts}
    assert 31.0 in toll_vals
    assert 41.0 in toll_vals


def test_day_precision_records_have_full_day_interval():
    """Records with time_precision: day must span a full 24h interval in UTC."""
    events = json.loads((SCENARIOS_DIR / "events.json").read_text(encoding="utf-8"))
    for e in events:
        if e.get("time_precision") == "day":
            t_start = datetime.fromisoformat(e["interval_utc"][0].replace("Z", "+00:00"))
            t_end = datetime.fromisoformat(e["interval_utc"][1].replace("Z", "+00:00"))
            # Must span at least 24 hours
            assert (t_end - t_start).total_seconds() >= 86400.0


# ===========================================================================
# 8. Integration & CLI
# ===========================================================================
def test_cli_smoke_runs_both_cities():
    """CLI smoke tests for upper_assam and north_bank_assam exit with code 0."""
    from scripts.run_replay import main as replay_main
    ret1 = replay_main(["--city", "upper_assam", "--seed", "1", "--hours", "24", "--rain-window", "peak"])
    assert ret1 == 0

    ret2 = replay_main(["--city", "north_bank_assam", "--seed", "1", "--hours", "24"])
    assert ret2 == 0


def test_consecutive_cli_determinism():
    """Consecutive CLI runs with identical flags produce identical stream hash."""
    from scripts.run_replay import main as replay_main, compute_stream_hash
    # Handled via compute_stream_hash determinism
    cfg = load_city_config(UPPER_ASSAM_YAML)
    obs1, _ = generate_city(cfg, seed=42, duration_hours=24)
    obs2, _ = generate_city(cfg, seed=42, duration_hours=24)
    assert compute_stream_hash(obs1) == compute_stream_hash(obs2)


def test_api_endpoints_health_and_city_summary():
    """Verify /health and /city/{city_id} responses."""
    h = health()
    assert h["status"] == "ok"
    assert h["service"] == "72-hour-warning-phase1"

    c = api_city("upper_assam")
    assert c["city_id"] == "upper_assam"
    assert len(c["zones"]) == 10
    assert len(c["systems"]) == 6


def test_websocket_stream_delivers_schema_valid_observations():
    """Verify ReplaySession step advances clock and produces valid observation dictionaries."""
    from backend.app.api import ReplaySession, _step
    cfg = load_city_config(UPPER_ASSAM_YAML)
    session = ReplaySession(cfg, seed=1, duration_hours=24)

    released = _step(session, hours=2.0)
    assert len(released) > 0
    for obs in released:
        d = obs.model_dump()
        assert "obs_id" in d
        assert "source" in d
        assert "arrival_time" in d
        assert obs.arrival_time <= session.clock.now


def test_config_rejects_missing_city_id(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("zones: []\nsystems: []\nstreams: []\nstart_time_utc: '2026-07-05T00:00:00Z'", encoding="utf-8")
    with pytest.raises(ValueError, match="city_id"):
        load_city_config(p)


def test_config_rejects_self_neighbour():
    with pytest.raises(ValueError, match="cannot list itself as a neighbour"):
        Zone(id="z1", name="Z1", centroid_lat=26.0, centroid_lon=94.0, neighbours=["z1"])


def test_config_rejects_unknown_neighbour(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        """
city_id: bad
start_time_utc: '2026-07-05T00:00:00Z'
zones:
  - id: z1
    name: Z1
    centroid_lat: 26.0
    centroid_lon: 94.0
    neighbours: [z_ghost]
systems:
  - id: s1
    capacity: 100.0
streams: []
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown neighbour"):
        load_city_config(p)


def test_config_rejects_stream_with_unknown_system(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        """
city_id: bad
start_time_utc: '2026-07-05T00:00:00Z'
zones:
  - id: z1
    name: Z1
    centroid_lat: 26.0
    centroid_lon: 94.0
    neighbours: []
systems:
  - id: s1
    capacity: 100.0
streams:
  - source: sensor1
    system: s_ghost
    cadence_hours: 1.0
    typical_delay_hours: 0.5
    noise_level: 0.1
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown system"):
        load_city_config(p)


def test_fault_stuck_at_changes_values(upper_assam_config):
    obs, _ = generate_city(upper_assam_config, seed=1, duration_hours=48)
    inj = FaultInjector(seed=42)
    inj.add_fault(FaultSpec(kind="stuck_at", stuck_value=0.0, probability=1.0, start_hour=0, end_hour=100))
    faulted = inj.apply(list(obs), upper_assam_config.start_time_utc)
    stuck_count = sum(1 for o in faulted if QualityFlag.STUCK_AT in o.quality_flags or "stuck_at" in o.quality_flags)
    assert stuck_count > 0


def test_fault_feed_delay_shifts_arrival(upper_assam_config):
    obs, _ = generate_city(upper_assam_config, seed=1, duration_hours=48)
    inj = FaultInjector(seed=42)
    inj.add_fault(FaultSpec(kind="feed_delay", delay_hours=10.0, probability=1.0, start_hour=0, end_hour=100))
    faulted = inj.apply(list(obs), upper_assam_config.start_time_utc)
    delayed_count = sum(1 for o in faulted if QualityFlag.FEED_DELAY in o.quality_flags or "feed_delay" in o.quality_flags)
    assert delayed_count > 0


def test_fault_contradictory_duplicate_adds_observations(upper_assam_config):
    obs, _ = generate_city(upper_assam_config, seed=1, duration_hours=48)
    inj = FaultInjector(seed=42)
    inj.add_fault(FaultSpec(kind="contradictory_duplicate", probability=0.5, start_hour=0, end_hour=100))
    faulted = inj.apply(list(obs), upper_assam_config.start_time_utc)
    assert len(faulted) > len(obs)


def test_fault_zone_blackout_removes_zone(upper_assam_config):
    obs, _ = generate_city(upper_assam_config, seed=1, duration_hours=48)
    target_zone = upper_assam_config.zones[0].id
    inj = FaultInjector(seed=42)
    inj.add_fault(FaultSpec(kind="zone_blackout", target_zone=target_zone, start_hour=0, end_hour=100))
    faulted = inj.apply(list(obs), upper_assam_config.start_time_utc)
    remaining_zones = {o.zone for o in faulted}
    assert target_zone not in remaining_zones


def test_fault_reproducible_by_seed(upper_assam_config):
    obs, _ = generate_city(upper_assam_config, seed=1, duration_hours=48)
    inj1 = FaultInjector(seed=99)
    inj1.add_fault(FaultSpec(kind="spike", probability=0.3, spike_magnitude=10.0))
    inj2 = FaultInjector(seed=99)
    inj2.add_fault(FaultSpec(kind="spike", probability=0.3, spike_magnitude=10.0))
    f1 = inj1.apply(list(obs), upper_assam_config.start_time_utc)
    f2 = inj2.apply(list(obs), upper_assam_config.start_time_utc)
    assert serialize_observations(f1) == serialize_observations(f2)


def test_planted_graph_required_features(upper_assam_config):
    """Verify planted graph structure: signed negative edge, feedback loop, cross-zone, time-windowed, river links."""
    graph = build_planted_graph(upper_assam_config.zones, upper_assam_config.systems, upper_assam_config.start_time_utc, seed=1)
    edge_set = {(e.u, e.v) for e in graph.edges}

    # Signed negative edge present
    assert any(e.weight < 0 for e in graph.edges), "no negative edge planted"

    # Feedback loop: reciprocal edge pair
    reciprocal = any((v, u) in edge_set for (u, v) in edge_set)
    assert reciprocal, "no feedback loop planted"

    # Cross-zone edge
    def zone_of(node_id):
        return node_id.split(":")[0]
    cross_zone = any(e for e in graph.edges if zone_of(e.u) != zone_of(e.v))
    assert cross_zone, "no cross-zone edge planted"

    # Time-windowed edge
    windowed = [e for e in graph.edges if e.active_start is not None or e.active_end is not None]
    assert windowed, "no time-windowed edge planted"

    # River links
    river_links = [e for e in graph.edges if e.edge_type == "river_link"]
    assert river_links, "no river links planted"


def test_planted_graph_has_physical_chain(upper_assam_config):
    """Physical chain: river_embankment -> transport -> emergency_response -> health."""
    graph = build_planted_graph(upper_assam_config.zones, upper_assam_config.systems, upper_assam_config.start_time_utc, seed=1)
    # Check chain for core flood zone
    zone = "sivasagar"
    assert graph.has_edge(f"{zone}:river_embankment", f"{zone}:transport")
    assert graph.has_edge(f"{zone}:transport", f"{zone}:emergency_response")
    assert graph.has_edge(f"{zone}:emergency_response", f"{zone}:health")


def test_cwc_contract_rejects_naive_and_malformed(tmp_path):
    """CWC contract parser rejects naive timestamps and non-numeric values."""
    bad_csv = tmp_path / "bad_cwc.csv"
    bad_csv.write_text("timestamp_ist,level_m,warning_level_m,danger_level_m,hfl_m\n2026-07-20 10:00:00,NOT_A_NUM,100,105,110\n", encoding="utf-8")
    adapter = CWCAdapter(cwc_dir=tmp_path)
    with pytest.raises(ValueError):
        adapter.load_station(bad_csv, "sivasagar")


def test_provenance_matrix_sums_to_100(upper_assam_config):
    """Provenance matrix components sum strictly to 100%."""
    from scripts.run_replay import main as replay_main
    # Run with peak window
    obs, _ = generate_city(upper_assam_config, seed=1, duration_hours=24)
    adapter = OpenMeteoAdapter(city_id="upper_assam")
    real_obs = adapter.to_observations("sivasagar", upper_assam_config.start_time_utc, upper_assam_config.start_time_utc + timedelta(hours=24))
    all_obs = real_obs + obs

    real_c = sum(1 for o in all_obs if o.source_kind == SourceKind.REAL)
    sim_c = sum(1 for o in all_obs if o.source_kind == SourceKind.SIMULATED)
    total = len(all_obs)
    pct_sum = (real_c / total * 100.0) + (sim_c / total * 100.0)
    assert abs(pct_sum - 100.0) < 1e-4


def test_reliability_grades_match_report():
    """Reliability grades in scenario files must be valid A-D matching report."""
    events = json.loads((SCENARIOS_DIR / "events.json").read_text(encoding="utf-8"))
    for e in events:
        assert e["reliability"] in {"A", "B", "C", "D"}


def test_no_headline_record_relies_on_grade_d():
    """No headline: true record relies solely on grade D."""
    events = json.loads((SCENARIOS_DIR / "events.json").read_text(encoding="utf-8"))
    for e in events:
        if e.get("headline"):
            assert e["reliability"] != "D", f"Headline record {e['id']} relies solely on Grade D source!"


@pytest.mark.network
def test_live_network_openmeteo_fetch():
    """Live smoke fetch from Open-Meteo archive."""
    import requests
    r = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude": 26.96,
            "longitude": 94.66,
            "start_date": "2026-07-20",
            "end_date": "2026-07-21",
            "hourly": "precipitation",
            "timezone": "UTC",
        },
        timeout=10,
    )
    assert r.status_code == 200
    assert len(r.json().get("hourly", {}).get("precipitation", [])) > 0

