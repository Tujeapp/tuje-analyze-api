# ============================================================================
# notion_steps/engine.py - Build a notion cycle from notion steps
# ============================================================================
# Ties repository (DB reads/writes on ONE connection) to rules + planner.
# Not wired into cycle creation yet.
# ============================================================================

import logging
from typing import Any, Dict, List, Optional

import asyncpg

from .planner import PlannerError, plan_slots
from .repository import (
    load_candidates,
    load_evidence,
    load_seen,
    load_steps,
    pick_notion_ids,
    upsert_in_progress,
)
from .rules import current_step, is_discovered

logger = logging.getLogger(__name__)


async def build_notion_cycle(
    conn: asyncpg.Connection,
    user_id: str,
    cycle_level: int,
    slots: int = 7,
    dry_run: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Try the user's candidate notions in priority order; the first one that
    yields a full plan wins. Unless dry_run, marks that notion in_progress.

    Returns:
        {"notion_id", "ordered_ids", "current_step_id", "notion_step_pool",
         "warnings"} or None if no notion could be built.
    """
    notion_ids = await pick_notion_ids(conn, user_id, cycle_level)
    reasons: Dict[str, str] = {}

    for notion_id in notion_ids:
        steps, warnings = await load_steps(conn, notion_id)
        if not steps:
            reasons[notion_id] = f"no usable live steps ({len(warnings)} skipped)"
            continue

        candidates = await load_candidates(conn, steps, cycle_level)
        if not candidates:
            reasons[notion_id] = f"no candidate interactions at level {cycle_level}"
            continue

        evidence = await load_evidence(conn, user_id, notion_id)
        if is_discovered(steps, evidence):
            logger.info(f"build_notion_cycle: notion {notion_id} already discovered for user {user_id} — skipping")
            reasons[notion_id] = "already discovered"
            continue

        seen = await load_seen(conn, user_id, candidates.keys())
        step = current_step(steps, evidence)

        try:
            plan = plan_slots(
                steps=steps,
                candidates=candidates,
                evidence=evidence,
                played_in_cycle=[],
                seen_ever=seen,
                slots_needed=slots,
            )
        except PlannerError as e:
            reasons[notion_id] = f"planner error: {e}"
            continue

        if len(plan.ids) != slots:
            reasons[notion_id] = f"plan returned {len(plan.ids)}/{slots} ids"
            continue

        if not dry_run:
            await upsert_in_progress(conn, user_id, notion_id, step.id)

        all_warnings: List[str] = warnings + plan.warnings
        logger.info(
            f"build_notion_cycle: user={user_id} notion={notion_id} "
            f"current_step={step.id} plan={plan.ids} warnings={len(all_warnings)}"
            f"{' (dry_run)' if dry_run else ''}"
        )
        return {
            "notion_id": notion_id,
            "ordered_ids": plan.ids,
            "current_step_id": step.id,
            "notion_step_pool": {
                "notion_id": notion_id,
                "steps": [
                    {"id": s.id, "purpose": s.purpose, "rank": s.rank}
                    for s in sorted(steps, key=lambda s: (s.rank, s.id))
                ],
                "candidates": candidates,
            },
            "warnings": all_warnings,
        }

    logger.warning(
        f"build_notion_cycle: no notion could be built for user={user_id} "
        f"level={cycle_level}; tried {notion_ids or 'none'}; reasons={reasons}"
    )
    return None
