# routers/initial_session_router.py
"""
Initial Session Generator — POST /api/initial-session/start

Creates a complete initial session in a single call:
  1. Session row  (session_type='initial', is_initial_session=TRUE)
  2. Cycle row    (template_interaction_ids = the 7 ordered IDs from brain_initial_session_template)
  3. First session_interaction row ready for iOS to play immediately

This endpoint is deliberately separate from regular session logic.
No mood, no notions, no streaks, no boredom, no user-state detection.
Template → ordered cycle → first interaction. Nothing more.

Milestone 1 of v1 onboarding rollout.
Milestone 2 (advancing through interactions 2-7) lives in complete_interaction_router.py — not here.
"""

import asyncpg
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from user_routes import get_current_user
from helpers import generate_id

logger = logging.getLogger(__name__)

router = APIRouter()

DATABASE_URL = os.getenv("DATABASE_URL")


@router.post("/start")
async def start_initial_session(current_user: dict = Depends(get_current_user)):
    """
    Create the initial session for a brand-new user from a pre-defined template.

    Fail-fast contract:
    - 400 onboarding_incomplete  → goal_id or initial_level_bucket is NULL on the user
    - 422 template_incomplete    → fewer than 7 rows in brain_initial_session_template
                                   for this goal/level combination
    - 200                        → session, cycle, and first interaction created; all
                                   IDs returned so iOS can play immediately without a
                                   separate start-interaction call
    """
    user_id = str(current_user["id"])
    goal_id = current_user["goal_id"]
    initial_level_bucket = current_user["initial_level_bucket"]

    # ── ONBOARDING GATE ────────────────────────────────────────────────────────
    # iOS uses the machine-readable "error" field to route back to the onboarding form.
    if goal_id is None or initial_level_bucket is None:
        logger.warning(
            f"⚠️ Initial session blocked — onboarding incomplete for user {user_id}"
        )
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": "onboarding_incomplete",
                "detail": (
                    "Onboarding incomplete: goal and level must be set "
                    "before starting the initial session."
                ),
            },
        )

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:

            # ── TEMPLATE LOOKUP ────────────────────────────────────────────────
            # user_level column holds the 0/1/2 bucket, matching brain_user.initial_level_bucket
            rows = await conn.fetch(
                """
                SELECT interaction_id
                FROM brain_initial_session_template
                WHERE goal_id   = $1
                  AND user_level = $2
                  AND live       = TRUE
                ORDER BY position ASC
                LIMIT 7
                """,
                goal_id,
                initial_level_bucket,
            )

            # ── TEMPLATE COMPLETENESS GATE ─────────────────────────────────────
            if len(rows) != 7:
                # TODO (future, interaction-engine work): plan-B fallback — when a
                # scheduled interaction is unavailable, substitute a similar interaction
                # using the "similar interaction ids" column on brain_interaction
                # (not yet built). For v1 we fail fast and rely on all 18 template
                # combinations (6 goals × 3 levels) being complete in the DB.
                logger.error(
                    f"❌ Template incomplete: goal={goal_id} / level={initial_level_bucket} "
                    f"has {len(rows)} row(s) (expected 7)"
                )
                return JSONResponse(
                    status_code=422,
                    content={
                        "success": False,
                        "error": "template_incomplete",
                        "detail": (
                            f"Initial session template for goal {goal_id} / level "
                            f"{initial_level_bucket} has {len(rows)} interactions, expected 7."
                        ),
                    },
                )

            ordered_ids = [r["interaction_id"] for r in rows]
            logger.info(
                f"📋 Template loaded: {len(ordered_ids)} interactions "
                f"for goal={goal_id} / level={initial_level_bucket}"
            )

            # ── ATOMIC WRITE — all three INSERTs or none ───────────────────────
            async with conn.transaction():

                # ── CREATE SESSION ─────────────────────────────────────────────
                session_id = generate_id("SESSION")
                await conn.execute(
                    """
                    INSERT INTO session (
                        id, user_id, status, is_initial_session,
                        session_type, expected_cycles, expected_total_score,
                        started_at, last_activity_at
                    )
                    VALUES ($1, $2, 'active', TRUE, 'initial', 1, 700, NOW(), NOW())
                    """,
                    session_id,
                    user_id,
                )
                logger.info(f"✅ Initial session created: {session_id} for user {user_id}")

                # ── CREATE CYCLE ───────────────────────────────────────────────
                # subtopic_id, cycle_goal, cycle_level, cycle_boredom left NULL —
                # this cycle is template-driven, not subtopic-driven.
                cycle_id = generate_id("CYCLE")
                await conn.execute(
                    """
                    INSERT INTO session_cycle (
                        id, session_id, cycle_number, status,
                        started_at, template_interaction_ids
                    )
                    VALUES ($1, $2, 1, 'active', NOW(), $3)
                    """,
                    cycle_id,
                    session_id,
                    ordered_ids,
                )
                logger.info(
                    f"✅ Initial cycle created: {cycle_id} "
                    f"with {len(ordered_ids)} templated interactions"
                )

                # ── CREATE FIRST INTERACTION ───────────────────────────────────
                # iOS uses the returned interaction_id directly for submit-answer and
                # complete-interaction — no separate start-interaction call needed.
                interaction_id = generate_id("INT")
                first_brain_interaction_id = ordered_ids[0]
                await conn.execute(
                    """
                    INSERT INTO session_interaction (
                        id, session_id, cycle_id, brain_interaction_id,
                        interaction_number, status, started_at
                    )
                    VALUES ($1, $2, $3, $4, 1, 'active', NOW())
                    """,
                    interaction_id,
                    session_id,
                    cycle_id,
                    first_brain_interaction_id,
                )
                logger.info(
                    f"✅ First interaction created: {interaction_id} → {first_brain_interaction_id}"
                )

        # ── SUCCESS RESPONSE ───────────────────────────────────────────────────
        return {
            "success": True,
            "session_id": session_id,
            "cycle_id": cycle_id,
            "interaction_id": interaction_id,
            "brain_interaction_id": first_brain_interaction_id,
            "total_interactions": 7,
        }

    except Exception as e:
        logger.error(f"❌ Initial session start failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await pool.close()
