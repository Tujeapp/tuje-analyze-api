# ============================================================================
# interaction_search.py - Interaction Search with Fallback
# ============================================================================

import asyncpg
import logging
from typing import List
from models import InteractionCandidate, InsufficientInteractionsError
from session_context import SessionContext

logger = logging.getLogger(__name__)


async def find_best_subtopic_with_fallback(
    db_pool: asyncpg.Pool,
    interaction_user_level: int,
    cycle_boredom: float,
    session_mood: str,
    context: SessionContext,
    cycle_goal: str = "story"
) -> List[InteractionCandidate]:
    """
    Progressive fallback strategy to find ≥7 interactions:
    
    Phase 1: New subtopics only, current boredom, current level
    Phase 2: New + seen subtopics, current boredom, current level
    Phase 3: Reduce boredom by 0.1 (up to 5 attempts)
    Phase 4: Reduce level by 50 (up to 3 attempts)
    
    Raises InsufficientInteractionsError if all fallbacks fail
    """
    
    from helpers import get_mood_types
    
    mood_types = get_mood_types(session_mood)
    current_boredom = cycle_boredom
    current_level = interaction_user_level
    attempt = 0
    
    # Phase 1: New only
    logger.info(f"🔍 Phase 1: New subtopics, level={current_level}, boredom={current_boredom:.2f}")
    candidates = await search_interactions(
        db_pool, current_level, current_boredom, mood_types,
        "new_only", context, cycle_goal
    )
    if len(candidates) >= 7:
        logger.info(f"✅ Found {len(candidates)} interactions (new subtopics)")
        return candidates
    
    attempt += 1
    
    # Phase 2: New + seen
    logger.info(f"🔍 Phase 2: New + seen subtopics")
    candidates = await search_interactions(
        db_pool, current_level, current_boredom, mood_types,
        "new_and_seen", context, cycle_goal
    )
    if len(candidates) >= 7:
        logger.info(f"✅ Found {len(candidates)} interactions (new + seen)")
        return candidates
    
    attempt += 1
    
    # Phase 3: Boredom fallbacks
    logger.warning(f"⚠️ Starting boredom fallbacks...")
    for i in range(5):
        current_boredom = max(0.0, cycle_boredom - (0.1 * (i + 1)))
        logger.info(f"🔍 Attempt {attempt + 1}: boredom={current_boredom:.2f}")
        
        candidates = await search_interactions(
            db_pool, current_level, current_boredom, mood_types,
            "new_and_seen", context, cycle_goal
        )
        if len(candidates) >= 7:
            logger.info(f"✅ Found {len(candidates)} (boredom={current_boredom:.2f})")
            return candidates
        attempt += 1
    
    # Phase 4: Level fallbacks
    logger.error(f"❌ Boredom fallbacks exhausted. Starting level fallbacks...")
    current_boredom = 0.0
    
    for i in range(3):
        current_level = max(0, interaction_user_level - (50 * (i + 1)))
        logger.warning(f"🔍 Attempt {attempt + 1}: level={current_level}")
        
        candidates = await search_interactions(
            db_pool, current_level, current_boredom, mood_types,
            "new_and_seen", context, cycle_goal
        )
        if len(candidates) >= 7:
            logger.warning(f"✅ Level fallback success: {len(candidates)} at level {current_level}")
            return candidates
        attempt += 1
    
    # All fallbacks failed
    logger.error(f"""
    ❌ CRITICAL: Could not find ≥7 interactions after {attempt} attempts
    - User: {context.user_id}
    - Original level: {interaction_user_level}
    - Final level tried: {current_level}
    - Cycle goal: {cycle_goal}
    - Found: {len(candidates)} interactions
    """)
    
    raise InsufficientInteractionsError(
        f"Could not find ≥7 interactions after {attempt} attempts. Found {len(candidates)}."
    )


