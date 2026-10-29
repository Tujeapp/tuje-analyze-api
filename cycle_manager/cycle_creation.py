# ============================================================================
# cycle_manager/cycle_creation.py - Cycle Creation Logic
# ============================================================================

import asyncpg
import json
import logging
from typing import Dict, Any, List
from models import InteractionCandidate, InsufficientInteractionsError
from session_context import SessionContext
from interaction_search import find_best_subtopic_with_fallback
from interaction_search_intent import find_best_intent_interactions_with_fallback
from helpers import generate_id
from notion_steps.engine import build_notion_cycle
from .interaction_selection import select_cycle_interactions
from .interaction_dispatcher import resolve_mode_and_purpose

logger = logging.getLogger(__name__)


async def start_new_cycle(
    session_id: str,
    context: SessionContext,
    cycle_number: int,
    cycle_goal: str,
    cycle_boredom: float,
    cycle_level: int,
    interaction_user_level: int,
    session_mood: str,
    db_pool: asyncpg.Pool
) -> Dict[str, Any]:
    """
    Start a new cycle with optimized interaction search
    
    Args:
        session_id: Current session ID
        context: Pre-loaded SessionContext
        cycle_number: Cycle number (1-7)
        cycle_goal: "story", "notion", or "intent"
        cycle_boredom: Calculated cycle boredom rate (0-1)
        cycle_level: Calculated cycle level (0-500)
        interaction_user_level: Current interaction user level
        session_mood: Session mood type
        db_pool: Database connection pool
    
    Returns:
        Dict with cycle_id, subtopic_id, ordered_interactions, first_interaction_id
    
    Raises:
        InsufficientInteractionsError: If the STORY search cannot find ≥7
            interactions. A notion cycle with no buildable step plan, or an
            intent search that fails this way, falls back to a story cycle
            instead of raising (see below); only the story search's own
            failure propagates.
    """
    
    logger.info(f"""
    🔄 Starting Cycle {cycle_number}:
    - Session: {session_id}
    - Goal: {cycle_goal}
    - Level: {cycle_level}
    - Boredom: {cycle_boredom:.2f}
    """)
    
    # Find interactions (goal-branched).
    # The notion that drives the cycle (notion cycles only); persisted on the
    # cycle so the runtime curator can filter on the SAME notion.
    target_notion_id = None
    interactions = None
    ordered_ids = None
    subtopic_id = None
    notion_step_pool = None  # JSON text; notion cycles only, NULL otherwise

    # Both fallbacks below run BEFORE the session_cycle INSERT, so a fallen-back
    # row records cycle_goal='story' and target_notion_id=NULL, and
    # resolve_mode_and_purpose sees 'story'. The story search is NOT wrapped:
    # if it fails too, it raises exactly as before.

    # NOTION: built from notion steps on ONE connection. The plan is already
    # ordered, so select_cycle_interactions is skipped for this path.
    # No plan (or any build error) → fall back to a STORY cycle.
    if cycle_goal == "notion":
        try:
            async with db_pool.acquire() as conn:
                notion_plan = await build_notion_cycle(
                    conn, user_id=context.user_id, cycle_level=interaction_user_level, slots=7)
                if notion_plan is not None:
                    subtopic_id = await conn.fetchval(
                        "SELECT subtopic_id FROM brain_interaction WHERE id = $1",
                        notion_plan["ordered_ids"][0])
        except Exception:
            logger.error(
                f"Cycle {cycle_number} 'notion' step build raised (user={context.user_id}, "
                f"session={session_id}, cycle_number={cycle_number})",
                exc_info=True,
            )
            notion_plan = None
            subtopic_id = None
        if notion_plan is None:
            logger.warning(
                f"Cycle {cycle_number} 'notion' step build found no plan — "
                f"falling back to 'story' (user={context.user_id}, session={session_id}, "
                f"cycle_number={cycle_number}, level={interaction_user_level})"
            )
            cycle_goal = "story"
        else:
            ordered_ids = notion_plan["ordered_ids"]
            target_notion_id = notion_plan["notion_id"]
            notion_step_pool = json.dumps(notion_plan["notion_step_pool"])

    # HOTFIX: an intent search that can't build (InsufficientInteractionsError)
    # must not crash the session. Fall back to a STORY cycle.
    elif cycle_goal == "intent":
        try:
            interactions = await find_best_intent_interactions_with_fallback(
                db_pool=db_pool,
                interaction_user_level=interaction_user_level,
                cycle_boredom=cycle_boredom,
                session_mood=session_mood,
                context=context,
                cycle_goal=cycle_goal
            )
        except InsufficientInteractionsError as e:
            logger.warning(
                f"Cycle {cycle_number} '{cycle_goal}' search could not build — "
                f"falling back to 'story' (user={context.user_id}, session={session_id}, "
                f"cycle_number={cycle_number}, original_goal={cycle_goal}): {e}"
            )
            cycle_goal = "story"
            target_notion_id = None

    if ordered_ids is None and interactions is None:
        interactions = await find_best_subtopic_with_fallback(
            db_pool=db_pool,
            interaction_user_level=interaction_user_level,
            cycle_boredom=cycle_boredom,
            session_mood=session_mood,
            context=context,
            cycle_goal=cycle_goal
        )
    
    cycle_id = generate_id("CYCLE")

    if ordered_ids is None:
        subtopic_id = interactions[0].subtopic_id
        # Select ordered sequence of 7 interactions
        ordered_ids = await select_cycle_interactions(
            interactions=interactions,
            cycle_level=cycle_level,
            cycle_boredom=cycle_boredom,
            cycle_goal=cycle_goal
        )

    # Save cycle to database (ordered_ids persisted as candidate_pool_ids
    # so advance_to_next_interaction can read them back later).
    await db_pool.execute("""
        INSERT INTO session_cycle (
            id, session_id, cycle_number, subtopic_id,
            status, started_at, cycle_level, cycle_boredom, cycle_goal,
            candidate_pool_ids, target_notion_id, notion_step_pool
        ) VALUES ($1, $2, $3, $4, 'active', NOW(), $5, $6, $7, $8, $9, $10::jsonb)
    """, cycle_id, session_id, cycle_number, subtopic_id,
        cycle_level, cycle_boredom, cycle_goal, ordered_ids, target_notion_id,
        notion_step_pool)
    
    # Save first interaction as active
    first_interaction_id = generate_id("INT")
    answer_mode, button_purpose = await resolve_mode_and_purpose(
        db_pool, context.user_id, cycle_goal, brain_interaction_id=ordered_ids[0])
    await db_pool.execute("""
        INSERT INTO session_interaction (
            id, session_id, cycle_id, brain_interaction_id,
            interaction_number, status, started_at, answer_mode, button_purpose
        ) VALUES ($1, $2, $3, $4, 1, 'active', NOW(), $5, $6)
    """, first_interaction_id, session_id, cycle_id, ordered_ids[0],
        answer_mode, button_purpose)

    # Cycle-1 backfill (NULL-marker notion model): the carry-forward / seed wrote this
    # session's notion rows with session_id NULL at session start (session_id did not
    # exist yet). Now that cycle 1 confirms the session is live, stamp those NULL rows
    # with the real session_id so they become this session's permanent history — which
    # next session's carry-forward reads as the "previous session". Runs once per session.
    if cycle_number == 1:
        backfilled = await db_pool.execute("""
            UPDATE session_notion
            SET session_id = $1, updated_at = NOW()
            WHERE user_id = $2 AND session_id IS NULL
        """, session_id, context.user_id)
        logger.info(f"Cycle-1 notion backfill: stamped NULL-session rows with {session_id} for user {context.user_id} ({backfilled})")

    logger.info(f"✅ Cycle {cycle_number} started successfully")
    
    return {
        "cycle_id": cycle_id,
        "subtopic_id": subtopic_id,
        "ordered_interactions": ordered_ids,
        "first_interaction_id": first_interaction_id,
        "total_interactions": len(ordered_ids),
        "answer_mode": answer_mode,
        "button_purpose": button_purpose,
        "target_notion_id": target_notion_id,
        # The EFFECTIVE goal — 'story' if a notion/intent search fell back above.
        # Callers must report this, not the goal they passed in.
        "cycle_goal": cycle_goal,
    }


