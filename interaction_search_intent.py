# ============================================================================
# interaction_search_intent.py - Intent-goal Interaction Search with Fallback
# ============================================================================
# Mirrors interaction_search_notion.py but for cycle_goal == "intent".
#
# Key differences from the notion search (per "Details of logic of session",
# intent-goal Part 2):
#   - Interactions are filtered by THE TOP INTENT from the intent list:
#       intents @> ARRAY[<top_intent>]::text[]
#     (the list is get_top_intents_list, sorted priority DESC / score ASC;
#      [0] = the top intent).
#   - >= 7 interactions IN TOTAL across the target subtopics (no best-subtopic CTE),
#     same as the notion search.
#
# DEFERRED (plumbing-first, mirroring how the notion search deferred ITS cross-filter):
#   - The "expected_notion contain notions with notion rate at least 0.8" mastered-notion
#     filter (intent Part 2) is NOT included yet. It requires a subquery against the
#     user's session_notion (their >= 0.8 notions). Added as a later refinement. The
#     intent filter is the defining one and is present.
#
# Ordering (first/next interaction, Parts 4-5, incl. same-subtopic-max-TWICE) is in
# interaction_selection.py (separate step); this file only builds the candidate POOL.
# ============================================================================

import asyncpg
import logging
from typing import List
from models import InteractionCandidate, InsufficientInteractionsError
from session_context import SessionContext
from intent_management import get_top_intents_list

logger = logging.getLogger(__name__)


async def find_best_intent_interactions_with_fallback(
    db_pool: asyncpg.Pool,
    interaction_user_level: int,
    cycle_boredom: float,
    session_mood: str,
    context: SessionContext,
    cycle_goal: str = "intent",
) -> List[InteractionCandidate]:
    """
    Progressive fallback to find >= 7 intent-filtered interactions (total).

    Phase 1: New subtopics, current boredom, current level
    Phase 2: New + seen subtopics
    Phase 3: Reduce boredom by 0.1 (up to 5 attempts)
    Phase 4: Reduce level by 50 (up to 3 attempts)

    The intent filter (top intent from the list) is constant across all phases.
    Raises InsufficientInteractionsError if all fallbacks fail OR if the intent list
    is empty (an intent-goal cycle with no intents is a genuine can't-build — and the
    cycle-goal selection's empty-intent exception should prevent reaching here in the
    normal case).
    """
    from helpers import get_mood_types

    # The defining input: the TOP intent from the list (priority DESC, score ASC).
    top = await get_top_intents_list(context.user_id, limit=1, db_pool=db_pool)
    if not top:
        logger.error(
            f"Intent-goal cycle for user {context.user_id} but the intent list is empty "
            f"— cannot build an intent search. (The empty-intent exception in cycle-goal "
            f"selection should normally prevent this.)"
        )
        raise InsufficientInteractionsError(
            "Intent-goal cycle requested but the intent list is empty."
        )
    top_intent = top[0]["intent_id"]
    logger.info(f"🔍 Intent search: top intent = {top_intent}")

    mood_types = get_mood_types(session_mood)
    current_boredom = cycle_boredom
    current_level = interaction_user_level
    attempt = 0

    # Phase 1: New only
    logger.info(f"🔍 Phase 1: New subtopics, level={current_level}, boredom={current_boredom:.2f}")
    candidates = await search_intent_interactions(
        db_pool, current_level, current_boredom, mood_types,
        "new_only", context, top_intent
    )
    if len(candidates) >= 7:
        logger.info(f"✅ Found {len(candidates)} intent interactions (new subtopics)")
        return candidates

    attempt += 1

    # Phase 2: New + seen
    logger.info(f"🔍 Phase 2: New + seen subtopics")
    candidates = await search_intent_interactions(
        db_pool, current_level, current_boredom, mood_types,
        "new_and_seen", context, top_intent
    )
    if len(candidates) >= 7:
        logger.info(f"✅ Found {len(candidates)} intent interactions (new + seen)")
        return candidates

    attempt += 1

    # Phase 3: Boredom fallbacks
    logger.warning(f"⚠️ Intent search: starting boredom fallbacks...")
    for i in range(5):
        current_boredom = max(0.0, cycle_boredom - (0.1 * (i + 1)))
        logger.info(f"🔍 Attempt {attempt + 1}: boredom={current_boredom:.2f}")
        candidates = await search_intent_interactions(
            db_pool, current_level, current_boredom, mood_types,
            "new_and_seen", context, top_intent
        )
        if len(candidates) >= 7:
            logger.info(f"✅ Found {len(candidates)} (boredom={current_boredom:.2f})")
            return candidates
        attempt += 1

    # Phase 4: Level fallbacks
    logger.error(f"❌ Intent boredom fallbacks exhausted. Starting level fallbacks...")
    current_boredom = 0.0
    for i in range(3):
        current_level = max(0, interaction_user_level - (50 * (i + 1)))
        logger.warning(f"🔍 Attempt {attempt + 1}: level={current_level}")
        candidates = await search_intent_interactions(
            db_pool, current_level, current_boredom, mood_types,
            "new_and_seen", context, top_intent
        )
        if len(candidates) >= 7:
            logger.warning(f"✅ Level fallback success: {len(candidates)} at level {current_level}")
            return candidates
        attempt += 1

    # All fallbacks failed
    logger.error(f"""
    ❌ CRITICAL: Could not find >= 7 intent interactions after {attempt} attempts
    - User: {context.user_id}
    - Top intent: {top_intent}
    - Original level: {interaction_user_level}
    - Final level tried: {current_level}
    - Found: {len(candidates)} interactions
    """)
    raise InsufficientInteractionsError(
        f"Could not find >= 7 intent interactions after {attempt} attempts. "
        f"Found {len(candidates)} (top intent {top_intent})."
    )


