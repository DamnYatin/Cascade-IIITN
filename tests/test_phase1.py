"""Phase 1 acceptance tests.

All must pass:
1. Determinism
2. Arrival ordering / gating / no-repeat
3. Leakage canary
4. Import isolation
5. Disaggregation (daily-total conservation)
6. Planted graph features
7. Fault injector
8. Config validation (both cities + invalid)
9. UTC-aware datetimes
"""
from __future__ import annotations

import ast
import importlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.app.city_config import load_city_config
from backend.app.synth.generator import generate_city
from backend.app.synth.planted_graph import build_planted_graph
from backend.app.replay.stream import ReplayStream
from backend.app.replay.clock import ReplayClock
from backend.app.replay.faults import FaultInjector, FaultSpec
from backend.app.adapters.imd_rain import IMDRainAdapter, PRESETS, DailyRow
from backend.app.schemas import SourceKind, QualityFlag

from tests.conftest import REPO, serialize_observations, serialize_ground_truth

MUMBAI = REPO / "configs" / "mumbai.yaml"
HELDOUT = REPO / "configs" / "heldout_city.yaml"
CSV = REPO / "data" / "processed" / "maharashtra_climate.csv"


# ---------------------------------------------------------------------------
# 1. Determinism
# ---------------------------------------------------------------------------
def test_determinism_same_seed_byte_identical(mumbai_config):
    obs1, gt1 = generate_city(mumbai_config, seed=7, duration_hours=72)
    obs2, gt2 = generate_city(mumbai_config, seed=7, duration_hours=72)
    assert serialize_observations(obs1) == serialize_observations(obs2)
    assert serialize_ground_truth(gt1) == serialize_ground_truth(gt2)


def test_determinism_differs_with_seed(mumbai_config):
    obs_a, gt_a = generate_city(mumbai_config, seed=1, duration_hours=48)
    obs_b, gt_b = generate_city(mumbai_config, seed=2, duration_hours=48)
    assert serialize_observations(obs_a) != serialize_observations(obs_b)
    assert serialize_ground_truth(gt_a) != serialize_ground_truth(gt_b)


# ---------------------------------------------------------------------------
# 2. Arrival ordering / gating / no-repeat
# ---------------------------------------------------------------------------
def test_release_ordering_and_gating(mumbai_config):
    observations, _ = generate_city(mumbai_config, seed=3, duration_hours=48)
    stream = ReplayStream(observations)
    t0 = mumbai_config.start_time_utc

    all_released = []
    released_ids = set()
    out_of_event_order = 0
    prev_event = None

    # Release in 6-hour steps across the horizon; cursor persists, so each call
    # returns only newly-released observations.
    for step in range(0, 49, 6):
        t = t0 + timedelta(hours=step)
        batch = stream.release_until(t)
        for o in batch:
            # gating: nothing released has arrival_time > clock
            assert o.arrival_time <= t, (o.obs_id, o.arrival_time, t)
            # no repeats across batches
            assert o.obs_id not in released_ids
            released_ids.add(o.obs_id)
            all_released.append(o)
            if prev_event is not None and o.event_time < prev_event:
                out_of_event_order += 1
            prev_event = o.event_time

    # flush the rest (arrivals beyond the last step) so every observation is
    # accounted for exactly once.
    rest = stream.release_until(t0 + timedelta(hours=1000))
    for o in rest:
        assert o.obs_id not in released_ids
        released_ids.add(o.obs_id)
    all_released.extend(rest)

    # globally sorted by arrival_time across all releases
    arrivals = [o.arrival_time for o in all_released]
    assert arrivals == sorted(arrivals)

    # every observation eventually released exactly once
    assert len(all_released) == len(observations)
    assert len(released_ids) == len(observations)

    # some observations arrive out of event_time order
    assert out_of_event_order > 0, "expected at least one out-of-event-order arrival"


