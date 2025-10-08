# ============================================================================
# cycle_manager/cycle_creation.py - Cycle Creation Logic
# ============================================================================

import asyncpg
import logging
from typing import Dict, Any, List
from models import InteractionCandidate
from session_context import SessionContext
from interaction_search import find_best_subtopic_with_fallback
from helpers import generate_id
from .interaction_selection import select_cycle_interactions

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
        InsufficientInteractionsError: If cannot find ≥7 interactions
    """
    
    logger.info(f"""
    🔄 Starting Cycle {cycle_number}:
    - Session: {session_id}
    - Goal: {cycle_goal}
    - Level: {cycle_level}
    - Boredom: {cycle_boredom:.2f}
    """)
    
    # Find interactions with progressive fallback
    interactions = await find_best_subtopic_with_fallback(
        db_pool=db_pool,
        interaction_user_level=interaction_user_level,
        cycle_boredom=cycle_boredom,
        session_mood=session_mood,
        context=context,
        cycle_goal=cycle_goal
    )
    
    cycle_id = generate_id("CYCLE")
    
    # Save cycle to database
    await db_pool.execute("""
        INSERT INTO session_cycle (
            id, session_id, cycle_number, subtopic_id,
            status, started_at, cycle_level, cycle_boredom, cycle_goal
        ) VALUES ($1, $2, $3, $4, 'active', NOW(), $5, $6, $7)
    """, cycle_id, session_id, cycle_number, interactions[0].subtopic_id,
        cycle_level, cycle_boredom, cycle_goal)
    
    # Select ordered sequence of 7 interactions
    ordered_ids = await select_cycle_interactions(
        interactions=interactions,
        cycle_level=cycle_level,
        cycle_boredom=cycle_boredom,
        cycle_goal=cycle_goal
    )
    
    # Save first interaction as active
    first_interaction_id = generate_id("INT")
    await db_pool.execute("""
        INSERT INTO session_interaction (
            id, session_id, cycle_id, brain_interaction_id,
            interaction_number, status, started_at
        ) VALUES ($1, $2, $3, $4, 1, 'active', NOW())
    """, first_interaction_id, session_id, cycle_id, ordered_ids[0])
    
    logger.info(f"✅ Cycle {cycle_number} started successfully")
    
    return {
        "cycle_id": cycle_id,
        "subtopic_id": interactions[0].subtopic_id,
        "ordered_interactions": ordered_ids,
        "first_interaction_id": first_interaction_id,
        "total_interactions": len(ordered_ids)
    }


async def advance_to_next_interaction(
    cycle_id: str,
    session_id: str,
    current_interaction_number: int,
    ordered_interaction_ids: List[str],
    db_pool: asyncpg.Pool
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
            interaction_number, status, started_at
        ) VALUES ($1, $2, $3, $4, $5, 'active', NOW())
    """, next_interaction_id, session_id, cycle_id, 
        next_brain_interaction_id, next_number)
    
    logger.info(f"Advanced to interaction {next_number}/7 in cycle {cycle_id}")
    
    return {
        "cycle_complete": False,
        "next_interaction_id": next_interaction_id,
        "brain_interaction_id": next_brain_interaction_id,
        "interaction_number": next_number
    }
