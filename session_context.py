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
    async def load(cls, user_id: str, db_pool: asyncpg.Pool):
        """
        Load all seen data in ONE batch query
        
        Performance: ~0.1-0.3s
        """
        
        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("""
                WITH 
                seen_subtopics AS (
                    SELECT DISTINCT subtopic_id 
                    FROM session_cycle
                    WHERE user_id = $1
                    AND completed_at > NOW() - INTERVAL '7 days'
                    AND cycle_goal IN ('story', 'intent')
                ),
                seen_interactions AS (
                    SELECT DISTINCT brain_interaction_id 
                    FROM session_interaction
                    WHERE user_id = $1
                    AND completed_at > NOW() - INTERVAL '4 days'
                ),
                seen_intents AS (
                    SELECT DISTINCT bii.intent_id
                    FROM session_interaction si
                    JOIN brain_interaction_intent bii 
                        ON si.brain_interaction_id = bii.interaction_id
                    WHERE si.user_id = $1
                    AND si.completed_at > NOW() - INTERVAL '4 days'
                )
                SELECT 
                    (SELECT array_agg(subtopic_id) FROM seen_subtopics) as subtopics,
                    (SELECT array_agg(brain_interaction_id) FROM seen_interactions) as interactions,
                    (SELECT array_agg(intent_id) FROM seen_intents) as intents
            """, user_id)
            
            return cls(
                user_id=user_id,
                seen_subtopics=set(result['subtopics'] or []),
                seen_interaction_ids=set(result['interactions'] or []),
                seen_intents=set(result['intents'] or [])
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

