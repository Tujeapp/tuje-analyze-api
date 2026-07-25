"""Interaction scoring — three pure phases.

A. Gross Interaction Score = gross_score × coefficient   (capped at 100)
B. Bonus-Malus Score       = bonus_total − (malus_total × modulo)
C. Interaction Score       = gross_interaction + bonus_malus   (rounded, clamped 0..100)

Scoring is only meaningful when the user gave a MATCHED answer — that gating
lives in the caller, not here. These functions assume a match exists (an
answer_optimum_level is available). Levels are always >= 50 in content, but the
coefficient guards defensively against a non-positive level just in case.
"""

import logging
import math

logger = logging.getLogger("interaction_scoring")


def compute_coefficient(answer_opt: float, interaction_opt: float, cycle_level: float) -> float:
    """((answer_opt / interaction_opt) + (answer_opt / cycle_level)) / 2.

    Rewards a higher-level answer relative to the interaction and the cycle.
    A non-positive denominator (should never happen — levels are >= 50) makes
    that term contribute 1.0 rather than raising."""
    term1 = (answer_opt / interaction_opt) if interaction_opt and interaction_opt > 0 else 1.0
    term2 = (answer_opt / cycle_level) if cycle_level and cycle_level > 0 else 1.0
    return (term1 + term2) / 2.0


def compute_gross_interaction_score(
    gross_score: float,
    answer_opt: float,
    interaction_opt: float,
    cycle_level: float,
) -> float:
    """Phase A. gross_score × coefficient, capped at 100 (never rounded here —
    rounding happens once at the final score)."""
    coeff = compute_coefficient(answer_opt, interaction_opt, cycle_level)
    gross_interaction = gross_score * coeff
    return min(100.0, gross_interaction)   # cap #1


def compute_bonus_malus_score(bonus_total: float, malus_total: float, modulo: float) -> float:
    """Phase B. Bonuses full weight; maluses scaled by the session modulo.
    bonus_total and malus_total are POSITIVE magnitudes (from the engine)."""
    return bonus_total - (malus_total * modulo)


def compute_interaction_score(
    gross_score: float,
    answer_opt: float,
    interaction_opt: float,
    cycle_level: float,
    bonus_total: float,
    malus_total: float,
    modulo: float,
) -> dict:
    """Phase C. Assemble A + B, round once, clamp to [0, 100].

    Returns a breakdown so the commit path can log/audit how the number was
    reached (the gross interaction, the bonus-malus contribution, the final)."""
    gross_interaction = compute_gross_interaction_score(
        gross_score, answer_opt, interaction_opt, cycle_level
    )
    bonus_malus = compute_bonus_malus_score(bonus_total, malus_total, modulo)
    raw = gross_interaction + bonus_malus
    # Round half UP explicitly (Python's round() is banker's/half-to-even, which
    # would send e.g. 88.5 → 88; a user-facing score should round ties up).
    # For negative raw this floors toward zero, but the clamp handles negatives.
    final = max(0, min(100, math.floor(raw + 0.5)))   # single rounding + cap #2
    return {
        "interaction_score": final,
        "gross_interaction_score": gross_interaction,   # pre-round, for audit
        "bonus_malus_score": bonus_malus,
        "coefficient": compute_coefficient(answer_opt, interaction_opt, cycle_level),
    }
