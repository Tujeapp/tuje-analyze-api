# ============================================================================
# session_context.py - SessionContext and Combination Logic
# ============================================================================

import asyncpg
from dataclasses import dataclass
from typing import Set, List


@dataclass
class SessionContext:
    """Pre-loaded context for fast combination calculations"""
    user_id: str
    seen_subtopics: Set[str]
    seen_interaction_ids: Set[str]
    seen_intents: Set[str]
    
    @classmethod
    async def load(cls, user_id: str, db_pool) -> "SessionContext":
        """
        Load the user's recent activity context for combination calculations.

        Seen subtopics and intents look back 7 days (per the logic doc);
        seen interaction IDs look back 4 days (recent-repeat avoidance).
        """
        async with db_pool.acquire() as conn:
            # Subtopics from cycles completed in the last 7 days for this user.
            subtopic_rows = await conn.fetch(
                """
                SELECT DISTINCT sc.subtopic_id
                FROM session_cycle sc
                JOIN session s ON sc.session_id = s.id
                WHERE s.user_id = $1
                  AND sc.completed_at >= NOW() - INTERVAL '7 days'
                  AND sc.subtopic_id IS NOT NULL
                """,
                user_id,
            )
            seen_subtopics = {row["subtopic_id"] for row in subtopic_rows}

            # Interactions completed in the last 4 days for this user.
            interaction_rows = await conn.fetch(
                """
                SELECT DISTINCT si.brain_interaction_id
                FROM session_interaction si
                JOIN session s ON si.session_id = s.id
                WHERE s.user_id = $1
                  AND si.completed_at >= NOW() - INTERVAL '4 days'
                """,
                user_id,
            )
            seen_interaction_ids = {row["brain_interaction_id"] for row in interaction_rows}

            # Intents from interactions completed in the last 7 days for this
            # user. brain_interaction.intents is an ARRAY column — unnest it.
            intent_rows = await conn.fetch(
                """
                SELECT DISTINCT intent_id
                FROM session_interaction si
                JOIN session s ON si.session_id = s.id
                JOIN brain_interaction bi ON si.brain_interaction_id = bi.id
                CROSS JOIN LATERAL unnest(bi.intents) AS intent_id
                WHERE s.user_id = $1
                  AND si.completed_at >= NOW() - INTERVAL '7 days'
                  AND bi.intents IS NOT NULL
                """,
                user_id,
            )
            seen_intents = {row["intent_id"] for row in intent_rows}

        return cls(
            user_id=user_id,
            seen_subtopics=seen_subtopics,
            seen_interaction_ids=seen_interaction_ids,
            seen_intents=seen_intents,
        )
    
    def get_combination(self, interaction_id: str, subtopic_id: str, intent_ids: List[str]) -> int:
        """
        Fast O(1) combination calculation
        
        Combinations:
        1 (boredom 0.0): seen/seen/seen
        2 (boredom 0.1): seen/new/seen
        3 (boredom 0.3): seen/new/new
        4 (boredom 0.4): new/seen/seen
        5 (boredom 0.5): new/new/new
        """
        
        subtopic_status = "seen" if subtopic_id in self.seen_subtopics else "new"
        transcription_status = "seen" if interaction_id in self.seen_interaction_ids else "new"
        intent_status = "seen" if any(iid in self.seen_intents for iid in intent_ids) else "new"
        
        combination_map = {
            ("seen", "seen", "seen"): 1,
            ("seen", "new", "seen"): 2,
            ("seen", "new", "new"): 3,
            ("new", "seen", "seen"): 4,
            ("new", "new", "new"): 5,
        }
        
        return combination_map.get((subtopic_status, transcription_status, intent_status), 5)