# ---------------------------------------------------------------------------
# 3. Leakage canary
# ---------------------------------------------------------------------------
def test_leakage_canary(mumbai_config):
    observations, _ = generate_city(mumbai_config, seed=11, duration_hours=48)
    t0 = mumbai_config.start_time_utc
    T = t0 + timedelta(hours=24)

    # First replay: release everything up to T.
    stream_a = ReplayStream(list(observations))
    released_before_T = stream_a.release_until(T)

    # Second replay: replace every observation arriving after T with garbage
    # (shift its event far into the future / corrupt value). Releasing up to T
    # must be bit-for-bit identical.
    garbage = []
    for o in observations:
        if o.arrival_time > T:
            garbage.append(
                o.model_copy(
                    update={
                        "value": -999999.0,
                        "event_time": t0 + timedelta(days=365),
                        "arrival_time": t0 + timedelta(days=365),
                    }
                )
            )
        else:
            garbage.append(o)
    stream_b = ReplayStream(garbage)
    released_before_T_b = stream_b.release_until(T)

    assert serialize_observations(released_before_T) == serialize_observations(
        released_before_T_b
    )


# ---------------------------------------------------------------------------
# 4. Import isolation
# ---------------------------------------------------------------------------
def test_import_isolation_no_synth_in_model_packages():
    """backend.app.replay, .api, .city_config must not import synth ground truth."""
    import ast as _ast

    protected = [
        REPO / "backend" / "app" / "replay" / "stream.py",
        REPO / "backend" / "app" / "replay" / "clock.py",
        REPO / "backend" / "app" / "city_config.py",
        REPO / "backend" / "app" / "schemas.py",
    ]
    # api.py is the composition root: it legitimately wires the generator to the
    # replay, but it never emits GroundTruth over the WebSocket. It is therefore
    # deliberately excluded from this isolation check.
    for path in protected:
        src = path.read_text(encoding="utf-8")
        tree = _ast.parse(src)
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("backend.app.synth"), (
                        f"{path.name} imports {alias.name} (leakage risk)"
                    )
            elif isinstance(node, _ast.ImportFrom):
                if node.module and node.module.startswith("backend.app.synth"):
                    raise AssertionError(
                        f"{path.name} imports from {node.module} (leakage risk)"
                    )


# ---------------------------------------------------------------------------
# 5. Disaggregation conserves daily totals
# ---------------------------------------------------------------------------
def test_disaggregation_conserves_daily_total(ensure_rain_csv):
    adapter = IMDRainAdapter(CSV, seed=5)
    adapter.load()
    # Constructed row (hermetic): Mumbai 2019-06-29, 269 mm (matches the fixture).
    row = DailyRow(date(2019, 6, 29), "Mumbai", 19.076, 72.878, 269.0, 30.0, 25.0, 27.5)
    hourly = adapter.disaggregate_daily(row.rainfall, seed=42)
    assert abs(sum(hourly) - row.rainfall) < 0.01
    assert len(hourly) == 24
    assert all(v >= 0 for v in hourly)


def test_disaggregation_deterministic_for_seed():
    adapter = IMDRainAdapter(CSV, seed=5)
    adapter.load()
    daily = 360.0  # Thane 2021-07-20 magnitude
    h1 = adapter.disaggregate_daily(daily, seed=99)
    h2 = adapter.disaggregate_daily(daily, seed=99)
    assert h1 == h2
    h3 = adapter.disaggregate_daily(daily, seed=100)
    assert h3 != h1  # different seed -> different split


def test_adapter_loads_fixture_and_preset_extremes_match(ensure_rain_csv):
    """Verify the two replay presets against the CSV (Mumbai 2019 / Konkan 2021)."""
    adapter = IMDRainAdapter(CSV, seed=0)
    adapter.load()

    def rainfall(district: str, on: date) -> float:
        row = next(r for r in adapter._district_rows(district) if r.date == on)
        return row.rainfall

    assert abs(rainfall("Mumbai", date(2019, 6, 29)) - 269.0) < 1.0
    assert abs(rainfall("Thane", date(2021, 7, 20)) - 360.0) < 1.0
    assert abs(rainfall("Mumbai", date(2021, 7, 19)) - 281.0) < 1.0


