"""Online sparse dependency learner with weak prior shrinkage, EdgeBook, and forward model.

Dynamics:
  s_i(t+1) = clip( a_i + rho_i * s_i(t)
                   + sum_{j, tau} w_{ji, tau} * s_j(t+1-tau)
                   + sum_k beta_k * f_k(t)
                   + eps_i, 0, 1 ), eps_i ~ N(0, sigma_i^2)

Key rules:
  - R3 Label maturity: update only when clock_time >= target_time (t + 1h).
  - Shrinkage toward weak domain prior; data can override it.
  - Candidate parents restricted to same-zone, adjacent-zone, upstream river links, prior.
  - Hysteresis on edges to prevent flickering.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np

from backend.app.forecast.config import LearnerConfig
from backend.app.forecast.drift import DriftEvent
from backend.app.schemas import CityConfig, Edge, NodeId


@dataclass
class EdgeChange:
    time: datetime
    u: str
    v: str
    kind: str  # "appeared", "disappeared", "weight_changed"
    old_weight: float
    new_weight: float
    reason: str


@dataclass
class EdgeRecord:
    edge: Edge
    status: str  # "active", "decayed"
    first_seen: datetime
    last_updated: datetime
    active_steps: int = 0
    inactive_steps: int = 0


class EdgeBook:
    """Maintains active edges, confidence, and timestamped change log."""

    def __init__(self, hysteresis_steps: int = 6):
        self.hysteresis_steps = hysteresis_steps
        self._edges: Dict[Tuple[str, str], EdgeRecord] = {}
        self.change_log: List[EdgeChange] = []

    def update_edge(
        self,
        u: str,
        v: str,
        lag_hours: float,
        weight: float,
        confidence: float,
        clock_time: datetime,
        is_significant: bool,
    ) -> None:
        key = (u, v)
        if key not in self._edges:
            if not is_significant:
                return
            rec = EdgeRecord(
                edge=Edge(
                    u=NodeId(u),
                    v=NodeId(v),
                    lag_hours=lag_hours,
                    weight=float(weight),
                    confidence=float(confidence),
                    last_updated=clock_time,
                ),
                status="pending_active",
                first_seen=clock_time,
                last_updated=clock_time,
                active_steps=1,
            )
            self._edges[key] = rec
            if rec.active_steps >= self.hysteresis_steps:
                rec.status = "active"
                self.change_log.append(EdgeChange(clock_time, u, v, "appeared", 0.0, weight, "hysteresis_satisfied"))
            return

        rec = self._edges[key]
        old_w = rec.edge.weight

        if is_significant:
            rec.active_steps += 1
            rec.inactive_steps = 0
            if rec.status != "active" and rec.active_steps >= self.hysteresis_steps:
                rec.status = "active"
                self.change_log.append(EdgeChange(clock_time, u, v, "appeared", old_w, weight, "activated"))
            elif rec.status == "active" and abs(weight - old_w) > 0.10:
                self.change_log.append(EdgeChange(clock_time, u, v, "weight_changed", old_w, weight, "weight_drift"))

            # Update edge attributes
            rec.edge = Edge(
                u=NodeId(u),
                v=NodeId(v),
                lag_hours=lag_hours,
                weight=float(weight),
                confidence=float(confidence),
                last_updated=clock_time,
            )
            rec.last_updated = clock_time
        else:
            rec.inactive_steps += 1
            rec.active_steps = 0
            if rec.status == "active" and rec.inactive_steps >= self.hysteresis_steps:
                rec.status = "decayed"
                self.change_log.append(EdgeChange(clock_time, u, v, "disappeared", old_w, 0.0, "decayed"))

    def snapshot(self) -> List[Edge]:
        """Return all currently active edges."""
        return [rec.edge for rec in self._edges.values() if rec.status == "active"]

    def diff(self, t0: datetime, t1: datetime) -> List[EdgeChange]:
        """Return all edge changes between t0 and t1."""
        return [ch for ch in self.change_log if t0 <= ch.time <= t1]


@dataclass
class ForecastModel:
    """Forward dynamics simulation model used by Monte Carlo rollouts."""

    nodes: List[str]
    # node -> intercept a_i
    intercepts: Dict[str, float]
    # node -> autoregressive weight rho_i
    persistence: Dict[str, float]
    # node -> list of (parent_node, lag_hours, weight)
    couplings: Dict[str, List[Tuple[str, float, float]]]
    # node -> list of (feature_name, weight)
    exogenous_weights: Dict[str, List[Tuple[str, float]]]
    # node -> residual std sigma_i
    sigmas: Dict[str, float]

    @classmethod
    def from_edges(
        cls,
        nodes: List[str],
        edges: List[Edge],
        default_persistence: float = 0.85,
        default_sigma: float = 0.05,
    ) -> ForecastModel:
        """Create explicit forecast model for testing or manual specification."""
        intercepts = {n: 0.02 for n in nodes}
        persistence = {n: default_persistence for n in nodes}
        couplings: Dict[str, List[Tuple[str, float, float]]] = {n: [] for n in nodes}
        exogenous: Dict[str, List[Tuple[str, float]]] = {n: [] for n in nodes}
        sigmas = {n: default_sigma for n in nodes}

        for e in edges:
            v = str(e.v)
            u = str(e.u)
            if v in couplings:
                couplings[v].append((u, float(e.lag_hours), float(e.weight)))

        return cls(
            nodes=nodes,
            intercepts=intercepts,
            persistence=persistence,
            couplings=couplings,
            exogenous_weights=exogenous,
            sigmas=sigmas,
        )


class NodeRLS:
    """Online Recursive Least Squares with forgetting and prior shrinkage for node i."""

    def __init__(
        self,
        node: str,
        candidate_features: List[str],
        config: LearnerConfig,
        prior_weights: Optional[Dict[str, float]] = None,
    ):
        self.node = node
        self.features = candidate_features
        self.d = len(candidate_features)
        self.config = config

        # Parameters: theta = [intercept, rho, w_1, ..., beta_1, ...]
        self.theta = np.zeros(self.d, dtype=np.float64)
        # Prior vector theta_0
        self.theta_0 = np.zeros(self.d, dtype=np.float64)
        self.theta_0[1] = 0.85  # Default persistence prior rho = 0.85

        if prior_weights:
            for feat, w in prior_weights.items():
                if feat in self.features:
                    idx = self.features.index(feat)
                    self.theta_0[idx] = w

        # Initialise theta to prior
        self.theta = self.theta_0.copy()

        # Covariance matrix P
        self.P = np.eye(self.d, dtype=np.float64) * 1.0
        self.forgetting = config.forgetting
        self.residual_variance: float = 0.0025  # (0.05)^2

    def update(self, x: np.ndarray, y: float, boost_forgetting: Optional[float] = None) -> float:
        """Update RLS parameters given feature vector x and target y."""
        lam = boost_forgetting if boost_forgetting is not None else self.forgetting

        pred = float(np.dot(x, self.theta))
        err = y - pred

        # P x
        Px = self.P @ x
        denom = lam + float(x @ Px)
        gain = Px / denom

        # Update theta with RLS + gentle shrinkage toward prior theta_0
        self.theta += gain * err
        if self.config.ridge_to_prior > 0.0:
            shrink = 0.001 * self.config.ridge_to_prior
            self.theta = (1.0 - shrink) * self.theta + shrink * self.theta_0

        # Update P
        self.P = (self.P - np.outer(gain, x @ self.P)) / lam

        # Update residual variance
        self.residual_variance = 0.98 * self.residual_variance + 0.02 * (err**2)
        return err


class DependencyLearner:
    """Manages online dependency discovery and forward model updates."""

    def __init__(
        self,
        city_config: CityConfig,
        learner_config: LearnerConfig,
        candidate_lags: List[int],
    ):
        self.city_config = city_config
        self.config = learner_config
        self.candidate_lags = candidate_lags
        self.edge_book = EdgeBook(hysteresis_steps=learner_config.edge_hysteresis_steps)

        # Build candidate features per node
        self._learners: Dict[str, NodeRLS] = {}
        self._build_candidate_models()

        # Update logging for R3 verification: list of (target_time, update_time)
        self.update_log: List[Tuple[datetime, datetime]] = []

    def _build_candidate_models(self) -> None:
        """Construct candidate feature names per node based on network topology."""
        zone_map = {z.id: z for z in self.city_config.zones}
        system_ids = [s.id for s in self.city_config.systems]

        # Prior edges from config
        priors: Dict[str, Dict[str, float]] = {f"{z.id}:{s}": {} for z in self.city_config.zones for s in system_ids}
        for e in self.city_config.domain_prior_edges:
            v = str(e.v)
            u = str(e.u)
            lag = int(round(e.lag_hours))
            feat_name = f"{u}@-{lag}h"
            if v in priors:
                priors[v][feat_name] = float(e.weight)

        for z in self.city_config.zones:
            z_sys = z.systems if z.systems is not None else system_ids
            for s in z_sys:
                node = f"{z.id}:{s}"
                feats = ["intercept", f"{node}@-1h"]

                # 1. Other systems in the same zone
                for other_s in z_sys:
                    if other_s != s:
                        for lag in self.candidate_lags:
                            feats.append(f"{z.id}:{other_s}@-{lag}h")

                # 2. Same system in adjacent zones
                for n_id in z.neighbours:
                    for lag in self.candidate_lags:
                        feats.append(f"{n_id}:{s}@-{lag}h")

                # 3. Upstream river links
                for rl in z.river_links:
                    up_zone = rl["target"]
                    for lag in self.candidate_lags:
                        feats.append(f"{up_zone}:{s}@-{lag}h")

                # 4. Exogenous rain features
                feats.append(f"{z.id}:rain_1h")
                feats.append(f"{z.id}:saturation_gain")

                self._learners[node] = NodeRLS(
                    node=node,
                    candidate_features=feats,
                    config=self.config,
                    prior_weights=priors.get(node),
                )

    def record_update(
        self,
        node: str,
        feature_vals: Dict[str, float],
        target_stress: float,
        target_time: datetime,
        clock_time: datetime,
        boost_forgetting: Optional[float] = None,
    ) -> float:
        """Execute online learning step.

        Enforces R3: clock_time >= target_time.
        """
        assert clock_time >= target_time, (
            f"R3 violation! Update at clock_time={clock_time} before target_time={target_time}"
        )
        self.update_log.append((target_time, clock_time))

        learner = self._learners.get(node)
        if not learner:
            return 0.0

        # Construct vector x
        x = np.zeros(learner.d, dtype=np.float64)
        for i, feat in enumerate(learner.features):
            if feat == "intercept":
                x[i] = 1.0
            else:
                x[i] = feature_vals.get(feat, 0.0)

        err = learner.update(x, target_stress, boost_forgetting=boost_forgetting)

        # Inspect weights and update EdgeBook
        self._update_edgebook_for_node(node, clock_time)
        return err

    def _update_edgebook_for_node(self, node: str, clock_time: datetime) -> None:
        learner = self._learners[node]
        theta = learner.theta
        P_diag = np.maximum(1e-8, np.diag(learner.P))
        se = np.sqrt(learner.residual_variance * P_diag)

        candidates: List[Tuple[str, str, float, float, float, bool]] = []
        for i, feat in enumerate(learner.features):
            if feat == "intercept" or feat.endswith("@-1h") and feat.startswith(node):
                continue
            if "@-" in feat:
                parent, lag_str = feat.split("@-")
                lag = float(lag_str.replace("h", ""))
                w = float(theta[i])
                z_score = float(abs(w) / max(1e-6, se[i]))
                is_sig = (z_score >= self.config.z_min) and (abs(w) >= self.config.w_min)
                conf = float(1.0 / (1.0 + np.exp(-max(-5.0, min(5.0, z_score - 2.0)))))
                candidates.append((parent, node, lag, w, conf, is_sig))

        # Select single best lag per parent candidate to prevent multi-lag self-cancellation
        best_by_parent: Dict[str, Tuple[str, str, float, float, float, bool, float]] = {}
        for parent, target, lag, w, conf, is_sig in candidates:
            idx = learner.features.index(f"{parent}@-{int(lag)}h")
            z = abs(w) / max(1e-6, se[idx])
            if parent not in best_by_parent or z > best_by_parent[parent][6]:
                best_by_parent[parent] = (parent, target, lag, w, conf, is_sig, z)

        # Sort by z_score descending and enforce max_active_edges_per_node
        selected = sorted(best_by_parent.values(), key=lambda c: c[6], reverse=True)
        active_count = 0
        for parent, target, lag, w, conf, is_sig, z in selected:
            if is_sig and active_count < self.config.max_active_edges_per_node:
                self.edge_book.update_edge(parent, target, lag, w, conf, clock_time, is_significant=True)
                active_count += 1
            else:
                self.edge_book.update_edge(parent, target, lag, w, conf, clock_time, is_significant=False)


    def get_model(self) -> ForecastModel:
        """Extract current forward model from learned coefficients."""
        nodes = list(self._learners.keys())
        intercepts: Dict[str, float] = {}
        persistence: Dict[str, float] = {}
        couplings: Dict[str, List[Tuple[str, float, float]]] = {n: [] for n in nodes}
        exogenous: Dict[str, List[Tuple[str, float]]] = {n: [] for n in nodes}
        sigmas: Dict[str, float] = {}

        for n, learner in self._learners.items():
            intercepts[n] = float(learner.theta[0])
            persistence[n] = float(np.clip(learner.theta[1], 0.0, 0.99))
            sigmas[n] = float(np.sqrt(max(1e-4, learner.residual_variance)))

            for i, feat in enumerate(learner.features[2:], start=2):
                w = float(learner.theta[i])
                if "@-" in feat:
                    parent, lag_str = feat.split("@-")
                    lag = float(lag_str.replace("h", ""))
                    if abs(w) >= self.config.w_min:
                        couplings[n].append((parent, lag, w))
                elif "rain" in feat or "saturation" in feat:
                    if abs(w) > 1e-4:
                        exogenous[n].append((feat, w))

        return ForecastModel(
            nodes=nodes,
            intercepts=intercepts,
            persistence=persistence,
            couplings=couplings,
            exogenous_weights=exogenous,
            sigmas=sigmas,
        )
