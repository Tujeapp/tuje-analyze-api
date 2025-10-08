# ============================================================================
# cycle_calculations.py - Cycle Level and Boredom Calculations
# ============================================================================

import asyncpg
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def calculate_cycle_level(
    session_id: str,
    cycle_number: int,
    user_level: int,
    db_pool: asyncpg.Pool
) -> int:
    """
    Calculate the cycle level based on session/cycle history
    
    This is a simplified version - full implementation would follow
    the detailed logic from "Details of logic of session"
    
    Args:
        session_id: Current session ID
        cycle_number: Cycle number (1-7)
        user_level: Current user level
        db_pool: Database connection pool
    
    Returns:
        Cycle level (0-500, in increments of 50)
    """
    
    async with db_pool.acquire() as conn:
        if cycle_number == 1:
            # First cycle: base on last session data
            last_session = await conn.fetchrow("""
                SELECT session_level, session_level_direction, session_score
                FROM session
                WHERE user_id = (SELECT user_id FROM session WHERE id = $1)
                AND id != $1
                AND status = 'completed'
                ORDER BY completed_at DESC
                LIMIT 1
            """, session_id)
            
            if not last_session:
                # No previous session, use user level
                return user_level
            
            # Apply adjustment based on last session performance
            # (Simplified - full logic would check streak7, last session rate, etc.)
            adjustment = 0
            
            if last_session['session_level_direction'] == 'up':
                adjustment = 50
            elif last_session['session_level_direction'] == 'down':
                adjustment = -50
            
            new_level = last_session['session_level'] + adjustment
            new_level = max(0, min(500, new_level))  # Clamp to 0-500
            new_level = round(new_level / 50) * 50   # Round to nearest 50
            
            logger.debug(f"First cycle level: {new_level} (from last session: {last_session['session_level']})")
            return new_level
        
        else:
            # Not first cycle: base on last cycle in current session
            last_cycle = await conn.fetchrow("""
                SELECT cycle_level, cycle_score, completed_interactions
                FROM session_cycle
                WHERE session_id = $1
                AND cycle_number = $2
                AND status = 'completed'
            """, session_id, cycle_number - 1)
            
            if not last_cycle:
                return user_level
            
            # Calculate cycle rate
            cycle_rate = last_cycle['cycle_score'] / 700.0 if last_cycle['completed_interactions'] == 7 else 0
            
            # Adjust level based on performance
            adjustment = 0
            
            if cycle_rate >= 0.8:
                adjustment = 50  # Good performance, increase level
            elif cycle_rate < 0.6:
                adjustment = -50  # Poor performance, decrease level
            # else: stay at same level
            
            new_level = last_cycle['cycle_level'] + adjustment
            new_level = max(0, min(500, new_level))  # Clamp to 0-500
            new_level = round(new_level / 50) * 50   # Round to nearest 50
            
            logger.debug(f"Cycle {cycle_number} level: {new_level} (from cycle {cycle_number-1}: {last_cycle['cycle_level']}, rate: {cycle_rate:.2f})")
            return new_level


async def calculate_cycle_boredom(
    session_id: str,
    cycle_number: int,
    session_boredom: float,
    db_pool: asyncpg.Pool
) -> float:
    """
    Calculate cycle boredom rate
    
    Args:
        session_id: Current session ID
        cycle_number: Cycle number (1-7)
        session_boredom: Session-level boredom rate
        db_pool: Database connection pool
    
    Returns:
        Cycle boredom rate (0.0 - 1.0)
    """
    
    if cycle_number == 1:
        # First cycle: use session boredom
        logger.debug(f"First cycle boredom: {session_boredom:.2f} (from session)")
        return session_boredom
    
    async with db_pool.acquire() as conn:
        # Get last cycle data
        last_cycle = await conn.fetchrow("""
            SELECT cycle_boredom, cycle_score, completed_interactions
            FROM session_cycle
            WHERE session_id = $1
            AND cycle_number = $2
            AND status = 'completed'
        """, session_id, cycle_number - 1)
        
        if not last_cycle:
            return session_boredom
        
        # Calculate last cycle rate
        last_cycle_rate = last_cycle['cycle_score'] / 700.0 if last_cycle['completed_interactions'] == 7 else 0
        
        # Adjust boredom based on performance
        # Low performance = increase boredom (needs more variety)
        # High performance = decrease boredom (content is engaging)
        
        if last_cycle_rate < 0.4:
            coefficient = 1.5  # Struggling badly, increase boredom significantly
        elif last_cycle_rate < 0.6:
            coefficient = 1.25  # Struggling, increase boredom
        elif last_cycle_rate < 0.8:
            coefficient = 1.0  # Moderate, keep same boredom
        else:
            coefficient = 0.75  # Doing well, decrease boredom
        
        new_boredom = last_cycle['cycle_boredom'] * coefficient
        new_boredom = round(max(0.0, min(1.0, new_boredom)), 2)  # Clamp to 0.0-1.0
        
        logger.debug(f"Cycle {cycle_number} boredom: {new_boredom:.2f} (from {last_cycle['cycle_boredom']:.2f}, rate: {last_cycle_rate:.2f}, coef: {coefficient})")
        return new_boredom


