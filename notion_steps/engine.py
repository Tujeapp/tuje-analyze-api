# ============================================================================
# notion_steps/engine.py - Build a notion cycle from notion steps
# ============================================================================
# Ties repository (DB reads/writes on ONE connection) to rules + planner.
# Not wired into cycle creation yet.
# ============================================================================

import json
import logging
from typing import Any, Dict, List, Optional

import asyncpg

from .planner import PlannerError, plan_slots, splice_tail
from .repository import (
    insert_validations,
    load_candidates,
    load_evidence,
    load_seen,
    load_steps,
    pick_notion_ids,
    update_cycle_tail,
    upsert_evidence,
    upsert_in_progress,
    write_notion_progress,
)
from .rules import Step, current_step, is_discovered, validated_steps

logger = logging.getLogger(__name__)

CYCLE_SIZE = 7


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


async def on_interaction_committed(conn: asyncpg.Connection, session_interaction_id: str,
                                   answer_id: str) -> None:
    """
    Notion cycles only (spec §4.4): record step evidence for the committed
    interaction, update step/notion progress, re-plan the not-yet-played tail
    of candidate_pool_ids from the cycle's stored step pool (no new search).
    All writes run in ONE transaction. The caller must wrap this in
    try/except — it never fails a commit.
    """
    row = await conn.fetchrow("""
        SELECT si.cycle_id, si.brain_interaction_id::text AS brain_interaction_id,
               si.interaction_number, si.session_id, s.user_id,
               sc.cycle_goal, sc.target_notion_id, sc.notion_step_pool,
               sc.candidate_pool_ids::text[] AS candidate_pool_ids,
               sa.verdict
        FROM session_interaction si
        JOIN session s        ON s.id = si.session_id
        JOIN session_cycle sc ON sc.id = si.cycle_id
        LEFT JOIN session_answer sa ON sa.id = $2
        WHERE si.id = $1
    """, session_interaction_id, answer_id)
    if row is None or row["cycle_goal"] != "notion" or row["notion_step_pool"] is None:
        logger.info(f"on_interaction_committed: {session_interaction_id} is not a "
                    f"step-built notion cycle — skipping")
        return

    pool = row["notion_step_pool"]
    if isinstance(pool, str):  # asyncpg returns jsonb as text by default
        pool = json.loads(pool)
    steps = [Step(id=s["id"], purpose=s["purpose"], rank=int(s["rank"])) for s in pool["steps"]]
    step_ids = {s.id for s in steps}
    candidates = {k: list(v) for k, v in pool["candidates"].items()}
    notion_id = pool.get("notion_id") or row["target_notion_id"]
    user_id = row["user_id"]
    brain_id = row["brain_interaction_id"]
    verdict = row["verdict"]
    played_count = row["interaction_number"]
    pool_ids = list(row["candidate_pool_ids"] or [])

    old_tail = pool_ids[played_count:]
    new_tail = old_tail
    warnings: List[str] = []

    async with conn.transaction():
        # a) Evidence: every step of this notion the interaction is tagged with.
        evidence_steps: List[str] = []
        if verdict in ("perfect", "good"):
            evidence_steps = [sid for sid in candidates.get(brain_id, []) if sid in step_ids]
            for sid in evidence_steps:
                await upsert_evidence(conn, user_id, sid, notion_id, brain_id,
                                      verdict, session_interaction_id)

        # b) Validation (direct + skip).
        evidence = await load_evidence(conn, user_id, notion_id)
        newly_validated = await insert_validations(
            conn, user_id, notion_id, validated_steps(steps, evidence))

        # c) Notion progress.
        step = current_step(steps, evidence)
        discovered = is_discovered(steps, evidence)
        await write_notion_progress(conn, user_id, notion_id,
                                    step.id if step else None, discovered)

        # d) Re-plan the not-yet-played tail; played positions never change.
        remaining = CYCLE_SIZE - played_count
        if remaining > 0:
            played = pool_ids[:played_count]
            try:
                seen = await load_seen(conn, user_id, candidates.keys())
                plan = plan_slots(
                    steps=steps, candidates=candidates, evidence=evidence,
                    played_in_cycle=played, seen_ever=seen, slots_needed=remaining,
                    last_played_id=played[-1] if played else None,
                )
                warnings = plan.warnings
                new_pool = splice_tail(pool_ids, played_count, plan.ids, size=CYCLE_SIZE)
                if new_pool is None:
                    logger.error(
                        f"on_interaction_committed: re-plan for {session_interaction_id} "
                        f"would not give {CYCLE_SIZE} ids (played={played_count}, "
                        f"pool={len(pool_ids)}, tail={len(plan.ids)}) — tail kept")
                elif await update_cycle_tail(conn, row["cycle_id"], played_count, new_pool):
                    new_tail = plan.ids
                else:
                    warnings.append("a later position already exists — tail kept")
            except PlannerError as e:
                warnings.append(f"planner error: {e} — tail kept")

    logger.info(
        f"notion step commit: si={session_interaction_id} notion={notion_id} "
        f"verdict={verdict} evidence={evidence_steps} newly_validated={newly_validated} "
        f"current_step={step.id if step else None} discovered={discovered} "
        f"tail {old_tail} -> {new_tail} warnings={warnings}"
    )
