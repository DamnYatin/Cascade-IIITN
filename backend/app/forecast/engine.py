"""ForecastEngine orchestrator.

Consumes strictly a StreamView (observations with arrival_time <= clock_time).
Never reads future data, synth ground truth, or evaluation label files (R1, R2).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np

from backend.app.forecast.aggregate import aggregate_rollouts
from backend.app.forecast.calibrate import Calibrator, IdentityCalibrator
from backend.app.forecast.config import ForecastConfig, load_forecast_config
from backend.app.forecast.drift import DriftEvent, make_drift_detector
from backend.app.forecast.estimator import NodeStateEstimator
from backend.app.forecast.features import (
    CausalExogenousFeatureBuilder,
    CausalStressNormalizer,
    get_city_nodes,
)
from backend.app.forecast.learner import DependencyLearner, ForecastModel
from backend.app.forecast.ledger import EvidenceLedger
from backend.app.forecast.mapper import RiskStateMapper
from backend.app.forecast.outlook import PersistenceDecayOutlook, RainOutlook
from backend.app.forecast.records import ForecastSnapshot
from backend.app.forecast.rollout import NoiseBank, cascade_rollout
from backend.app.forecast.trust import SourceTrustManager
from backend.app.replay.stream import StreamView
from backend.app.schemas import CityConfig, Observation, RiskState, SourceKind


class ForecastEngine:
    """Orchestrates causal streaming data ingestion, state estimation, online learning,

    and probabilistic Monte Carlo cascade forecasting.
    """

    def __init__(
        self,
        city_config: CityConfig,
        forecast_config: Optional[ForecastConfig] = None,
        rain_outlook: Optional[RainOutlook] = None,
        calibrator: Optional[Calibrator] = None,
        global_seed: int = 42,
        anchor_mode: str = "off",
    ):
        self.city_config = city_config
        self.forecast_config = forecast_config or load_forecast_config()
        if self.forecast_config.ablation.persistence_outlook_only:
            self.rain_outlook = PersistenceDecayOutlook()
        else:
            self.rain_outlook = rain_outlook or PersistenceDecayOutlook()
        self.calibrator = calibrator or IdentityCalibrator()
        self.global_seed = int(global_seed)
        self.anchor_mode = anchor_mode

        # Config hash for snapshot
        cfg_str = f"{city_config.city_id}:{self.forecast_config.step_hours}:{self.forecast_config.rollouts}"
        self.config_hash = hashlib.sha256(cfg_str.encode("utf-8")).hexdigest()[:16]

        # 1. Causal Normalization & Features
        self.normalizer = CausalStressNormalizer(city_config)
        self.exogenous_builder = CausalExogenousFeatureBuilder(city_config)

        # 2. Evidence Ledger & Trust
        self.ledger = EvidenceLedger()
        self.trust_manager = SourceTrustManager(self.forecast_config.trust)
        if self.forecast_config.ablation.no_source_trust:
            self.trust_manager.get_trust = lambda source: 1.0  # type: ignore
            self.trust_manager.is_outlier = lambda *args, **kwargs: False  # type: ignore

        # 3. State Estimator
        self.estimator = NodeStateEstimator(
            city_config=city_config,
            forecast_config=self.forecast_config,
            trust_manager=self.trust_manager,
            normalizer=self.normalizer,
            ledger=self.ledger,
        )

        # 4. Online Dependency Learner
        self.learner = DependencyLearner(
            city_config=city_config,
            learner_config=self.forecast_config.learner,
            candidate_lags=self.forecast_config.candidate_lags_hours,
        )

        # 5. Drift Detectors per node
        self._drift_detectors = {
            node: make_drift_detector(self.forecast_config.drift)
            for node in self.estimator.nodes
        }
        self._boosted_nodes: Dict[str, int] = {}  # node -> remaining boost hours
        self._recent_drift_events: List[DriftEvent] = []

        # 6. Risk-State Mapper
        self.mapper = RiskStateMapper(
            config=self.forecast_config.mapper,
            calibrator=self.calibrator,
        )

        # History of past step beliefs for RLS learning (node -> datetime -> mean)
        self._past_beliefs: Dict[str, Dict[datetime, float]] = {n: {} for n in self.estimator.nodes}
        # Ingested observation tracking
        self._ingested_obs_ids: Set[str] = set()
        self._obs_count_real: int = 0
        self._obs_count_simulated: int = 0

    def step(
        self,
        clock_time: datetime,
        stream_view: StreamView,
        enable_trace: bool = False,
    ) -> ForecastSnapshot:
        """Advance forecaster clock to clock_time, process available observations, and issue snapshot."""
        # 1. Filter newly released observations from stream_view (arrival_time <= clock_time)
        if hasattr(stream_view, "set_clock_time"):
            stream_view.set_clock_time(clock_time)
            available = stream_view.released()
        elif hasattr(stream_view, "release_until"):
            available = stream_view.release_until(clock_time)
        elif hasattr(stream_view, "released"):
            available = stream_view.released()
        else:
            available = list(stream_view)

        new_obs: List[Observation] = []
        for o in available:
            if o.obs_id not in self._ingested_obs_ids:
                self._ingested_obs_ids.add(o.obs_id)
                new_obs.append(o)
                if o.source_kind == SourceKind.REAL:
                    self._obs_count_real += 1
                else:
                    self._obs_count_simulated += 1

        # Sort observations by arrival_time ascending
        new_obs.sort(key=lambda o: (o.arrival_time, o.event_time))

        # 2. Ingest observations into features and rain outlook
        for o in new_obs:
            self.exogenous_builder.ingest(o)
            self.normalizer.update_history(o)
            if hasattr(self.rain_outlook, "ingest"):
                self.rain_outlook.ingest(o)

        # 3. Kalman state estimator predict & update
        self.estimator.predict_step(clock_time)
        self.estimator.ingest_observations(new_obs, clock_time)

        # Record current estimated mean
        for node, st in self.estimator.states.items():
            self._past_beliefs[node][clock_time] = st.mean

        # 4. Online learning update for target at clock_time (1-hour ahead learning schedule)
        # Learning target is state at clock_time, conditioned on features at clock_time - 1h
        prev_t = clock_time - timedelta(hours=self.forecast_config.step_hours)
        hours_since_start = (clock_time - self.city_config.start_time_utc).total_seconds() / 3600.0
        is_burn_in = hours_since_start < self.forecast_config.burn_in_hours

        # Decay boost hours
        for b_node in list(self._boosted_nodes.keys()):
            self._boosted_nodes[b_node] -= 1
            if self._boosted_nodes[b_node] <= 0:
                del self._boosted_nodes[b_node]

        if prev_t in self._past_beliefs[self.estimator.nodes[0]]:
            for node, st in self.estimator.states.items():
                if st.unobserved:
                    continue

                zone = node.split(":")[0]
                exo_feats, _ = self.exogenous_builder.get_features(zone, prev_t)

                # Assemble feature values at prev_t
                feats: Dict[str, float] = {}
                for other_n in self.estimator.nodes:
                    for lag in self.forecast_config.candidate_lags_hours:
                        lag_t = clock_time - timedelta(hours=lag)
                        if lag_t in self._past_beliefs[other_n]:
                            feats[f"{other_n}@-{lag}h"] = self._past_beliefs[other_n][lag_t]

                feats[f"{zone}:rain_1h"] = exo_feats.get("rain_1h", 0.0) / 100.0 if not np.isnan(exo_feats.get("rain_1h", 0.0)) else 0.0
                feats[f"{zone}:saturation_gain"] = exo_feats.get("saturation_gain", 0.0) / 100.0 if not np.isnan(exo_feats.get("saturation_gain", 0.0)) else 0.0

                target_stress = st.mean
                boost_f = self.forecast_config.drift.forgetting_during_boost if node in self._boosted_nodes else None

                should_learn = True
                if self.forecast_config.ablation.prior_only:
                    should_learn = False
                elif self.forecast_config.ablation.static_graph and not is_burn_in:
                    should_learn = False

                if should_learn:
                    # Record learning update (R3 strictly checked: clock_time >= clock_time)
                    err = self.learner.record_update(
                        node=node,
                        feature_vals=feats,
                        target_stress=target_stress,
                        target_time=clock_time,
                        clock_time=clock_time,
                        boost_forgetting=boost_f,
                    )
                else:
                    err = 0.0

                # 5. Drift detector check on standardised prediction error (outside burn-in)
                if not is_burn_in and not self.forecast_config.ablation.static_graph and not self.forecast_config.ablation.prior_only:
                    pred_std = float(np.sqrt(max(1e-6, st.variance)))
                    norm_err = abs(err) / pred_std
                    detector = self._drift_detectors[node]
                    if detector.update(norm_err, clock_time):
                        self._boosted_nodes[node] = self.forecast_config.drift.boost_hours
                        drift_ev = DriftEvent(
                            node=node,
                            time=clock_time,
                            detector=self.forecast_config.drift.method,
                            magnitude=float(norm_err),
                        )
                        self._recent_drift_events.append(drift_ev)

        # 6. Monte Carlo cascade rollout
        current_beliefs = {n: (st.mean, st.variance) for n, st in self.estimator.states.items()}
        forward_model = self.learner.get_model()

        # Sample rain outlook paths per zone
        zone_ids = [z.id for z in self.city_config.zones]
        noise_bank = NoiseBank(
            global_seed=self.global_seed,
            issue_time=clock_time,
            n_rollouts=self.forecast_config.rollouts,
            n_nodes=len(self.estimator.nodes),
            horizon=max(self.forecast_config.horizons_hours),
        )

        rain_outlook_samples: Dict[str, np.ndarray] = {}
        for z in zone_ids:
            rain_outlook_samples[z] = self.rain_outlook.sample(
                zone=z,
                issue_time=clock_time,
                horizon_hours=max(self.forecast_config.horizons_hours),
                n=self.forecast_config.rollouts,
                rng=noise_bank.outlook_rng,
            )

        rollout_res = cascade_rollout(
            model=forward_model,
            initial_beliefs=current_beliefs,
            horizon=max(self.forecast_config.horizons_hours),
            n_rollouts=self.forecast_config.rollouts,
            noise_bank=noise_bank,
            global_seed=self.global_seed,
            issue_time=clock_time,
            stress_levels=self.forecast_config.stress_levels,
            rain_outlook_by_zone=rain_outlook_samples,
            enable_trace=enable_trace,
        )

        self.last_rollout_results = rollout_res
        self.last_noise_bank = noise_bank
        self.last_forward_model = forward_model
        self.last_initial_beliefs = current_beliefs
        self.last_rain_outlook_samples = rain_outlook_samples
        self.last_clock_time = clock_time

        # 7. Aggregate rollouts
        agg = aggregate_rollouts(
            results=rollout_res,
            city_config=self.city_config,
            horizons=self.forecast_config.horizons_hours,
            stress_levels=self.forecast_config.stress_levels,
            aggregation_config=self.forecast_config.aggregation,
        )

        # 8. Risk State Mapping with Hysteresis
        zone_risk_states: Dict[str, RiskState] = {}
        for z in zone_ids:
            p_crit_72 = agg.zone_probabilities.get(z, {}).get(72, {}).get("CRITICAL", 0.0)
            p_crit_12 = agg.zone_probabilities.get(z, {}).get(12, {}).get("CRITICAL", 0.0)
            z_state, _ = self.mapper.update(z, p_crit_72, p_crit_12)
            zone_risk_states[z] = z_state

        city_p_crit_72 = agg.city_probabilities.get(72, {}).get("CRITICAL", 0.0)
        city_p_crit_12 = agg.city_probabilities.get(12, {}).get("CRITICAL", 0.0)
        city_state, _ = self.mapper.update("city", city_p_crit_72, city_p_crit_12)

        # 9. Format Evidence Quality & Provenance
        eq_map: Dict[str, float] = {}
        for z in zone_ids:
            z_eqs = [st.evidence_quality for n, st in self.estimator.states.items() if n.startswith(f"{z}:")]
            eq_map[z] = float(np.mean(z_eqs)) if z_eqs else 0.5
        eq_map["city"] = float(np.mean(list(eq_map.values())))

        total_obs = max(1, self._obs_count_real + self._obs_count_simulated)
        pct_real = float(self._obs_count_real / total_obs * 100.0)
        pct_sim = float(self._obs_count_simulated / total_obs * 100.0)

        sim_systems = [s.id for s in self.city_config.systems if s.id != "river_embankment"]
        provenance_mix = {
            "real_percentage": pct_real,
            "simulated_percentage": pct_sim,
            "simulated_systems": sorted(sim_systems),
            "real_streams": ["rain", "soil_moisture"],
        }

        disc_str = (
            "PROVENANCE DISCLOSURE: Real inputs are rainfall and soil moisture. "
            "Downstream systems (power, transport, comms, health, emergency response) are SIMULATED."
        )
        if self.anchor_mode == "on":
            disc_str += " ANCHOR MODE ON: generator outputs tagged with anchored=true."

        # Format cascade summary dicts
        formatted_cascade: List[Dict[str, Any]] = []
        for stg in agg.city_cascade_summary:
            formatted_cascade.append(
                {
                    "stage": stg.stage_index,
                    "node": stg.node,
                    "probability": round(stg.probability, 4),
                    "eta_p10": stg.eta_p10,
                    "eta_p50": stg.eta_p50,
                    "eta_p90": stg.eta_p90,
                    "dominant_parent": stg.dominant_parent,
                }
            )

        # Active top edges from EdgeBook
        active_edges = self.learner.edge_book.snapshot()
        top_edges_list = [
            {
                "u": str(e.u),
                "v": str(e.v),
                "lag_hours": e.lag_hours,
                "weight": round(e.weight, 4),
                "confidence": round(e.confidence, 4),
            }
            for e in active_edges[:10]
        ]

        recent_changes = [
            {
                "time": ch.time.isoformat(),
                "u": ch.u,
                "v": ch.v,
                "kind": ch.kind,
                "old_weight": round(ch.old_weight, 4),
                "new_weight": round(ch.new_weight, 4),
                "reason": ch.reason,
            }
            for ch in self.learner.edge_book.diff(clock_time - timedelta(hours=6), clock_time)
        ]

        drift_ev_dicts = [
            {
                "node": dev.node,
                "time": dev.time.isoformat(),
                "detector": dev.detector,
                "magnitude": round(dev.magnitude, 4),
            }
            for dev in self._recent_drift_events[-5:]
        ]

        # Format probabilities with string keys for JSON serialization
        city_probs_str = {str(h): agg.city_probabilities[h] for h in self.forecast_config.horizons_hours}
        zone_probs_str = {
            z: {str(h): agg.zone_probabilities.get(z, {}).get(h, {}) for h in self.forecast_config.horizons_hours}
            for z in zone_ids
        }

        is_cal = bool(getattr(self.calibrator, "is_calibrated", False))
        cal_source = str(getattr(self.calibrator, "calibration_source", "none"))

        if is_cal:
            out_city_probs = {
                str(h): {
                    st: self.calibrator.calibrate(val) if st != "NORMAL" else 1.0
                    for st, val in agg.city_probabilities[h].items()
                }
                for h in self.forecast_config.horizons_hours
            }
            out_zone_probs = {
                z: {
                    str(h): {
                        st: self.calibrator.calibrate(val) if st != "NORMAL" else 1.0
                        for st, val in agg.zone_probabilities.get(z, {}).get(h, {}).items()
                    }
                    for h in self.forecast_config.horizons_hours
                }
                for z in zone_ids
            }
        else:
            out_city_probs = city_probs_str
            out_zone_probs = zone_probs_str

        is_oracle_active = getattr(self.rain_outlook, "is_oracle", False)

        snapshot = ForecastSnapshot(
            issued_at=clock_time,
            city_id=self.city_config.city_id,
            city_risk_state=city_state,
            city_probabilities=out_city_probs,
            zone_risk_states=zone_risk_states,
            zone_probabilities=out_zone_probs,
            evidence_quality=eq_map,
            top_edges=top_edges_list,
            edge_changes=recent_changes,
            drift_events=drift_ev_dicts,
            cascade_summary=formatted_cascade,
            provenance_mix=provenance_mix,
            disclosure_string=disc_str,
            burn_in=is_burn_in,
            calibrated=is_cal,
            calibration_source=cal_source,
            oracle=is_oracle_active,
            config_hash=self.config_hash,
        )
        self.last_snapshot = snapshot
        return snapshot
