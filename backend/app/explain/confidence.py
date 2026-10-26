"""Explanation Confidence, Graceful Degradation, and Abstention Engine.

Confidence Formulation:
  Confidence in [0, 1] synthesises:
    - Evidence Quality (30%): Mean sensor quality score of nodes along the failure chain.
    - Edge Confidence (25%): Mean EdgeBook statistical confidence along chain links.
    - Usage Probability (20%): Mean empirical dominant trigger probability P(u dominant | v).
    - Attribution Stability (15%): Jaccard rank stability of top drivers across noise seeds.
    - Drift Penalty (-10%): Penalty if any active edge in the chain underwent recent drift.

Abstention & Degradation Rules:
  - If Evidence Quality < 0.5: downgrade to 'low' confidence, warn of wider ETA intervals.
  - If Rank Stability < 0.5: abstain from picking single dominant driver ('attribution unstable').
  - If top drivers have nearly identical contributions (|delta| < 0.02): flag unidentifiable drivers ('cannot separate X from Y').
  - If no chain reaches probability floor: flag 'no coherent cascade above threshold' rather than hallucinating paths.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from backend.app.explain.records import ChainLink, DriverRecord


def compute_explanation_confidence(
    chain_links: List[ChainLink],
    candidate_drivers: List[DriverRecord],
    evidence_quality: float = 0.85,
    attribution_stability: float = 1.0,
    has_recent_drift: bool = False,
) -> Tuple[float, str, List[str]]:
    """Compute overall explanation confidence score, category, and list of abstentions.

    Returns:
        (confidence_score, category, abstentions)
    """
    abstentions: List[str] = []

    # 1. Edge confidence along chain
    if chain_links:
        edge_conf = float(sum(link.confidence for link in chain_links) / len(chain_links))
        link_usage = float(sum(link.p_link for link in chain_links) / len(chain_links))
    else:
        edge_conf = 0.50
        link_usage = 0.50

    # 2. Weighted formula
    raw_score = (
        0.30 * max(0.0, min(1.0, evidence_quality))
        + 0.25 * max(0.0, min(1.0, edge_conf))
        + 0.20 * max(0.0, min(1.0, link_usage))
        + 0.15 * max(0.0, min(1.0, attribution_stability))
        - (0.10 if has_recent_drift else 0.0)
    )
    score = round(float(max(0.05, min(0.99, raw_score))), 4)

    # 3. Categorisation
    if score >= 0.70:
        category = "high"
    elif score >= 0.40:
        category = "medium"
    else:
        category = "low"

    # 4. Abstention checks
    if evidence_quality < 0.50:
        abstentions.append("Low sensor evidence quality; wider predictive intervals applied.")
        category = "low"

    if attribution_stability < 0.50:
        abstentions.append("Attribution unstable across noise seeds; cannot separate competing drivers with confidence.")

    if len(candidate_drivers) >= 2:
        d0, d1 = candidate_drivers[0], candidate_drivers[1]
        if abs(d0.contribution - d1.contribution) < 0.02 and abs(d0.contribution) > 0.05:
            abstentions.append(f"Cannot separate {d0.label} from {d1.label} (contributions nearly identical).")

    if not chain_links:
        abstentions.append("No coherent cascade above threshold.")

    if has_recent_drift:
        abstentions.append("Recent topological drift detected on active edges; model adapting.")

    return score, category, abstentions
