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
from pydantic import BaseModel

from user_routes import get_current_user, ONBOARDING_PHASES
from helpers import generate_id

logger = logging.getLogger(__name__)

router = APIRouter()


class CompleteInitialInteractionRequest(BaseModel):
    session_id: str
    cycle_id: str
    interaction_id: str  # accepted for logging; submit-answer already completed this row

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

                # ── ADVANCE ONBOARDING PHASE ──────────────────────────────────
                # Only move forward — if user is already past this phase, leave it.
                # NOTE: This guard allows forward-skip (e.g., not_started →
                # initial_session_started). This is intentional for the current
                # single-screen form (D17). When the form is split into two screens
                # (D19, M4 part 2 iOS work), change `<` to `== target_idx - 1`
                # for strict one-step.
                current_phase = current_user.get("onboarding_phase", "not_started")
                target_phase = "initial_session_started"
                if current_phase not in ONBOARDING_PHASES:
                    logger.error(
                        f"❌ Corrupt onboarding_phase '{current_phase}' for user {user_id}; skipping phase update"
                    )
                elif ONBOARDING_PHASES.index(current_phase) < ONBOARDING_PHASES.index(target_phase):
                    await conn.execute(
                        """
                        UPDATE brain_user
                        SET onboarding_phase = $1, updated_at = NOW()
                        WHERE id = $2
                        """,
                        target_phase,
                        user_id,
                    )
                    logger.info(
                        f"✅ Phase advanced: '{current_phase}' → '{target_phase}' for user {user_id}"
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


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/initial-session/complete-interaction
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/complete-interaction")
async def complete_initial_interaction(
    request: CompleteInitialInteractionRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Advance an initial session to the next templated interaction.

    Submit-answer already handles all scoring and marks the current interaction
    'completed'. This endpoint reads the post-submit-answer state and either:
      A) Marks the session complete (when the single cycle finished after interaction 7).
      B) Creates the next session_interaction row from template_interaction_ids.
      C) Returns 409 if the cycle is in an unexpected state.

    Does NOT touch: interaction_score, completed_interactions, cycle data, or
    the just-completed interaction row (request.interaction_id). Submit-answer
    owns all of that.
    """
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:

            # ── READ CYCLE STATE ───────────────────────────────────────────────
            # By the time iOS calls this, submit-answer has already:
            #   - set session_interaction.status = 'completed'
            #   - recounted session_cycle.completed_interactions
            #   - if interaction 7: set session_cycle.status = 'completed' + cycle_score etc.
            cycle = await conn.fetchrow(
                """
                SELECT status, completed_interactions, template_interaction_ids
                FROM session_cycle
                WHERE id = $1
                """,
                request.cycle_id,
            )

            if cycle is None:
                return JSONResponse(
                    status_code=404,
                    content={"success": False, "error": "cycle_not_found"},
                )

            cycle_status = cycle["status"]
            completed_interactions = cycle["completed_interactions"] or 0
            template_ids = cycle["template_interaction_ids"]

            logger.info(
                f"📋 Advance requested: cycle={request.cycle_id} "
                f"status={cycle_status} completed={completed_interactions} "
                f"last_interaction={request.interaction_id}"
            )

            # ── CASE A: CYCLE COMPLETE — initial session is finished ───────────
            # An initial session has exactly 1 cycle. When the cycle is 'completed'
            # (set by submit-answer after interaction 7), the whole session is done.
            if cycle_status == "completed":
                # Compute session score from the 7 completed interaction rows.
                # AVG(INTEGER) returns NUMERIC in Postgres; cast to INTEGER after ROUND.
                # submit-answer has already written bonus-malus-adjusted scores to all rows.
                session_score = await conn.fetchval(
                    """
                    SELECT ROUND(AVG(interaction_score))::INTEGER
                    FROM session_interaction
                    WHERE session_id = $1 AND status = 'completed'
                    """,
                    request.session_id,
                )
                # Guard: AVG returns NULL if no rows match — shouldn't happen here, but defensive.
                if session_score is None:
                    session_score = 0

                # Atomic: mark session complete + advance onboarding phase together
                # NOTE: This guard allows forward-skip (e.g., level_selected →
                # initial_session_completed). This is intentional for the current
                # single-screen form (D17). When the form is split into two screens
                # (D19, M4 part 2 iOS work), change `<` to `== target_idx - 1`
                # for strict one-step.
                user_id = str(current_user["id"])
                current_phase = current_user.get("onboarding_phase", "not_started")
                target_phase = "initial_session_completed"

                async with conn.transaction():
                    await conn.execute(
                        """
                        UPDATE session
                        SET status = 'completed',
                            completed_at = NOW(),
                            last_activity_at = NOW(),
                            session_score = $2
                        WHERE id = $1
                        """,
                        request.session_id,
                        session_score,
                    )

                    if current_phase not in ONBOARDING_PHASES:
                        logger.error(
                            f"❌ Corrupt onboarding_phase '{current_phase}' for user {user_id}; skipping phase update"
                        )
                    elif ONBOARDING_PHASES.index(current_phase) < ONBOARDING_PHASES.index(target_phase):
                        await conn.execute(
                            """
                            UPDATE brain_user
                            SET onboarding_phase = $1, updated_at = NOW()
                            WHERE id = $2
                            """,
                            target_phase,
                            current_user["id"],
                        )
                        logger.info(
                            f"✅ Phase advanced: '{current_phase}' → '{target_phase}' for user {user_id}"
                        )

                logger.info(f"✅ Initial session complete: {request.session_id} (session_score={session_score})")
                return {
                    "success": True,
                    "session_complete": True,
                    "next_interaction_id": None,
                    "next_brain_interaction_id": None,
                    "interaction_number": None,
                    "session_score": session_score,
                }

            # ── CASE C: UNEXPECTED CYCLE STATUS ───────────────────────────────
            if cycle_status != "active":
                return JSONResponse(
                    status_code=409,
                    content={
                        "success": False,
                        "error": "cycle_not_active",
                        "detail": f"Cycle status is '{cycle_status}'",
                    },
                )

            # ── CASE B: CYCLE ACTIVE — create next templated interaction ───────
            # completed_interactions is 0-based index of the next template entry:
            # if 3 interactions are done, index 3 in template_ids is the next one.
            next_index = completed_interactions

            # Defensive guard: should never trigger if submit-answer closed the
            # cycle correctly at 7, but protects against inconsistent state.
            if template_ids is None or next_index >= len(template_ids) or next_index >= 7:
                logger.error(
                    f"❌ Template exhausted: cycle={request.cycle_id} "
                    f"next_index={next_index} "
                    f"template_len={len(template_ids) if template_ids else 0}"
                )
                return JSONResponse(
                    status_code=500,
                    content={"success": False, "error": "template_exhausted"},
                )

            next_brain_interaction_id = template_ids[next_index]
            new_interaction_id = generate_id("INT")
            interaction_number = completed_interactions + 1  # 1-based position for iOS

            await conn.execute(
                """
                INSERT INTO session_interaction (
                    id, session_id, cycle_id, brain_interaction_id,
                    interaction_number, status, started_at
                )
                VALUES ($1, $2, $3, $4, $5, 'active', NOW())
                """,
                new_interaction_id,
                request.session_id,
                request.cycle_id,
                next_brain_interaction_id,
                interaction_number,
            )

            await conn.execute(
                """
                UPDATE session SET last_activity_at = NOW() WHERE id = $1
                """,
                request.session_id,
            )

            logger.info(
                f"✅ Advanced to interaction {interaction_number}: "
                f"{new_interaction_id} → {next_brain_interaction_id}"
            )

            return {
                "success": True,
                "session_complete": False,
                "next_interaction_id": new_interaction_id,       # session_interaction PK for submit/complete calls
                "next_brain_interaction_id": next_brain_interaction_id,  # brain_interaction id for video fetch
                "interaction_number": interaction_number,
            }

    except Exception as e:
        logger.error(f"❌ Initial session complete-interaction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await pool.close()
