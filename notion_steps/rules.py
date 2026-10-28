# ============================================================================
# notion_steps/rules.py - Notion step validation rules (pure logic)
# ============================================================================
# No DB, no env: stdlib + dataclasses only.
#
# A notion is learned through ranked steps. Evidence is the set of distinct
# interactions answered correctly (perfect/good) while tagged with a step.
# A step is validated either DIRECTLY (enough evidence on the step itself) or by
# SKIP (≥2 distinct interactions already succeeded on strictly higher steps).
# ============================================================================

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

PURPOSES = ("awareness", "learn", "understand", "practice_guided", "practice_free")

# step_id -> {brain_interaction_id: "perfect" | "good"}
Evidence = Dict[str, Dict[str, str]]


def normalize_purpose(raw: Optional[str]) -> Optional[str]:
    """'Practice guided' / 'practice-guided' -> 'practice_guided'; unknown -> None."""
    if raw is None:
        return None
    key = "_".join(str(raw).strip().lower().replace("-", " ").split())
    return key if key in PURPOSES else None


@dataclass(frozen=True)
class Step:
    id: str
    purpose: str
    rank: int


def _by_rank(steps: Iterable[Step]) -> List[Step]:
    return sorted(steps, key=lambda s: (s.rank, s.id))


def counts(ev_for_step: Optional[Dict[str, str]]) -> Tuple[int, int]:
    """(perfect_count, total_count) of distinct interactions on one step."""
    ev_for_step = ev_for_step or {}
    perfect = sum(1 for verdict in ev_for_step.values() if verdict == "perfect")
    return perfect, len(ev_for_step)


def directly_validated(step: Step, ev: Evidence) -> bool:
    perfect, total = counts(ev.get(step.id))
    if step.purpose in ("awareness", "learn"):
        return perfect >= 1 or total >= 2
    if step.purpose in ("understand", "practice_guided"):
        return total >= 2
    if step.purpose == "practice_free":
        return total >= 1
    # Unknown purpose: never validated directly (only by skip).
    return False


def validated_steps(steps: Iterable[Step], ev: Evidence) -> Dict[str, str]:
    """step_id -> 'direct' | 'skip' for every validated step."""
    ordered = _by_rank(steps)
    result: Dict[str, str] = {}
    for step in ordered:
        if directly_validated(step, ev):
            result[step.id] = "direct"
            continue
        # Distinct interactions with evidence on any strictly higher step —
        # one interaction tagged on two higher steps counts once.
        higher_ids = set()
        for other in ordered:
            if other.rank > step.rank:
                higher_ids.update((ev.get(other.id) or {}).keys())
        if len(higher_ids) >= 2:
            result[step.id] = "skip"
    return result


def current_step(steps: Iterable[Step], ev: Evidence) -> Optional[Step]:
    """Lowest-rank step not yet validated; None once every step is validated."""
    ordered = _by_rank(steps)
    validated = validated_steps(ordered, ev)
    for step in ordered:
        if step.id not in validated:
            return step
    return None


def is_discovered(steps: Iterable[Step], ev: Evidence) -> bool:
    ordered = _by_rank(steps)
    return bool(ordered) and current_step(ordered, ev) is None


def remaining_need(step: Step, ev: Evidence, validated: Optional[Dict[str, str]] = None) -> int:
    """
    How many more interactions this step wants planned. Pass the
    validated_steps() map so skip-validated steps count as done; without it,
    only direct validation is considered.
    """
    if (validated is not None and step.id in validated) or directly_validated(step, ev):
        return 0
    _, total = counts(ev.get(step.id))
    if step.purpose in ("understand", "practice_guided"):
        return max(1, 2 - total)
    # awareness / learn / practice_free (and unknown purposes): one more.
    return 1
