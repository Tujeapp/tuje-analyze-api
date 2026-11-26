# ============================================================================
# intent_vocab/rules.py - Intent vocab scoring + pack state rules (pure logic)
# ============================================================================
# No DB, no env: stdlib + dataclasses only.
#
# Per-word scores (0..100) for passive (understood) and active (produced)
# knowledge. Evidence from an interaction raises them by a fixed increment
# that depends on kind and answer mode. A pack's state is derived from the
# weighted share of its words that are understood / owned.
# ============================================================================

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

PASSIVE_INC = 50
ACTIVE_VOICE_INC = 50
ACTIVE_BUTTON_INC = 25
DEFAULT_MASTERY = 0.7
DEFAULT_WEIGHT = 0.5

MAX_SCORE = 100

MODES = ("voice", "multipleButtons", "singleButton")
_ACTIVE_INC = {
    "voice": ACTIVE_VOICE_INC,
    "multipleButtons": ACTIVE_BUTTON_INC,
    "singleButton": 0,
}

STATE_ORDER = ("in_progress", "discovered", "owned")


def increment(kind: str, mode: str, context: Optional[dict] = None) -> int:
    """Score increment for one piece of evidence.

    `context` is unused in v1: hook for later refinement (levels, difficulty).
    """
    if mode not in _ACTIVE_INC:
        raise ValueError(f"unknown mode: {mode!r}")
    if kind == "passive":
        return PASSIVE_INC
    if kind == "active":
        return _ACTIVE_INC[mode]
    raise ValueError(f"unknown kind: {kind!r}")


@dataclass
class WordScore:
    passive: int = 0
    active: int = 0


def apply_evidence(
    scores: Dict[str, WordScore],
    passive_ids: Iterable[str],
    active_ids: Iterable[str],
    mode: str,
    owned_ids: Optional[Set[str]] = None,
) -> Dict[str, Tuple[int, int]]:
    """Apply one interaction's evidence to `scores` (mutated in place).

    Each id counts once per call per kind; scores are capped at 100. Words in
    `owned_ids` are skipped entirely (no entry created, absent from the result).
    Returns the (passive_delta, active_delta) applied for every id touched.
    """
    p_inc = increment("passive", mode)
    a_inc = increment("active", mode)
    passive_set = set(passive_ids)
    active_set = set(active_ids)
    skip = set(owned_ids or ())

    deltas: Dict[str, Tuple[int, int]] = {}
    for vid in sorted((passive_set | active_set) - skip):
        score = scores.setdefault(vid, WordScore())
        pd = ad = 0
        if vid in passive_set:
            pd = max(0, min(p_inc, MAX_SCORE - score.passive))
            score.passive += pd
        if vid in active_set:
            ad = max(0, min(a_inc, MAX_SCORE - score.active))
            score.active += ad
        deltas[vid] = (pd, ad)
    return deltas


def apply_downgrade(
    scores: Dict[str, WordScore],
    vocab_ids: Iterable[str],
    amount: int = 50,
) -> Dict[str, int]:
    """Lower passive by `amount` (floor 0) for each word, owned ones included.

    Each id counts once; missing entries are created (0 stays 0). Returns the
    applied passive delta per id (negative or 0).
    """
    deltas: Dict[str, int] = {}
    for vid in sorted(set(vocab_ids)):
        score = scores.setdefault(vid, WordScore())
        d = min(max(0, amount), score.passive)
        score.passive -= d
        deltas[vid] = -d
    return deltas


def is_owned(
    score: WordScore,
    level_own: Optional[int],
    session_level: int,
    downgraded: bool = False,
) -> bool:
    """Score ownership (100/100) always applies; level ownership only when the
    word has not been downgraded."""
    if score.passive == MAX_SCORE and score.active == MAX_SCORE:
        return True
    return not downgraded and level_own is not None and session_level >= level_own


def weight_of(commonness) -> float:
    if commonness is None:
        return DEFAULT_WEIGHT
    w = float(commonness)
    return 0.0 if w < 0 else w


@dataclass
class PackWord:
    vocab_id: str
    weight: float
    passive: int
    active: int
    owned: bool


def pack_ratios(words: List[PackWord]) -> dict:
    """Weighted ratios for a pack. `weight` may be None (→ DEFAULT_WEIGHT)."""
    zero = {"understood_ratio": 0.0, "owned_ratio": 0.0, "avg_passive": 0.0, "avg_active": 0.0}
    if not words:
        return zero
    total = understood = owned = passive = active = 0.0
    for w in words:
        wt = weight_of(w.weight)
        total += wt
        if w.passive == MAX_SCORE or w.owned:
            understood += wt
        if w.owned:
            owned += wt
        passive += wt * w.passive
        active += wt * w.active
    if total <= 0:
        return zero
    return {
        "understood_ratio": understood / total,
        "owned_ratio": owned / total,
        "avg_passive": passive / total,
        "avg_active": active / total,
    }


def pack_state(ratios: dict, mastery_ratio: Optional[float], previous: Optional[str]) -> str:
    m = mastery_ratio or DEFAULT_MASTERY  # None or 0 → default
    if ratios.get("owned_ratio", 0.0) >= m:
        state = "owned"
    elif ratios.get("understood_ratio", 0.0) >= m:
        state = "discovered"
    else:
        state = "in_progress"
    if previous in STATE_ORDER and STATE_ORDER.index(previous) > STATE_ORDER.index(state):
        return previous
    return state
