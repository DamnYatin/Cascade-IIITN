"""Per-node scalar linear-Gaussian state estimator with late-arrival rewinding.

Architecture:
  - Linear-Gaussian (Kalman) filtering on continuous stress s in [0, 1].
  - Trust-tempered measurement updates: variance inflated by 1 / trust.
  - Precision-weighted fusion for multi-source observations in the same hour.
  - Missing data: predict-only with process noise growing uncertainty.
  - Late-arrival handling: re-filters from earliest affected hour within reorder_window_hours.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
import numpy as np

from backend.app.forecast.config import ForecastConfig
from backend.app.forecast.features import CausalStressNormalizer
from backend.app.forecast.ledger import EvidenceItem, EvidenceLedger
from backend.app.forecast.trust import SourceTrustManager, compute_evidence_quality
from backend.app.schemas import CityConfig, Observation, QualityFlag


@dataclass
class NodeState:
    node: str
    mean: float
    variance: float
    last_obs_time: Optional[datetime] = None
    evidence_ids: List[str] = field(default_factory=list)
    unobserved: bool = False
    evidence_quality: float = 1.0


@dataclass
class HistoricStep:
    time: datetime
    predicted_mean: float
    predicted_var: float
    updated_mean: float
    updated_var: float
    observations: List[Observation] = field(default_factory=list)


class NodeStateEstimator:
    """Manages continuous state estimation across all nodes in a city."""

    def __init__(
        self,
        city_config: CityConfig,
        forecast_config: ForecastConfig,
        trust_manager: SourceTrustManager,
        normalizer: CausalStressNormalizer,
        ledger: EvidenceLedger,
        process_noise: float = 0.015,
        base_meas_variance: float = 0.01,
    ):
        self.city_config = city_config
        self.forecast_config = forecast_config
        self.trust_manager = trust_manager
        self.normalizer = normalizer
        self.ledger = ledger
        self.process_noise = process_noise
        self.base_meas_variance = base_meas_variance
        self.reorder_window = timedelta(hours=forecast_config.reorder_window_hours)

        # Identify all nodes
        self.nodes: List[str] = []
        system_ids = [s.id for s in city_config.systems]
        for z in city_config.zones:
            z_sys = z.systems if z.systems is not None else system_ids
            for s in z_sys:
                self.nodes.append(f"{z.id}:{s}")

        # Check which nodes have streams
        stream_systems = {s.system for s in city_config.streams}
        self.unobserved_nodes = {
            node for node in self.nodes if node.split(":")[1] not in stream_systems
        }

        # Current state per node: NodeState
        self.states: Dict[str, NodeState] = {}
        for node in self.nodes:
            is_unobs = node in self.unobserved_nodes
            self.states[node] = NodeState(
                node=node,
                mean=0.15,  # quiet city baseline stress
                variance=0.10 if is_unobs else 0.05,
                unobserved=is_unobs,
                evidence_quality=0.0 if is_unobs else 0.5,
            )

        # Ring buffer of observation history per node: event_time -> list[Observation]
        self._obs_buffer: Dict[str, Dict[datetime, List[Observation]]] = defaultdict(lambda: defaultdict(list))
        # Step history for rewinding: node -> dict[datetime, HistoricStep]
        self._step_history: Dict[str, Dict[datetime, HistoricStep]] = defaultdict(dict)

    def predict_step(self, clock_time: datetime) -> None:
        """Execute one Kalman predict step for all nodes (e.g. at hourly tick)."""
        for node, st in self.states.items():
            if st.unobserved:
                # Grow variance for unobserved node up to ceiling
                st.variance = min(0.30, st.variance + self.process_noise)
                st.evidence_quality = 0.0
                continue

            # Persistence model with slight mean reversion to baseline
            pred_mean = 0.96 * st.mean + 0.04 * 0.15
            pred_var = min(0.30, st.variance + self.process_noise)

            st.mean = float(np.clip(pred_mean, 0.0, 1.0))
            st.variance = float(pred_var)

            # Record step in history
            self._step_history[node][clock_time] = HistoricStep(
                time=clock_time,
                predicted_mean=st.mean,
                predicted_var=st.variance,
                updated_mean=st.mean,
                updated_var=st.variance,
            )

    def ingest_observations(
        self,
        observations: List[Observation],
        clock_time: datetime,
    ) -> None:
        """Ingest observations arriving at clock_time.

        Handles out-of-order / late observations by checking if event_time < clock_time.
        If late within reorder_window, triggers a deterministic rewound refilter.
        """
        if not observations:
            return

        # Group by node
        grouped: Dict[str, List[Observation]] = defaultdict(list)
        for obs in observations:
            node = obs.node_id or f"{obs.zone}:{obs.system}"
            if node in self.states:
                grouped[node].append(obs)

        for node, obs_list in grouped.items():
            earliest_late: Optional[datetime] = None

            for obs in obs_list:
                ev_t = obs.event_time
                self._obs_buffer[node][ev_t].append(obs)

                if ev_t < clock_time:
                    # Late arrival
                    if ev_t >= clock_time - self.reorder_window:
                        if earliest_late is None or ev_t < earliest_late:
                            earliest_late = ev_t
                    else:
                        # Beyond reorder window: accept to ledger without rewinding
                        stress, norm_m = self.normalizer.normalize(obs, clock_time)
                        self.ledger.record_evidence(
                            EvidenceItem(
                                obs_id=obs.obs_id,
                                source=obs.source,
                                node=node,
                                event_time=obs.event_time,
                                arrival_time=obs.arrival_time,
                                trust=self.trust_manager.get_trust(obs.source),
                                weight=0.0,
                                gated=True,  # Gated from state update due to expired window
                                stress_value=stress,
                                normalization=norm_m,
                                quality_flags=[str(f) for f in obs.quality_flags] + ["expired_reorder_window"],
                            )
                        )

            if earliest_late is not None:
                # Rewind and refilter this node from earliest_late to clock_time
                self._refilter_node(node, earliest_late, clock_time)
            else:
                # Normal update at clock_time
                current_obs = self._obs_buffer[node].get(clock_time, [])
                if current_obs:
                    self._update_node_at_time(node, clock_time, current_obs)

    def _update_node_at_time(
        self,
        node: str,
        t: datetime,
        obs_list: List[Observation],
    ) -> None:
        """Update Kalman filter for node using observations for timestamp t."""
        st = self.states[node]
        if st.unobserved:
            return

        # Separate citizen reports from sensor observations
        sensors: List[Observation] = []
        citizen_reports: List[Observation] = []
        for o in obs_list:
            if QualityFlag.CITIZEN_REPORT in o.quality_flags or "citizen" in o.source.lower():
                citizen_reports.append(o)
            else:
                sensors.append(o)

        # 1. Process sensors
        valid_updates: List[Tuple[float, float, str, str, str]] = []  # (stress, variance, obs_id, source, norm_method)
        peer_values: List[float] = []

        # First compute normalized stresses
        for o in sensors:
            stress, norm_m = self.normalizer.normalize(o, t)
            peer_values.append(stress)

        for o in sensors:
            stress, norm_m = self.normalizer.normalize(o, t)
            source = o.source
            trust = self.trust_manager.get_trust(source)

            # Flatline check
            if self.trust_manager.check_flatline(node, source, stress, t):
                self.ledger.record_evidence(
                    EvidenceItem(
                        obs_id=o.obs_id,
                        source=source,
                        node=node,
                        event_time=o.event_time,
                        arrival_time=o.arrival_time,
                        trust=trust,
                        weight=0.0,
                        gated=True,
                        stress_value=stress,
                        normalization=norm_m,
                        quality_flags=[str(f) for f in o.quality_flags] + ["flatline_detected"],
                    )
                )
                continue

            # Outlier check
            pred_std = float(np.sqrt(max(1e-6, st.variance)))
            is_outlier = self.trust_manager.is_outlier(stress, st.mean, pred_std, peer_values)
            if is_outlier:
                self.ledger.record_evidence(
                    EvidenceItem(
                        obs_id=o.obs_id,
                        source=source,
                        node=node,
                        event_time=o.event_time,
                        arrival_time=o.arrival_time,
                        trust=trust,
                        weight=0.0,
                        gated=True,
                        stress_value=stress,
                        normalization=norm_m,
                        quality_flags=[str(f) for f in o.quality_flags] + ["gated_outlier"],
                    )
                )
                # Penalize trust for outlier
                self.trust_manager.update_trust(source, agreed=False, weight=1.0)
                continue

            # Valid observation: tempered variance = base_variance / trust
            tempered_var = self.base_meas_variance / max(0.01, trust)
            valid_updates.append((stress, tempered_var, o.obs_id, source, norm_m))

        # If outliers were gated while peers agreed with model, reward valid peers
        if len(sensors) >= 2 and len(valid_updates) >= 1:
            for (v_stress, _, _, v_src, _) in valid_updates:
                if v_src != "citizen_report_cluster" and abs(v_stress - st.mean) < 0.25:
                    self.trust_manager.update_trust(v_src, agreed=True, weight=1.0)

        # 2. Process citizen reports
        if citizen_reports:
            mean_c, w_c, admitted = self.trust_manager.process_citizen_reports(
                citizen_reports, sensor_stress=st.mean
            )
            if admitted and mean_c is not None:
                rep_var = self.base_meas_variance / max(0.01, w_c)
                rep_id = citizen_reports[0].obs_id
                valid_updates.append((mean_c, rep_var, rep_id, "citizen_report_cluster", "reports"))
                for cr in citizen_reports:
                    self.ledger.record_evidence(
                        EvidenceItem(
                            obs_id=cr.obs_id,
                            source=cr.source,
                            node=node,
                            event_time=cr.event_time,
                            arrival_time=cr.arrival_time,
                            trust=w_c,
                            weight=w_c,
                            gated=False,
                            stress_value=mean_c,
                            normalization="citizen_aggregate",
                            quality_flags=[str(f) for f in cr.quality_flags],
                        )
                    )
            else:
                for cr in citizen_reports:
                    self.ledger.record_evidence(
                        EvidenceItem(
                            obs_id=cr.obs_id,
                            source=cr.source,
                            node=node,
                            event_time=cr.event_time,
                            arrival_time=cr.arrival_time,
                            trust=0.05,
                            weight=0.0,
                            gated=True,
                            stress_value=float(cr.value),
                            normalization="citizen_spam",
                            quality_flags=[str(f) for f in cr.quality_flags] + ["citizen_spam_gated"],
                        )
                    )

        if not valid_updates:
            # Predict only
            return

        # 3. Fuse valid updates by precision weighting
        precisions = [1.0 / var for (_, var, _, _, _) in valid_updates]
        total_prec = sum(precisions)
        fused_stress = sum(val * prec for (val, _, _, _, _), prec in zip(valid_updates, precisions)) / total_prec
        fused_var = 1.0 / total_prec

        # Update source trust if multiple independent sources
        unique_sources = {src for (_, _, _, src, _) in valid_updates if src != "citizen_report_cluster"}
        if len(unique_sources) >= 2:
            for (val, _, _, src, _) in valid_updates:
                if src != "citizen_report_cluster":
                    diff = abs(val - fused_stress)
                    agreed = diff < 0.20
                    self.trust_manager.update_trust(src, agreed=agreed, weight=1.0)

        # Kalman measurement update
        prior_mean = st.mean
        prior_var = st.variance
        gain = prior_var / (prior_var + fused_var)
        updated_mean = prior_mean + gain * (fused_stress - prior_mean)
        updated_var = (1.0 - gain) * prior_var

        st.mean = float(np.clip(updated_mean, 0.0, 1.0))
        st.variance = float(max(1e-5, updated_var))
        st.last_obs_time = t

        # Record evidence in ledger
        for (stress_val, _, obs_id, source, norm_m) in valid_updates:
            if source != "citizen_report_cluster":
                trust = self.trust_manager.get_trust(source)
                self.ledger.record_evidence(
                    EvidenceItem(
                        obs_id=obs_id,
                        source=source,
                        node=node,
                        event_time=t,
                        arrival_time=t,
                        trust=trust,
                        weight=float(gain),
                        gated=False,
                        stress_value=stress_val,
                        normalization=norm_m,
                    )
                )

        # Update evidence quality
        freshness = 1.0
        mean_trust = float(np.mean([self.trust_manager.get_trust(src) for src in unique_sources])) if unique_sources else 0.5
        agreement = 1.0 - float(np.clip(np.std([v for (v, _, _, _, _) in valid_updates]) * 2.0, 0.0, 1.0)) if len(valid_updates) > 1 else 0.8
        st.evidence_quality = compute_evidence_quality(freshness, mean_trust, agreement, unobserved=False)
        st.evidence_ids = self.ledger.evidence_ids_for_prediction(node, t, window_hours=6.0)

    def _refilter_node(
        self,
        node: str,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        """Deterministic rewound refiltering from start_time to end_time."""
        st = self.states[node]
        if st.unobserved:
            return

        # Find initial state at start_time - 1h if available, else baseline
        prev_t = start_time - timedelta(hours=self.forecast_config.step_hours)
        if prev_t in self._step_history[node]:
            step_prev = self._step_history[node][prev_t]
            current_mean = step_prev.updated_mean
            current_var = step_prev.updated_var
        else:
            current_mean = 0.15
            current_var = 0.05

        # Replay each hour up to end_time
        cur = start_time
        while cur <= end_time:
            # Predict
            pred_mean = 0.96 * current_mean + 0.04 * 0.15
            pred_var = min(0.30, current_var + self.process_noise)
            st.mean = float(np.clip(pred_mean, 0.0, 1.0))
            st.variance = float(pred_var)

            # Update
            obs_at_t = self._obs_buffer[node].get(cur, [])
            if obs_at_t:
                self._update_node_at_time(node, cur, obs_at_t)

            # Record in history
            self._step_history[node][cur] = HistoricStep(
                time=cur,
                predicted_mean=pred_mean,
                predicted_var=pred_var,
                updated_mean=st.mean,
                updated_var=st.variance,
            )

            current_mean = st.mean
            current_var = st.variance
            cur += timedelta(hours=self.forecast_config.step_hours)
