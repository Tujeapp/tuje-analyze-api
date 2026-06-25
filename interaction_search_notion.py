# ============================================================================
# interaction_search_notion.py - Notion-goal Interaction Search with Fallback
# ============================================================================
# Mirrors interaction_search.py (story) but for cycle_goal == "notion".
#
# Key differences from the story search (per "Details of logic of session",
# notion-goal Parts 1-2):
#   - Interactions are filtered by THE FIRST NOTION from the notion list:
#       expected_notion_id @> ARRAY[<first_notion>]::text[]
#     (the list is get_top_notions_list, sorted priority DESC, complexity DESC;
#      [0] = the first/top notion).
#   - >= 7 interactions IN TOTAL across the target subtopics — NOT >= 7 per
#     subtopic. So there is NO best_subtopic CTE; all qualifying interactions
#     across the subtopic list are returned, and the >= 7 check is on the total
#     (handled by the fallback wrapper via len(candidates) >= 7).
#
# Ordering (first/next interaction, Parts 4-5, incl. same-subtopic-max-twice)
# is deferred — this plumbing reuses select_cycle_interactions' existing
# non-story branch. This file only builds the candidate POOL.
# ============================================================================

import asyncpg
import logging
from typing import List
from models import InteractionCandidate, InsufficientInteractionsError
from session_context import SessionContext
from notion_management import get_top_notions_list

logger = logging.getLogger(__name__)


async def find_best_notion_interactions_with_fallback(
    db_pool: asyncpg.Pool,
    interaction_user_level: int,
    cycle_boredom: float,
    session_mood: str,
    context: SessionContext,
    cycle_goal: str = "notion",
) -> List[InteractionCandidate]:
    """
    Progressive fallback to find >= 7 notion-filtered interactions (total).

    Phase 1: New subtopics, current boredom, current level
    Phase 2: New + seen subtopics
    Phase 3: Reduce boredom by 0.1 (up to 5 attempts)
    Phase 4: Reduce level by 50 (up to 3 attempts)

    The notion filter (first notion from the list) is constant across all phases.
    Raises InsufficientInteractionsError if all fallbacks fail OR if the notion
    list is empty (a notion-goal cycle with no notions is a genuine can't-build —
    in the normal content state the list is always populated).
    """
    from helpers import get_mood_types

    # The defining input: the FIRST (top-priority) notion from the list.
    top = await get_top_notions_list(context.user_id, limit=1, db_pool=db_pool)
    if not top:
        logger.error(
            f"Notion-goal cycle for user {context.user_id} but the notion list is "
            f"empty — cannot build a notion search. (Expected only during content "
            f"authoring; in the normal state the list is always populated.)"
        )
        raise InsufficientInteractionsError(
            "Notion-goal cycle requested but the notion list is empty."
        )
    first_notion = top[0]["notion_id"]
    logger.info(f"🔍 Notion search: first notion = {first_notion}")

    mood_types = get_mood_types(session_mood)
    current_boredom = cycle_boredom
    current_level = interaction_user_level
    attempt = 0

    # Phase 1: New only
    logger.info(f"🔍 Phase 1: New subtopics, level={current_level}, boredom={current_boredom:.2f}")
    candidates = await search_notion_interactions(
        db_pool, current_level, current_boredom, mood_types,
        "new_only", context, first_notion
    )
    if len(candidates) >= 7:
        logger.info(f"✅ Found {len(candidates)} notion interactions (new subtopics)")
        return candidates

    attempt += 1

    # Phase 2: New + seen
    logger.info(f"🔍 Phase 2: New + seen subtopics")
    candidates = await search_notion_interactions(
        db_pool, current_level, current_boredom, mood_types,
        "new_and_seen", context, first_notion
    )
    if len(candidates) >= 7:
        logger.info(f"✅ Found {len(candidates)} notion interactions (new + seen)")
        return candidates

    attempt += 1

    # Phase 3: Boredom fallbacks
    logger.warning(f"⚠️ Notion search: starting boredom fallbacks...")
    for i in range(5):
        current_boredom = max(0.0, cycle_boredom - (0.1 * (i + 1)))
        logger.info(f"🔍 Attempt {attempt + 1}: boredom={current_boredom:.2f}")
        candidates = await search_notion_interactions(
            db_pool, current_level, current_boredom, mood_types,
            "new_and_seen", context, first_notion
        )
        if len(candidates) >= 7:
            logger.info(f"✅ Found {len(candidates)} (boredom={current_boredom:.2f})")
            return candidates
        attempt += 1

    # Phase 4: Level fallbacks
    logger.error(f"❌ Notion boredom fallbacks exhausted. Starting level fallbacks...")
    current_boredom = 0.0
    for i in range(3):
        current_level = max(0, interaction_user_level - (50 * (i + 1)))
        logger.warning(f"🔍 Attempt {attempt + 1}: level={current_level}")
        candidates = await search_notion_interactions(
            db_pool, current_level, current_boredom, mood_types,
            "new_and_seen", context, first_notion
        )
        if len(candidates) >= 7:
            logger.warning(f"✅ Level fallback success: {len(candidates)} at level {current_level}")
            return candidates
        attempt += 1

    # All fallbacks failed
    logger.error(f"""
    ❌ CRITICAL: Could not find >= 7 notion interactions after {attempt} attempts
    - User: {context.user_id}
    - First notion: {first_notion}
    - Original level: {interaction_user_level}
    - Final level tried: {current_level}
    - Found: {len(candidates)} interactions
    """)
    raise InsufficientInteractionsError(
        f"Could not find >= 7 notion interactions after {attempt} attempts. "
        f"Found {len(candidates)} (first notion {first_notion})."
    )


async def search_notion_interactions(
    db_pool,
    interaction_user_level: int,
    cycle_boredom: float,
    mood_types: List[str],
    search_mode: str,  # "new_only" or "new_and_seen"
    context: SessionContext,
    first_notion: str,
) -> List[InteractionCandidate]:
    """
    Search for notion-filtered interactions across the target subtopics.

    Notion-cycle filter shape (Part 2):
      - interactions live, in a live subtopic from the subtopic list (Part 1)
      - expected_notion_id contains the first notion from the list
      - level_from within [user_level - 50, user_level + 50]
      - boredom >= cycle_boredom
      - type name (lowercase) matches one of the requested mood types
      - >= 7 IN TOTAL (checked by the caller via len(candidates)); no per-subtopic
        count, no best-subtopic restriction.

    NOTE (plumbing scope): the spec's "expected_intent contains seen intents"
    filter (Part 2) is deferred with the rest of the intent system — added here
    only when the intent list is wired. The notion filter is the defining one and
    is present.
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
          AND i.expected_notion_id @> ARRAY[$5]::text[]
          AND i.level_from BETWEEN $1 AND $2
          AND i.boredom >= $3
          AND LOWER(bit.name) = ANY($4::varchar[])
    """

    async with db_pool.acquire() as conn:
        if search_mode == "new_only":
            rows = await conn.fetch(
                query,
                level_min, level_max, cycle_boredom,
                mood_types_lower, first_notion, seen_array
            )
        else:
            rows = await conn.fetch(
                query,
                level_min, level_max, cycle_boredom,
                mood_types_lower, first_notion
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