async def calculate_cycle_goal(
    session_id: str,
    cycle_number: int,
    db_pool: asyncpg.Pool
) -> str:
    """
    Determine cycle goal based on patterns and history
    
    This is a simplified version - full implementation would follow
    modulo-based rotation logic
    
    Args:
        session_id: Current session ID
        cycle_number: Cycle number (1-7)
        db_pool: Database connection pool
    
    Returns:
        Cycle goal: "story", "notion", or "intent"
    """
    
    # Simplified rotation pattern
    # Full implementation would use modulo calculation
    
    rotation_pattern = {
        1: "story",
        2: "notion",
        3: "story",
        4: "intent",
        5: "story",
        6: "notion",
        7: "story"
    }
    
    goal = rotation_pattern.get(cycle_number, "story")
    
    logger.debug(f"Cycle {cycle_number} goal: {goal}")
    return goal


async def calculate_interaction_user_level(
    cycle_id: str,
    interaction_number: int,
    cycle_level: int,
    db_pool: asyncpg.Pool
) -> int:
    """
    Calculate interaction user level (adaptive during cycle)
    
    Args:
        cycle_id: Current cycle ID
        interaction_number: Current interaction number (1-7)
        cycle_level: Cycle level
        db_pool: Database connection pool
    
    Returns:
        Interaction user level (0-500)
    """
    
    if interaction_number == 1:
        # First interaction: use cycle level
        return cycle_level
    
    async with db_pool.acquire() as conn:
        # Get last interaction data
        last_interaction = await conn.fetchrow("""
            SELECT interaction_score
            FROM session_interaction
            WHERE cycle_id = $1
            AND interaction_number = $2
            AND status = 'completed'
        """, cycle_id, interaction_number - 1)
        
        if not last_interaction:
            return cycle_level
        
        # Get cycle stats so far
        cycle_stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) as completed_count,
                AVG(interaction_score) as avg_score
            FROM session_interaction
            WHERE cycle_id = $1
            AND status = 'completed'
        """, cycle_id)
        
        completed_count = cycle_stats['completed_count'] or 0
        cycle_rate = (cycle_stats['avg_score'] or 0) / 100.0
        
        # Only adjust after at least 3 interactions
        if completed_count < 3:
            return cycle_level
        
        last_score = last_interaction['interaction_score']
        
        # Adjustment logic
        adjustment = 0
        
        # Increase level if performing well
        if cycle_rate >= 0.8 and last_score >= 80:
            adjustment = 50
        
        # Decrease level if struggling
        elif cycle_rate < 0.8 and last_score < 60:
            adjustment = -50
        
        # Decrease if doing "okay" but level seems too high
        elif 0.6 <= cycle_rate < 0.8 and 60 <= last_score < 80:
            adjustment = -50
        
        new_level = cycle_level + adjustment
        new_level = max(0, min(500, new_level))
        new_level = round(new_level / 50) * 50
        
        if adjustment != 0:
            logger.debug(f"Interaction {interaction_number} level adjusted: {cycle_level} → {new_level}")
        
        return new_level
