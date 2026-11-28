# ============================================================================
# intent_vocab/planner.py - Greedy slot planner for intent vocab packs
# ============================================================================
# No DB, no env: stdlib + dataclasses only.
#
# Each slot gets the candidate interaction with the highest remaining value
# (weighted score headroom of the not-owned words it exercises). After each
# pick, success is SIMULATED on a copy of the scores so later slots target
# other words.
# ============================================================================

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from intent_vocab import rules
from intent_vocab.rules import PackWord, WordScore

# Weight of active headroom per answer mode.
ACTIVE_FACTOR = {"voice": 1.0, "multipleButtons": 0.5, "singleButton": 0.0}

SATURATED_WARNING = "pack saturated"


@dataclass
class Candidate:
    id: str
    passive_ids: Set[str]
    active_ids: Set[str]
    mode: str


@dataclass
class PlanResult:
    ids: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class PlannerError(Exception):
    pass


def _value(c: Candidate, words: Dict[str, PackWord], scores: Dict[str, WordScore], owned: Set[str]) -> float:
    total = 0.0
    for vid in c.passive_ids:
        if vid in words and vid not in owned:
            total += rules.weight_of(words[vid].weight) * (100 - scores[vid].passive)
    f = ACTIVE_FACTOR.get(c.mode, 0.0)
    if f:
        for vid in c.active_ids:
            if vid in words and vid not in owned:
                total += f * rules.weight_of(words[vid].weight) * (100 - scores[vid].active)
    return round(total, 9)  # absorb float noise so ties are real ties


def candidate_value(c: Candidate, words: Dict[str, PackWord]) -> float:
    """A candidate's value against the words' current scores (no simulation)."""
    scores = {vid: WordScore(w.passive, w.active) for vid, w in words.items()}
    owned = {vid for vid, w in words.items() if w.owned}
    return _value(c, words, scores, owned)


def plan_slots(
    words: Dict[str, PackWord],
    candidates: List[Candidate],
    played_in_cycle: List[str],
    seen_ever: Set[str],
    slots_needed: int,
    last_played_id: Optional[str] = None,
) -> PlanResult:
    result = PlanResult()
    if slots_needed <= 0:
        return result
    if not candidates:
        raise PlannerError("no candidates")

    # Simulation state: a private copy, never the caller's objects.
    scores = {vid: WordScore(w.passive, w.active) for vid, w in words.items()}
    owned = {vid for vid, w in words.items() if w.owned}
    played = set(played_in_cycle)
    planned: Counter = Counter()
    prev = last_played_id

    for _ in range(slots_needed):
        pool = [c for c in candidates if c.id != prev] or list(candidates)
        scored = [(c, _value(c, words, scores, owned)) for c in pool]
        if all(v == 0 for _, v in scored) and SATURATED_WARNING not in result.warnings:
            result.warnings.append(SATURATED_WARNING)

        def key(item):
            c, v = item
            return (
                -v,
                c.id in played or planned[c.id] > 0,
                c.id in seen_ever,
                planned[c.id],
                c.id,
            )

        pick, _v = min(scored, key=key)
        result.ids.append(pick.id)
        planned[pick.id] += 1
        prev = pick.id

        # Simulate success for the words of this pack.
        rules.apply_evidence(
            scores,
            [v for v in pick.passive_ids if v in words],
            [v for v in pick.active_ids if v in words],
            pick.mode,
        )
        for vid in pick.passive_ids | pick.active_ids:
            if vid in scores and scores[vid].passive == 100 and scores[vid].active == 100:
                owned.add(vid)

    return result