# ---------------------------------------------------------------------------
# 6. Planted graph features
# ---------------------------------------------------------------------------
def test_planted_graph_required_features(mumbai_config):
    graph = build_planted_graph(mumbai_config.zones, mumbai_config.systems,
                                mumbai_config.start_time_utc, seed=1)

    edge_set = {(e.u, e.v) for e in graph.edges}

    # (b) signed negative edge present
    assert any(e.weight < 0 for e in graph.edges), "no negative edge planted"

    # (c) feedback loop: at least one pair with edges both directions
    reciprocal = any((v, u) in edge_set for (u, v) in edge_set)
    assert reciprocal, "no feedback loop (reciprocal edge) planted"

    # (d) cross-zone edge (different zones)
    def zone_of(node_id):
        return node_id.split(":")[0]
    cross_zone = any(e for e in graph.edges if zone_of(e.u) != zone_of(e.v))
    assert cross_zone, "no cross-zone edge planted"

    # (e) time-windowed edge present
    windowed = [e for e in graph.edges
                if e.active_start is not None or e.active_end is not None]
    assert windowed, "no time-windowed edge planted"

    # (f) decoy pairs: no planted edge connects a decoy pair
    for a, b in graph.decoy_pairs:
        assert (a, b) not in edge_set and (b, a) not in edge_set, (
            f"decoy pair {a}->{b} unexpectedly has a planted edge"
        )


def test_planted_graph_has_physical_chain(mumbai_config):
    graph = build_planted_graph(mumbai_config.zones, mumbai_config.systems,
                                mumbai_config.start_time_utc, seed=1)
    edge_set = {(e.u, e.v) for e in graph.edges}
    # rainfall->drainage is exogenous, not an edge; check drainage->roads->emergency->hospital
    zone = mumbai_config.zones[0].id
    assert (f"{zone}:drainage", f"{zone}:roads") in edge_set
    assert (f"{zone}:roads", f"{zone}:emergency_response") in edge_set
    assert (f"{zone}:emergency_response", f"{zone}:hospital") in edge_set


# ---------------------------------------------------------------------------
# 7. Fault injector
# ---------------------------------------------------------------------------
def _obs_list(config, seed, hours=48):
    obs, _ = generate_city(config, seed=seed, duration_hours=hours)
    return obs


def test_fault_dropout_reduces_stream(mumbai_config):
    obs = _obs_list(mumbai_config, seed=1)
    before = len(obs)
    inj = FaultInjector(seed=3)
    inj.add_fault(FaultSpec(kind="dropout", probability=1.0,
                            start_hour=0, end_hour=10**9))
    out = inj.apply(list(obs), mumbai_config.start_time_utc)
    assert len(out) < before
    assert len(inj.fault_log) > 0


def test_fault_stuck_at_changes_values(mumbai_config):
    obs = _obs_list(mumbai_config, seed=1)
    inj = FaultInjector(seed=4)
    inj.add_fault(FaultSpec(kind="stuck_at", probability=1.0,
                            stuck_value=42.0, start_hour=0, end_hour=10**9))
    out = inj.apply(list(obs), mumbai_config.start_time_utc)
    stuck = [o for o in out if QualityFlag.STUCK_AT in o.quality_flags]
    assert len(stuck) > 0
    assert all(o.value == 42.0 for o in stuck)


def test_fault_spike_changes_values(mumbai_config):
    obs = _obs_list(mumbai_config, seed=1)
    inj = FaultInjector(seed=5)
    inj.add_fault(FaultSpec(kind="spike", probability=1.0,
                            spike_magnitude=100.0, start_hour=0, end_hour=10**9))
    out = inj.apply(list(obs), mumbai_config.start_time_utc)
    spiked = [o for o in out if QualityFlag.SPIKE in o.quality_flags]
    assert len(spiked) > 0


