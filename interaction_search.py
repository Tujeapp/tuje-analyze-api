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
    
    from .helpers import get_mood_types
    
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
    db_pool: asyncpg.Pool,
    interaction_user_level: int,
    cycle_boredom: float,
    mood_types: List[str],
    search_mode: str,  # "new_only" or "new_and_seen"
    context: SessionContext,
    cycle_goal: str
) -> List[InteractionCandidate]:
    """
    Core search logic
    
    Returns list of InteractionCandidate with combinations calculated
    """
    
    async with db_pool.acquire() as conn:
        level_min = max(0, interaction_user_level - 50)
        level_max = interaction_user_level + 50
        
        # Subtopic filter based on search mode
        subtopic_filter = """
            AND s.id NOT IN (SELECT unnest($7::varchar[]))
        """ if search_mode == "new_only" else ""
        
        query = f"""
            WITH 
            user_mastered_notions AS (
                SELECT notion_id FROM session_notion
                WHERE user_id = $4 AND notion_rate >= 0.8
            ),
            target_subtopics AS (
                SELECT s.id as subtopic_id FROM brain_subtopic s
                WHERE s.live = true 
                AND s.level_from >= $1
                AND s.boredom_rate >= $3 
                {subtopic_filter}
            ),
            interactions_with_all_notions_mastered AS (
                SELECT i.id as interaction_id FROM brain_interaction i
                WHERE i.subtopic_id IN (SELECT subtopic_id FROM target_subtopics)
                AND i.level_from BETWEEN $1 AND $2
                AND i.boredom_rate >= $3
                AND i.type = ANY($5::varchar[])
                AND i.is_live = true
                -- ALL expected notions must be mastered
                AND NOT EXISTS (
                    SELECT 1 FROM brain_interaction_notion bin
                    WHERE bin.interaction_id = i.id
                    AND bin.notion_id NOT IN (SELECT notion_id FROM user_mastered_notions)
                )
                -- Ensure has at least one notion
                AND EXISTS (
                    SELECT 1 FROM brain_interaction_notion bin
                    WHERE bin.interaction_id = i.id
                )
            ),
            interaction_counts AS (
                SELECT i.subtopic_id, COUNT(*) as interaction_count
                FROM brain_interaction i
                WHERE i.id IN (SELECT interaction_id FROM interactions_with_all_notions_mastered)
                GROUP BY i.subtopic_id
                HAVING COUNT(*) >= 7
            ),
            best_subtopic AS (
                SELECT subtopic_id FROM interaction_counts
                ORDER BY interaction_count DESC
                LIMIT 1
            )
            SELECT 
                i.id, i.subtopic_id, i.boredom_rate, i.is_entry_point, i.level_from,
                COALESCE(
                    array_agg(DISTINCT bii.intent_id) FILTER (WHERE bii.intent_id IS NOT NULL), 
                    ARRAY[]::varchar[]
                ) as intent_ids
            FROM brain_interaction i
            LEFT JOIN brain_interaction_intent bii ON i.id = bii.interaction_id
            WHERE i.id IN (SELECT interaction_id FROM interactions_with_all_notions_mastered)
            AND i.subtopic_id = (SELECT subtopic_id FROM best_subtopic)
            GROUP BY i.id, i.subtopic_id, i.boredom_rate, i.is_entry_point, i.level_from
        """
        
        seen_array = list(context.seen_subtopics) if search_mode == "new_only" else []
        
        rows = await conn.fetch(
            query, level_min, level_max, cycle_boredom,
            context.user_id, mood_types, cycle_goal, seen_array
        )
        
        # Convert to InteractionCandidate objects
        candidates = [
            InteractionCandidate(
                id=row['id'],
                subtopic_id=row['subtopic_id'],
                intent_ids=row['intent_ids'],
                boredom_rate=float(row['boredom_rate']),
                is_entry_point=row['is_entry_point'],
                level_from=row['level_from']
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