async def advance_to_next_interaction(
    cycle_id: str,
    session_id: str,
    current_interaction_number: int,
    ordered_interaction_ids: List[str],
    db_pool: asyncpg.Pool,
    answer_mode: str = None,
    button_purpose: str = None
) -> Dict[str, Any]:
    """
    Advance to the next interaction in the cycle
    
    Args:
        cycle_id: Current cycle ID
        session_id: Current session ID
        current_interaction_number: Just completed interaction number (1-7)
        ordered_interaction_ids: Pre-selected ordered list of 7 interaction IDs
        db_pool: Database connection pool
    
    Returns:
        Dict with next_interaction_id and interaction_number, or cycle_complete flag
    """
    
    next_number = current_interaction_number + 1
    
    if next_number > 7:
        # Cycle is complete
        logger.info(f"Cycle {cycle_id} complete - all 7 interactions finished")
        return {
            "cycle_complete": True,
            "cycle_id": cycle_id
        }
    
    # Get next interaction ID from ordered list
    next_brain_interaction_id = ordered_interaction_ids[next_number - 1]
    
    # Create next interaction record
    next_interaction_id = generate_id("INT")
    
    await db_pool.execute("""
        INSERT INTO session_interaction (
            id, session_id, cycle_id, brain_interaction_id,
            interaction_number, status, started_at, answer_mode, button_purpose
        ) VALUES ($1, $2, $3, $4, $5, 'active', NOW(), $6, $7)
    """, next_interaction_id, session_id, cycle_id,
        next_brain_interaction_id, next_number, answer_mode, button_purpose)
    
    logger.info(f"Advanced to interaction {next_number}/7 in cycle {cycle_id}")
    
    return {
        "cycle_complete": False,
        "next_interaction_id": next_interaction_id,
        "brain_interaction_id": next_brain_interaction_id,
        "interaction_number": next_number
    }
