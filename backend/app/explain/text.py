"""Hedged, Deterministic Explanation Text Generation and Phrasing Lints.

Enforces:
  - Strict hedging standards: only permitted hedged verbs ('is estimated to', 'under the learned model', 'the model links').
  - Absolute prohibition of unhedged causal certainty words ('proven', 'definitely caused', 'certainly causes').
  - Strict numerical consistency: numbers in generated text must match structured record fields.
  - Transparent distinction between real meteorological inputs and synthetic simulated streams.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from backend.app.explain.records import ExplanationRecord

# Prohibited unhedged certainty words for model-based claims
BANNED_CERTAINTY_WORDS = [
    "proven cause",
    "proven that",
    "proves that",
    "definitely caused",
    "guaranteed to",
    "certainly causes",
    "certain cause",
    "inarguable",
    "absolute certainty",
]

# Required / approved hedged phrasings
APPROVED_HEDGED_VERBS = [
    "is estimated to",
    "under the learned model",
    "the model links",
    "learned dependency",
    "paired estimate",
    "statistical candidate",
]


def generate_explanation_text(
    record: ExplanationRecord,
    n_rollouts: int = 300,
) -> str:
    """Generate deterministic, hedged plain-language explanation from an ExplanationRecord."""
    p_before_pct = round(record.probability_before * 100.0, 1)
    p_after_pct = round(record.probability_after * 100.0, 1)

    top_driver_label = (
        record.drivers[0].label
        if record.drivers
        else "ambient model background dynamics"
    )

    sentences: List[str] = []

    # 1. Primary Risk State & Probability Transition
    if record.probability_after >= record.probability_before:
        s1 = (
            f"In {record.subject}, {top_driver_label} is estimated to raise stress; "
            f"this is the largest contributor to the rise in P(critical within 72h) "
            f"from {p_before_pct:.1f}% to {p_after_pct:.1f}% (paired estimate, n={n_rollouts})."
        )
    else:
        s1 = (
            f"In {record.subject}, P(critical within 72h) is estimated to decrease "
            f"from {p_before_pct:.1f}% to {p_after_pct:.1f}% under the learned model, "
            f"driven primarily by {top_driver_label}."
        )
    sentences.append(s1)

    # 2. Chain Stage Information
    if record.chain_tree and "branches" in record.chain_tree and record.chain_tree["branches"]:
        first_branch = record.chain_tree["branches"][0]
        parent_name = first_branch.get("node", "upstream driver")
        timing = first_branch.get("timing_stats", {})
        med_lag = timing.get("p50", 2.0)
        s2 = (
            f"The model links incoming stress from {parent_name} to {record.subject} "
            f"with an estimated median propagation lag of {med_lag:.1f} hours."
        )
        sentences.append(s2)

    # 3. Feedback Loop Disclosure
    if record.loops:
        loop = record.loops[0]
        loop_nodes_str = " <-> ".join(loop.nodes)
        s3 = (
            f"A reinforcing feedback loop is identified along {loop_nodes_str} "
            f"(estimated amplification factor +{loop.amplification_factor:.2f})."
        )
        sentences.append(s3)

    # 4. Confidence & Abstention Disclosures
    if record.abstentions:
        abs_text = "; ".join(record.abstentions)
        s4 = f"Confidence is assessed as {record.confidence_category} ({record.confidence:.2f}): {abs_text}"
        sentences.append(s4)
    else:
        s4 = f"Overall explanation confidence is assessed as {record.confidence_category} ({record.confidence:.2f})."
        sentences.append(s4)

    # 5. Provenance Notice
    s5 = "Estimates under the learned model; downstream infrastructure responses are simulated."
    sentences.append(s5)

    return " ".join(sentences)


def lint_explanation_text(text: str, record: Optional[ExplanationRecord] = None) -> List[str]:
    """Audit text against hedging standards, numerical accuracy, and simulated stream disclosures.

    Returns:
        List of lint failure messages (empty if all checks pass).
    """
    violations: List[str] = []
    text_lower = text.lower()

    # 1. Check for banned unhedged certainty words
    for word in BANNED_CERTAINTY_WORDS:
        if word in text_lower:
            violations.append(f"Contains prohibited unhedged certainty phrasing: '{word}'")

    # 2. Check for required hedged verb presence
    has_hedged_verb = any(v in text_lower for v in APPROVED_HEDGED_VERBS)
    if not has_hedged_verb:
        violations.append("Lacks required hedged verb phrasing (e.g. 'is estimated to', 'under the learned model')")

    # 3. Numerical consistency with structured record
    if record is not None:
        p_b_str = f"{record.probability_before * 100.0:.1f}%"
        p_a_str = f"{record.probability_after * 100.0:.1f}%"
        if p_b_str not in text and f"{round(record.probability_before * 100):.0f}%" not in text:
            violations.append(f"Probability before ({p_b_str}) does not match text numbers.")
        if p_a_str not in text and f"{round(record.probability_after * 100):.0f}%" not in text:
            violations.append(f"Probability after ({p_a_str}) does not match text numbers.")

    # 4. Check for simulated infrastructure disclosure
    if "simulated" not in text_lower:
        violations.append("Missing mandatory honesty disclosure that downstream infrastructure is simulated.")

    return violations
