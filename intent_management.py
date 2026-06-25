# ============================================================================
# intent_management.py - Intent list management for intent-goal cycles
# ============================================================================
# Parallel to notion_management.py, for the `intent` cycle goal.
#
# Per TuJe_Session_RampUp_and_Cycle_Goal_Logic.md §7: a session_intents table
# holds one row per intent the user has encountered (intent_score,
# intent_priority_score). The "list of intents" for an intent cycle is that
# table sorted priority DESC, score ASC, top N.
#
# DEFERRED (per §7/§8, same dependencies as notion's Moment 2):
#   - Population of session_intents (intent_score / intent_priority_score) happens
#     as the user completes interactions carrying an intent — needs the answering
#     system (a separate workstream). Until then, session_intents is empty and the
#     list is empty (the intent search then raises cleanly — correct plumbing).
#   - The intent_score / intent_priority_score FORMULAS are deferred (§8). This
#     module only sorts whatever values are present.
# ============================================================================

import asyncpg
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


# ============================================================================
# LIST OF TOP INTENTS (for intent-goal cycle search)
# ============================================================================

async def get_top_intents_list(
    user_id: str,
    limit: int = 10,
    db_pool: asyncpg.Pool = None
) -> List[Dict[str, Any]]:
    """
    Get the list of top intents for an intent-goal cycle.

    Per §7: sort session_intents by intent_priority_score DESC (primary), then
    intent_score ASC (tiebreaker — lowest score first = most in need of
    vocabulary practice). Take the top `limit`.

    Note: unlike the notion list, there is NO 0<score<1 exclusion — §7 specifies a
    plain sort-and-take. (Intent score/priority formulas are deferred per §8; this
    function sorts whatever values are present.)

    Args:
        user_id: User ID
        limit: Maximum number of intents to return
        db_pool: Database connection pool

    Returns:
        List of intent dicts: intent_id, intent_name, intent_score, priority_score
    """
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                si.intent_id,
                si.intent_score,
                si.intent_priority_score,
                bi.name
            FROM session_intents si
            JOIN brain_intent bi ON si.intent_id = bi.id
            WHERE si.user_id = $1
            ORDER BY
                si.intent_priority_score DESC,
                si.intent_score ASC
            LIMIT $2
        """, user_id, limit)

        intents = [
            {
                "intent_id": row['intent_id'],
                "intent_name": row['name'],
                "intent_score": float(row['intent_score'] or 0),
                "priority_score": float(row['intent_priority_score'] or 0),
            }
            for row in rows
        ]

        logger.debug(f"Found {len(intents)} top intents for user {user_id}")
        return intents