async def search_interactions(
    db_pool,
    interaction_user_level: int,
    cycle_boredom: float,
    mood_types: List[str],
    search_mode: str,  # "new_only" or "new_and_seen"
    context: SessionContext,
    cycle_goal: str  # passed-through; not yet used (story-only in 1c).
                     # Phase 2/3 will branch query shape per goal.
) -> List[InteractionCandidate]:
    """
    Search for ≥7 interactions matching the cycle's requirements, in a single
    subtopic (the one with the most qualifying interactions).

    Story-cycle filter shape:
      - interactions live, in a live subtopic
      - level_from within [user_level - 50, user_level + 50]
      - boredom >= cycle_boredom
      - type name (lowercase) matches one of the requested mood types
      - all expected notions are mastered by the user (notion_rate >= 0.8)
      - has at least one expected notion
      - in a subtopic with >= 7 qualifying interactions
    """
    level_min = max(0, interaction_user_level - 50)
    level_max = interaction_user_level + 50

    # Lowercase mood types so the comparison against brain_interaction_type.name
    # works regardless of capitalization (helpers.py returns lowercase strings;
    # the DB stores capitalized names like "Conversation").
    mood_types_lower = [m.lower() for m in mood_types]

    # Build the seen-subtopics filter in Python, not SQL — array containment
    # is cleaner than IN with unnest. seen_array is passed as $7 only in
    # new_only mode; in new_and_seen mode there's no filter.
    seen_array = list(context.seen_subtopics) if search_mode == "new_only" else []
    subtopic_filter = "AND s.id != ALL($5::varchar[])" if search_mode == "new_only" else ""

    query = f"""
        WITH target_subtopics AS (
            SELECT s.id AS subtopic_id
            FROM brain_subtopic s
            WHERE s.live = true
              AND s.level_from >= $1
              AND s.boredom >= $3
              {subtopic_filter}
        ),
        qualifying_interactions AS (
            SELECT
                i.id,
                i.subtopic_id,
                i.boredom,
                i.entry_point,
                i.level_from,
                i.intents
            FROM brain_interaction i
            JOIN brain_interaction_type bit ON i.interaction_type_id = bit.id
            WHERE i.live = true
              AND i.subtopic_id IN (SELECT subtopic_id FROM target_subtopics)
              AND i.level_from BETWEEN $1 AND $2
              AND i.boredom >= $3
              AND LOWER(bit.name) = ANY($4::varchar[])
        ),
        interaction_counts AS (
            SELECT subtopic_id, COUNT(*) AS interaction_count
            FROM qualifying_interactions
            GROUP BY subtopic_id
            HAVING COUNT(*) >= 7
        ),
        best_subtopic AS (
            SELECT subtopic_id
            FROM interaction_counts
            ORDER BY interaction_count DESC
            LIMIT 1
        )
        SELECT
            qi.id,
            qi.subtopic_id,
            qi.boredom,
            qi.entry_point,
            qi.level_from,
            COALESCE(qi.intents, ARRAY[]::varchar[]) AS intent_ids
        FROM qualifying_interactions qi
        WHERE qi.subtopic_id = (SELECT subtopic_id FROM best_subtopic)
    """

    # NOTE: context.user_id and cycle_goal are NOT passed to the SQL query
    # because they're not currently referenced by it. Both will be re-introduced
    # later:
    #   - user_id: when the mastery filter is re-added for session_rank >= 2 (R11)
    #   - cycle_goal: when notion/intent goal branches are added (phase 2/3)
    # The function still accepts them so callers don't need to change.
    async with db_pool.acquire() as conn:
        if search_mode == "new_only":
            rows = await conn.fetch(
                query,
                level_min, level_max, cycle_boredom,
                mood_types_lower, seen_array
            )
        else:
            rows = await conn.fetch(
                query,
                level_min, level_max, cycle_boredom,
                mood_types_lower
            )

    candidates = [
        InteractionCandidate(
            id=row["id"],
            subtopic_id=row["subtopic_id"],
            intent_ids=list(row["intent_ids"]),
            boredom_rate=float(row["boredom"]),
            is_entry_point=bool(row["entry_point"]),
            level_from=int(row["level_from"]) if row["level_from"] is not None else 0,
        )
        for row in rows
    ]

    # Calculate combinations
    for candidate in candidates:
        candidate.combination = context.get_combination(
            candidate.id, candidate.subtopic_id, candidate.intent_ids
        )

    # Sort by combination, then boredom
    candidates.sort(key=lambda x: (x.combination, x.boredom_rate))

    return candidates