async def search_intent_interactions(
    db_pool,
    interaction_user_level: int,
    cycle_boredom: float,
    mood_types: List[str],
    search_mode: str,  # "new_only" or "new_and_seen"
    context: SessionContext,
    top_intent: str,
) -> List[InteractionCandidate]:
    """
    Search for intent-filtered interactions across the target subtopics.

    Intent-cycle filter shape (Part 2):
      - interactions live, in a live subtopic from the subtopic list (Part 1)
      - intents (expected intents) contains the top intent from the list
      - level_from within [user_level - 50, user_level + 50]
      - boredom >= cycle_boredom
      - type name (lowercase) matches one of the requested mood types
      - >= 7 IN TOTAL (checked by the caller via len(candidates)); no per-subtopic
        count, no best-subtopic restriction.

    DEFERRED: the "expected_notion contains notions with rate >= 0.8" mastered-notion
    filter (Part 2) — added later (needs a session_notion subquery for the user's
    mastered notions).
    """
    level_min = max(0, interaction_user_level - 50)
    level_max = interaction_user_level + 50
    mood_types_lower = [m.lower() for m in mood_types]

    seen_array = list(context.seen_subtopics) if search_mode == "new_only" else []
    subtopic_filter = "AND s.id != ALL($6::varchar[])" if search_mode == "new_only" else ""

    query = f"""
        WITH target_subtopics AS (
            SELECT s.id AS subtopic_id
            FROM brain_subtopic s
            WHERE s.live = true
              AND s.level_from >= $1
              AND s.boredom >= $3
              {subtopic_filter}
        )
        SELECT
            i.id,
            i.subtopic_id,
            i.boredom,
            i.entry_point,
            i.level_from,
            COALESCE(i.intents, ARRAY[]::varchar[]) AS intent_ids,
            i.transcription_fr
        FROM brain_interaction i
        JOIN brain_interaction_type bit ON i.interaction_type_id = bit.id
        WHERE i.live = true
          AND i.subtopic_id IN (SELECT subtopic_id FROM target_subtopics)
          AND i.intents @> ARRAY[$5]::text[]
          AND i.level_from BETWEEN $1 AND $2
          AND i.boredom >= $3
          AND LOWER(bit.name) = ANY($4::varchar[])
    """

    async with db_pool.acquire() as conn:
        if search_mode == "new_only":
            rows = await conn.fetch(
                query,
                level_min, level_max, cycle_boredom,
                mood_types_lower, top_intent, seen_array
            )
        else:
            rows = await conn.fetch(
                query,
                level_min, level_max, cycle_boredom,
                mood_types_lower, top_intent
            )

    candidates = [
        InteractionCandidate(
            id=row["id"],
            subtopic_id=row["subtopic_id"],
            intent_ids=list(row["intent_ids"]),
            boredom_rate=float(row["boredom"]),
            is_entry_point=bool(row["entry_point"]),
            level_from=int(row["level_from"]) if row["level_from"] is not None else 0,
            transcription_fr=row["transcription_fr"] or "",
        )
        for row in rows
    ]

    for candidate in candidates:
        candidate.combination = context.get_combination(
            candidate.id, candidate.subtopic_id, candidate.transcription_fr, candidate.intent_ids
        )

    candidates.sort(key=lambda x: (x.combination, x.boredom_rate))

    return candidates