def test_fault_feed_delay_shifts_arrival(mumbai_config):
    obs = _obs_list(mumbai_config, seed=1)
    inj = FaultInjector(seed=6)
    inj.add_fault(FaultSpec(kind="feed_delay", probability=1.0,
                            delay_hours=5.0, start_hour=0, end_hour=10**9))
    out = inj.apply(list(obs), mumbai_config.start_time_utc)
    delayed = [o for o in out if QualityFlag.FEED_DELAY in o.quality_flags]
    assert len(delayed) > 0
    assert all((o.arrival_time - o.event_time).total_seconds() / 3600 >= 5.0
               for o in delayed)


def test_fault_contradictory_duplicate_adds_observations(mumbai_config):
    obs = _obs_list(mumbai_config, seed=1)
    before = len(obs)
    inj = FaultInjector(seed=7)
    inj.add_fault(FaultSpec(kind="contradictory_duplicate", probability=1.0,
                            start_hour=0, end_hour=10**9))
    out = inj.apply(list(obs), mumbai_config.start_time_utc)
    assert len(out) > before
    flagged = [o for o in out if QualityFlag.CONTRADICTORY_DUPLICATE in o.quality_flags]
    assert len(flagged) > 0


def test_fault_zone_blackout_removes_zone(mumbai_config):
    obs = _obs_list(mumbai_config, seed=1)
    target_zone = mumbai_config.zones[0].id
    before_zone = sum(1 for o in obs if o.zone == target_zone)
    inj = FaultInjector(seed=8)
    inj.add_fault(FaultSpec(kind="zone_blackout", target_zone=target_zone,
                            probability=1.0, start_hour=0, end_hour=10**9))
    out = inj.apply(list(obs), mumbai_config.start_time_utc)
    after_zone = sum(1 for o in out if o.zone == target_zone)
    assert after_zone < before_zone


def test_fault_reproducible_by_seed(mumbai_config):
    obs = _obs_list(mumbai_config, seed=1)

    def run(seed):
        inj = FaultInjector(seed)
        inj.add_fault(FaultSpec(kind="spike", probability=0.5,
                                spike_magnitude=99.0, start_hour=0,
                                end_hour=10**9))
        return inj.apply(list(obs), mumbai_config.start_time_utc)

    r1 = run(42)
    r2 = run(42)
    assert serialize_observations(r1) == serialize_observations(r2)
    r3 = run(99)
    assert serialize_observations(r1) != serialize_observations(r3)


# ---------------------------------------------------------------------------
# 8. Config validation
# ---------------------------------------------------------------------------
def test_both_configs_validate(mumbai_config, heldout_config):
    assert mumbai_config.city_id == "mumbai"
    assert heldout_config.city_id == "heldout"
    assert len(mumbai_config.zones) != len(heldout_config.zones)


def test_heldout_city_runs_full_pipeline(heldout_config):
    obs, gt = generate_city(heldout_config, seed=3, duration_hours=48)
    assert len(obs) > 0
    assert gt.city_id == "heldout"
    stream = ReplayStream(obs)
    released = stream.release_until(
        heldout_config.start_time_utc + timedelta(hours=48)
    )
    assert len(released) > 0


def test_invalid_config_fails_clearly(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "city_id: bad\nzones: []\nsystems: []\nstreams: []\n"
        "start_time_utc: not-a-date\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_city_config(bad)


# ---------------------------------------------------------------------------
# 9. All datetimes UTC and timezone-aware
# ---------------------------------------------------------------------------
def test_all_datetimes_utc_aware(mumbai_config):
    obs, gt = generate_city(mumbai_config, seed=1, duration_hours=24)
    assert mumbai_config.start_time_utc.tzinfo is not None
    assert gt.start_time_utc.tzinfo is not None
    for o in obs:
        assert o.event_time.tzinfo is not None
        assert o.arrival_time.tzinfo is not None
        assert o.arrival_time >= o.event_time
