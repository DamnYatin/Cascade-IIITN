"""True episode extraction at node, zone-cascade, and city levels.

This module belongs strictly to the evaluation layer (backend/app/eval/) and may
read ground truth or latent stress trajectories.

Definitions:
  - Node-critical episode: stress >= critical_threshold.
  - Zone cascade-critical episode (PRIMARY): >= zone_cascade_min_systems distinct
    systems in the zone simultaneously critical.
  - City-critical episode: >= city_zone_fraction of zones simultaneously cascade-critical.
  - Episode boundaries: start = first hour meeting condition; end = first hour below.
  - Merge rule: episodes separated by less than merge_gap_hours (default 6) are merged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import numpy as np


@dataclass
class TrueEpisode:
    """Represents a true ground-truth stress episode."""

    episode_id: str
    entity_type: str  # "node" | "zone_cascade" | "city"
    entity_id: str  # e.g. "disang:roads", "disang", or "city"
    level: str  # "CRITICAL" | "HIGH_RISK"
    start_hour: float
    end_hour: float  # inclusive or first hour below
    peak_value: float = 1.0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_hours(self) -> float:
        return max(0.0, self.end_hour - self.start_hour)


def merge_raw_spans(
    spans: List[Tuple[float, float, float]],
    merge_gap_hours: float = 6.0,
) -> List[Tuple[float, float, float]]:
    """Merge continuous [start, end, peak] spans separated by < merge_gap_hours.

    Args:
        spans: List of (start_hour, end_hour, peak_val) sorted by start_hour.
        merge_gap_hours: Threshold gap below which two spans are joined.

    Returns:
        List of merged (start_hour, end_hour, peak_val).
    """
    if not spans:
        return []

    sorted_spans = sorted(spans, key=lambda s: s[0])
    merged: List[Tuple[float, float, float]] = [sorted_spans[0]]

    for cur_start, cur_end, cur_peak in sorted_spans[1:]:
        prev_start, prev_end, prev_peak = merged[-1]
        gap = cur_start - prev_end
        if gap < merge_gap_hours:
            # Join into single episode
            new_end = max(prev_end, cur_end)
            new_peak = max(prev_peak, cur_peak)
            merged[-1] = (prev_start, new_end, new_peak)
        else:
            merged.append((cur_start, cur_end, cur_peak))

    return merged


def extract_episodes_from_binary_mask(
    mask: List[bool] | np.ndarray,
    hours: List[float] | np.ndarray,
    values: Optional[List[float] | np.ndarray] = None,
    merge_gap_hours: float = 6.0,
) -> List[Tuple[float, float, float]]:
    """Extract and merge contiguous active spans from a boolean time mask.

    Returns:
        List of (start_hour, end_hour, peak_value).
    """
    spans: List[Tuple[float, float, float]] = []
    n = len(mask)
    if n == 0:
        return spans

    in_ep = False
    start_h = 0.0
    peak_v = 0.0

    for i in range(n):
        active = bool(mask[i])
        h = float(hours[i])
        v = float(values[i]) if values is not None else (1.0 if active else 0.0)

        if active and not in_ep:
            in_ep = True
            start_h = h
            peak_v = v
        elif active and in_ep:
            if v > peak_v:
                peak_v = v
        elif not active and in_ep:
            in_ep = False
            spans.append((start_h, h, peak_v))

    if in_ep:
        # Reached end of simulation while active
        final_h = float(hours[-1]) + 1.0 if len(hours) > 0 else start_h + 1.0
        spans.append((start_h, final_h, peak_v))

    return merge_raw_spans(spans, merge_gap_hours=merge_gap_hours)


def extract_node_episodes(
    stress_series: List[float] | np.ndarray,
    node_id: str,
    critical_threshold: float = 0.80,
    merge_gap_hours: float = 6.0,
    start_time_utc: Optional[datetime] = None,
) -> List[TrueEpisode]:
    """Extract critical episodes for a single node from latent stress trajectory."""
    hours = np.arange(len(stress_series), dtype=float)
    arr = np.asarray(stress_series, dtype=float)
    mask = arr >= critical_threshold
    spans = extract_episodes_from_binary_mask(
        mask=mask,
        hours=hours,
        values=arr,
        merge_gap_hours=merge_gap_hours,
    )

    episodes: List[TrueEpisode] = []
    for idx, (s_h, e_h, peak) in enumerate(spans):
        st_dt = start_time_utc + timedelta(hours=s_h) if start_time_utc else None
        et_dt = start_time_utc + timedelta(hours=e_h) if start_time_utc else None
        episodes.append(
            TrueEpisode(
                episode_id=f"node_{node_id}_ep{idx}",
                entity_type="node",
                entity_id=node_id,
                level="CRITICAL",
                start_hour=s_h,
                end_hour=e_h,
                peak_value=peak,
                start_time=st_dt,
                end_time=et_dt,
            )
        )
    return episodes


def extract_zone_cascade_episodes(
    node_stresses: Dict[str, List[float] | np.ndarray],
    zone_id: str,
    systems: List[str],
    min_systems: int = 2,
    critical_threshold: float = 0.80,
    merge_gap_hours: float = 6.0,
    start_time_utc: Optional[datetime] = None,
) -> List[TrueEpisode]:
    """Extract PRIMARY zone cascade-critical episodes.

    Definition: At least min_systems distinct systems in the zone are simultaneously critical.
    """
    # Find matching node series
    matching_nodes = [f"{zone_id}:{sys}" for sys in systems if f"{zone_id}:{sys}" in node_stresses]
    if not matching_nodes:
        return []

    # Align lengths
    min_len = min(len(node_stresses[n]) for n in matching_nodes)
    if min_len == 0:
        return []

    stacked_crit = np.zeros((len(matching_nodes), min_len), dtype=bool)
    for i, n in enumerate(matching_nodes):
        stacked_crit[i, :] = np.asarray(node_stresses[n][:min_len]) >= critical_threshold

    simultaneous_count = np.sum(stacked_crit, axis=0)  # shape (min_len,)
    mask = simultaneous_count >= min_systems
    hours = np.arange(min_len, dtype=float)

    spans = extract_episodes_from_binary_mask(
        mask=mask,
        hours=hours,
        values=simultaneous_count.astype(float),
        merge_gap_hours=merge_gap_hours,
    )

    episodes: List[TrueEpisode] = []
    for idx, (s_h, e_h, peak) in enumerate(spans):
        st_dt = start_time_utc + timedelta(hours=s_h) if start_time_utc else None
        et_dt = start_time_utc + timedelta(hours=e_h) if start_time_utc else None
        episodes.append(
            TrueEpisode(
                episode_id=f"zone_{zone_id}_cascade_ep{idx}",
                entity_type="zone_cascade",
                entity_id=zone_id,
                level="CRITICAL",
                start_hour=s_h,
                end_hour=e_h,
                peak_value=peak,
                start_time=st_dt,
                end_time=et_dt,
                details={"systems_critical_peak": int(peak), "min_systems_required": min_systems},
            )
        )
    return episodes


def extract_city_cascade_episodes(
    zone_cascade_masks: Dict[str, List[bool] | np.ndarray],
    num_zones: int,
    city_zone_fraction: float = 0.20,
    merge_gap_hours: float = 6.0,
    start_time_utc: Optional[datetime] = None,
) -> List[TrueEpisode]:
    """Extract city-level cascade episodes.

    Definition: At least city_zone_fraction of zones are simultaneously cascade-critical.
    """
    if not zone_cascade_masks or num_zones <= 0:
        return []

    min_len = min(len(m) for m in zone_cascade_masks.values())
    if min_len == 0:
        return []

    stacked = np.stack([np.asarray(m[:min_len], dtype=bool) for m in zone_cascade_masks.values()], axis=0)
    simultaneous_zones = np.sum(stacked, axis=0)  # shape (min_len,)
    zone_fraction = simultaneous_zones / float(num_zones)
    mask = zone_fraction >= city_zone_fraction
    hours = np.arange(min_len, dtype=float)

    spans = extract_episodes_from_binary_mask(
        mask=mask,
        hours=hours,
        values=zone_fraction,
        merge_gap_hours=merge_gap_hours,
    )

    episodes: List[TrueEpisode] = []
    for idx, (s_h, e_h, peak) in enumerate(spans):
        st_dt = start_time_utc + timedelta(hours=s_h) if start_time_utc else None
        et_dt = start_time_utc + timedelta(hours=e_h) if start_time_utc else None
        episodes.append(
            TrueEpisode(
                episode_id=f"city_cascade_ep{idx}",
                entity_type="city",
                entity_id="city",
                level="CRITICAL",
                start_hour=s_h,
                end_hour=e_h,
                peak_value=peak,
                start_time=st_dt,
                end_time=et_dt,
                details={"peak_zone_fraction": float(peak), "required_fraction": city_zone_fraction},
            )
        )
    return episodes
