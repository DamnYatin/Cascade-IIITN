"""Alert-run evaluation and episode attribution logic with hysteresis.

Rules:
  - Alert run starts when score >= tau for k consecutive steps.
  - Alert run ends when score < tau_low for k_off consecutive steps.
  - Attribution:
      * An alert run is a HIT for the next true episode (same entity and level)
        that starts within (0, H_hit] hours after the run's first alert step (H_hit = 72h default).
      * Lead time = episode start - first alert time.
      * A run with no qualifying episode in (0, H_hit] is a FALSE ALARM.
      * An episode with no preceding run inside the window is a MISS.
      * An alert that starts after the episode has already started counts as LATE (negative lead)
        and a miss for POD purposes (reported separately).
      * One run can serve at most one episode; one episode is credited to the earliest qualifying run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from backend.app.eval.events import TrueEpisode


@dataclass
class AlertStep:
    step_index: int
    hour: float
    score: float
    timestamp: Optional[datetime] = None


@dataclass
class AlertRun:
    run_id: str
    entity_id: str
    level: str
    first_alert_hour: float
    end_alert_hour: float
    steps: List[AlertStep] = field(default_factory=list)
    status: str = "unassigned"  # "hit" | "false_alarm" | "late"
    matched_episode_id: Optional[str] = None
    lead_time_hours: Optional[float] = None
    first_alert_time: Optional[datetime] = None


@dataclass
class AttributionResult:
    entity_id: str
    alert_runs: List[AlertRun]
    episodes: List[TrueEpisode]
    hits: List[AlertRun]
    false_alarms: List[AlertRun]
    late_alerts: List[AlertRun]
    missed_episodes: List[TrueEpisode]
    lead_times: List[float]


def detect_alert_runs(
    scores: List[float],
    hours: List[float],
    tau: float = 0.30,
    k: int = 2,
    tau_low: Optional[float] = None,
    k_off: int = 2,
    entity_id: str = "entity",
    level: str = "CRITICAL",
    timestamps: Optional[List[datetime]] = None,
) -> List[AlertRun]:
    """Detect alert runs with hysteresis and consecutive step requirements.

    Args:
        scores: Sequence of forecast probabilities/scores.
        hours: Simulation hour for each step.
        tau: Activation threshold.
        k: Minimum consecutive steps >= tau to trigger an alert run.
        tau_low: Deactivation threshold. If None, tau_low = tau.
        k_off: Minimum consecutive steps < tau_low to terminate an active alert run.
        entity_id: Zone ID, node ID, or 'city'.
        level: Target risk level.
        timestamps: Optional datetime for each step.

    Returns:
        List of AlertRun objects.
    """
    if tau_low is None:
        tau_low = tau

    n = len(scores)
    if n == 0:
        return []

    runs: List[AlertRun] = []
    in_run = False
    consec_high = 0
    consec_low = 0

    current_steps: List[AlertStep] = []
    run_start_step_idx = -1
    run_start_hour = 0.0
    run_start_time: Optional[datetime] = None

    for i in range(n):
        s = float(scores[i])
        h = float(hours[i])
        t = timestamps[i] if timestamps else None
        step_obj = AlertStep(step_index=i, hour=h, score=s, timestamp=t)

        if not in_run:
            if s >= tau:
                consec_high += 1
                if consec_high == 1:
                    # Potential start candidate
                    run_start_step_idx = i
                    run_start_hour = h
                    run_start_time = t
                if consec_high >= k:
                    # Run triggers! First alert time is the step where k was reached
                    in_run = True
                    consec_low = 0
                    current_steps = [
                        AlertStep(
                            step_index=j,
                            hour=float(hours[j]),
                            score=float(scores[j]),
                            timestamp=timestamps[j] if timestamps else None,
                        )
                        for j in range(run_start_step_idx, i + 1)
                    ]
            else:
                consec_high = 0
                run_start_step_idx = -1
        else:
            # Currently inside an active alert run
            current_steps.append(step_obj)
            if s < tau_low:
                consec_low += 1
                if consec_low >= k_off:
                    # Run ends
                    in_run = False
                    consec_high = 0
                    consec_low = 0
                    end_h = h
                    runs.append(
                        AlertRun(
                            run_id=f"{entity_id}_{level}_run{len(runs)}",
                            entity_id=entity_id,
                            level=level,
                            first_alert_hour=run_start_hour,
                            end_alert_hour=end_h,
                            steps=current_steps,
                            first_alert_time=run_start_time,
                        )
                    )
                    current_steps = []
            else:
                consec_low = 0

    if in_run and current_steps:
        # Reached end of series while in active run
        runs.append(
            AlertRun(
                run_id=f"{entity_id}_{level}_run{len(runs)}",
                entity_id=entity_id,
                level=level,
                first_alert_hour=run_start_hour,
                end_alert_hour=float(hours[-1]),
                steps=current_steps,
                first_alert_time=run_start_time,
            )
        )

    return runs


def attribute_alerts(
    alert_runs: List[AlertRun],
    episodes: List[TrueEpisode],
    h_hit: float = 72.0,
    entity_id: str = "entity",
) -> AttributionResult:
    """Attribute alert runs to true episodes strictly following evaluation rules.

    Rules:
      - Alert run is a hit if true episode starts within (0, h_hit] hours after first alert step.
      - Lead time = episode.start_hour - run.first_alert_hour.
      - If first_alert_hour >= episode.start_hour (and alert run overlaps or starts after episode),
        it is classified as LATE (negative lead time), not a hit.
      - One run can serve at most one episode.
      - One episode is credited to the earliest qualifying run.
      - Episodes with no qualifying run are MISSED.
      - Runs with no qualifying episode in (0, h_hit] are FALSE ALARMS.
    """
    sorted_runs = sorted(alert_runs, key=lambda r: r.first_alert_hour)
    sorted_episodes = sorted(episodes, key=lambda e: e.start_hour)

    hits: List[AlertRun] = []
    false_alarms: List[AlertRun] = []
    late_alerts: List[AlertRun] = []
    lead_times: List[float] = []

    used_run_ids: set[str] = set()
    credited_episodes: set[str] = set()

    # For each true episode in chronological order, find the earliest qualifying run
    for ep in sorted_episodes:
        candidate_runs: List[AlertRun] = []
        for r in sorted_runs:
            if r.run_id in used_run_ids:
                continue

            lead = ep.start_hour - r.first_alert_hour
            if 0 < lead <= h_hit:
                candidate_runs.append(r)

        if candidate_runs:
            # Earliest qualifying run gets the credit
            best_run = min(candidate_runs, key=lambda r: r.first_alert_hour)
            best_lead = ep.start_hour - best_run.first_alert_hour
            best_run.status = "hit"
            best_run.matched_episode_id = ep.episode_id
            best_run.lead_time_hours = best_lead

            used_run_ids.add(best_run.run_id)
            credited_episodes.add(ep.episode_id)
            hits.append(best_run)
            lead_times.append(best_lead)

    # Now evaluate remaining unused runs
    for r in sorted_runs:
        if r.run_id in used_run_ids:
            continue

        # Check if this run was late for an episode (i.e. started during or after an episode)
        is_late = False
        for ep in sorted_episodes:
            # If alert started after episode start, but before episode end + some small tolerance
            if ep.start_hour <= r.first_alert_hour < ep.end_hour + 6.0:
                is_late = True
                r.status = "late"
                r.matched_episode_id = ep.episode_id
                r.lead_time_hours = ep.start_hour - r.first_alert_hour
                late_alerts.append(r)
                used_run_ids.add(r.run_id)
                break

        if not is_late:
            r.status = "false_alarm"
            r.lead_time_hours = None
            false_alarms.append(r)

    missed_episodes = [ep for ep in sorted_episodes if ep.episode_id not in credited_episodes]

    return AttributionResult(
        entity_id=entity_id,
        alert_runs=sorted_runs,
        episodes=sorted_episodes,
        hits=hits,
        false_alarms=false_alarms,
        late_alerts=late_alerts,
        missed_episodes=missed_episodes,
        lead_times=lead_times,
    )
