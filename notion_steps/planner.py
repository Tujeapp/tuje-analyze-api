# ============================================================================
# notion_steps/planner.py - Plan the remaining slots of a notion cycle
# ============================================================================
# No DB, no env: stdlib + dataclasses only.
#
# Phase 1: walk steps from the current one upward (skipping validated steps),
#          planning remaining_need() interactions per step.
# Phase 2: fill leftover slots from the LAST-ranked step (unused first, then
#          repeats, least-used first).
# Phase 3: if the last step has no interactions, fill from any notion candidate.
# Throughout: never the same id twice in a row when an alternative exists.
# ============================================================================

from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from .rules import Evidence, Step, current_step, remaining_need, validated_steps


@dataclass
class PlanResult:
    ids: List[str]
    warnings: List[str]


class PlannerError(Exception):
    """The notion has no steps or no candidate interactions."""


def plan_slots(
    steps: List[Step],
    candidates: Dict[str, List[str]],
    evidence: Evidence,
    played_in_cycle: List[str],
    seen_ever: Set[str],
    slots_needed: int,
    last_played_id: Optional[str] = None,
) -> PlanResult:
    """
    Args:
        steps: this notion's steps (any order).
        candidates: brain_interaction_id -> step_ids it is tagged with (this notion only).
        evidence: step_id -> {brain_interaction_id: "perfect"|"good"}.
        played_in_cycle: ids already played this cycle, in order.
        seen_ever: ids the user has ever seen.
        slots_needed: how many ids to return.
        last_played_id: the id just played (first planned slot must differ when possible).

    Returns:
        PlanResult with exactly slots_needed ids (empty if slots_needed <= 0).

    Raises:
        PlannerError: no steps or no candidates.
    """
    if slots_needed <= 0:
        return PlanResult(ids=[], warnings=[])
    if not steps:
        raise PlannerError("notion has no steps")
    if not candidates:
        raise PlannerError("notion has no candidate interactions")

    ordered = sorted(steps, key=lambda s: (s.rank, s.id))
    step_rank = {s.id: s.rank for s in ordered}
    by_step = {
        s.id: sorted(i for i, tags in candidates.items() if s.id in (tags or []))
        for s in ordered
    }
    validated = validated_steps(ordered, evidence)
    played_set = set(played_in_cycle)
    plan: List[str] = []
    warnings: List[str] = []

    def prev() -> Optional[str]:
        return plan[-1] if plan else last_played_id

    def key(i: str):
        # Unused (never played this cycle nor planned) first, then least-used;
        # never-seen before seen; then id for determinism.
        return (played_in_cycle.count(i) + plan.count(i), i in seen_ever, i)

    def pick(*pools: List[str]) -> Optional[str]:
        """First id across pools (priority order, key order within) that isn't
        the previous slot; the previous slot only if nothing else exists."""
        p = prev()
        for pool in pools:
            for i in sorted(pool, key=key):
                if i != p:
                    return i
        for pool in pools:
            if pool:
                return sorted(pool, key=key)[0]
        return None

    # Phase 1 — current step upward.
    cur = current_step(ordered, evidence)
    if cur is not None:
        for step in ordered:
            if len(plan) >= slots_needed:
                break
            if step.rank < cur.rank or step.id in validated:
                continue
            pool = by_step[step.id]
            if not pool:
                warnings.append(f"content gap: step {step.id} has no interactions")
                continue
            need = remaining_need(step, evidence, validated)
            got = 0
            while got < need and len(plan) < slots_needed:
                fresh = [i for i in pool if i not in played_set and i not in plan]
                replay = [i for i in pool if i in played_set and i not in plan]
                choice = pick(fresh, replay)
                if choice is None:
                    break
                plan.append(choice)
                got += 1
            if got < need and len(plan) < slots_needed:
                warnings.append(f"step {step.id} short: needed {need}, planned {got}")

    # Phase 2 — fill from the last-ranked step.
    last_pool = by_step[ordered[-1].id]

    def max_rank(i: str) -> float:
        return max((step_rank[t] for t in candidates[i] if t in step_rank), default=float("-inf"))

    run_break_warned = False
    while len(plan) < slots_needed and last_pool:
        p = prev()
        choice = next((i for i in sorted(last_pool, key=key) if i != p), None)
        if choice is None:
            # Only the previous id is left on the last step: break the run with
            # the highest-ranked other notion candidate, if any.
            others = [i for i in candidates if i != p]
            if others:
                choice = sorted(others, key=lambda i: (-max_rank(i), key(i)))[0]
                if not run_break_warned:
                    warnings.append(
                        f"last step {ordered[-1].id} exhausted: interleaving other notion interactions"
                    )
                    run_break_warned = True
            else:
                choice = p
        plan.append(choice)

    # Phase 3 — last step has no interactions: any notion candidate.
    if len(plan) < slots_needed:
        warnings.append(
            f"last step {ordered[-1].id} has no interactions: filling from any notion interaction"
        )
        all_ids = list(candidates)
        while len(plan) < slots_needed:
            plan.append(pick(all_ids))

    _break_runs(plan, last_played_id)
    return PlanResult(ids=plan, warnings=warnings)


def _break_runs(ids: List[str], last_played_id: Optional[str]) -> None:
    """Safety pass: swap a slot that repeats its predecessor with the next
    later slot that doesn't. Leaves a repeat only when unavoidable."""
    for i in range(len(ids)):
        p = ids[i - 1] if i else last_played_id
        if ids[i] != p:
            continue
        for j in range(i + 1, len(ids)):
            if ids[j] != p:
                ids[i], ids[j] = ids[j], ids[i]
                break
