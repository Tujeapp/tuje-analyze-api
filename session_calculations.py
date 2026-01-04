# ============================================================================
# session_calculations.py - Session Start Calculations
# ============================================================================
# This module contains all calculations needed when starting a new session
# Based on "Logic of a Session" documentation - Part 1: Set a new session
# ============================================================================

import asyncpg
import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


# ============================================================================
# A. TOP SESSION MOOD
# ============================================================================

async def calculate_top_session_mood(
    user_id: str,
    db_pool: asyncpg.Pool
) -> Tuple[str, float]:
    """
    Calculate the most used session mood from last 5 completed sessions
    
    Documentation: "Check the last 5 sessions → find most used mood"
    
    Args:
        user_id: User ID
        db_pool: Database connection pool
    
    Returns:
        Tuple of (top_mood, rate)
        - top_mood: Most frequent mood ("effective", "playful", etc.)
        - rate: Frequency rate (e.g., 0.6 means 3 out of 5 sessions)
    """
    async with db_pool.acquire() as conn:
        result = await conn.fetchrow("""
            WITH last_5_sessions AS (
                SELECT session_mood
                FROM session
                WHERE user_id = $1 
                AND status = 'completed'
                ORDER BY completed_at DESC
                LIMIT 5
            ),
            mood_counts AS (
                SELECT 
                    session_mood,
                    COUNT(*) as count,
                    COUNT(*)::float / NULLIF((SELECT COUNT(*) FROM last_5_sessions), 0) as rate
                FROM last_5_sessions
                GROUP BY session_mood
                ORDER BY count DESC
                LIMIT 1
            )
            SELECT session_mood, rate FROM mood_counts
        """, user_id)
        
        if result:
            top_mood = result['session_mood']
            rate = round(float(result['rate']), 2)
            logger.debug(f"Top session mood for {user_id}: {top_mood} ({rate:.0%})")
            return top_mood, rate
        
        # Default for new users
        return "effective", 0.0


# ============================================================================
# D. SESSION BOREDOM (Full calculation per documentation)
# ============================================================================

async def calculate_session_boredom_full(
    user_id: str,
    db_pool: asyncpg.Pool
) -> float:
    """
    Calculate session boredom based on last session data
    
    Documentation formula:
    - Based on last session rate, last session level direction, and top session mood
    - Coefficients vary based on these factors
    
    Args:
        user_id: User ID
        db_pool: Database connection pool
    
    Returns:
        Session boredom rate (0.0 - 1.0)
    """
    async with db_pool.acquire() as conn:
        last_session = await conn.fetchrow("""
            SELECT 
                session_score,
                session_level_direction,
                session_mood,
                session_nbr_cycle
            FROM session
            WHERE user_id = $1 
            AND status = 'completed'
            ORDER BY completed_at DESC
            LIMIT 1
        """, user_id)
        
        if not last_session:
            return 0.0  # No history = no boredom
        
        # Calculate last session rate (score / expected_score)
        expected_score = last_session['session_nbr_cycle'] * 7 * 100
        last_session_rate = last_session['session_score'] / expected_score if expected_score > 0 else 0
        last_level_direction = last_session['session_level_direction'] or 'stable'
        last_mood = last_session['session_mood'] or 'effective'
        
        # Get previous boredom to apply coefficient
        prev_boredom = await conn.fetchval("""
            SELECT session_boredom
            FROM session
            WHERE user_id = $1 
            AND status = 'completed'
            ORDER BY completed_at DESC
            LIMIT 1
        """, user_id) or 0.0
        
        # Calculate coefficient based on last session rate and level direction
        # Documentation: coefficient matrix
        coefficient = _get_boredom_coefficient(last_session_rate, last_level_direction)
        
        # Apply mood multiplier
        mood_multiplier = _get_mood_boredom_multiplier(last_mood)
        
        # Calculate new boredom
        new_boredom = float(prev_boredom) * coefficient * mood_multiplier
        
        # Clamp to 0.0 - 1.0
        new_boredom = round(max(0.0, min(1.0, new_boredom)), 2)
        
        logger.debug(f"Session boredom: {new_boredom:.2f} (prev: {prev_boredom}, rate: {last_session_rate:.2f}, dir: {last_level_direction})")
        return new_boredom


def _get_boredom_coefficient(session_rate: float, level_direction: str) -> float:
    """
    Get boredom coefficient based on last session performance
    
    Documentation matrix:
    - Low rate (0-0.4) + up direction = 1.25
    - Low rate (0-0.4) + stable = 1.5
    - Low rate (0-0.4) + down = 1.75
    - etc.
    """
    if session_rate <= 0.4:
        coefficients = {"up": 1.25, "stable": 1.5, "down": 1.75}
    elif session_rate <= 0.6:
        coefficients = {"up": 1.0, "stable": 1.25, "down": 1.5}
    elif session_rate <= 0.8:
        coefficients = {"up": 0.75, "stable": 1.0, "down": 1.25}
    else:  # > 0.8
        coefficients = {"up": 0.5, "stable": 0.75, "down": 1.0}
    
    return coefficients.get(level_direction.lower(), 1.0)


def _get_mood_boredom_multiplier(mood: str) -> float:
    """
    Get mood multiplier for boredom calculation
    
    Documentation:
    - "relax" or "playful" = 1.5 (higher boredom impact)
    - "listening", "cultural" = 1.0
    - "effective" = 0.5 (lower boredom impact)
    """
    multipliers = {
        "effective": 0.5,
        "listening": 1.0,
        "cultural": 1.0,
        "playful": 1.5,
        "relax": 1.5
    }
    return multipliers.get(mood.lower(), 1.0)


# ============================================================================
# E. SESSION MOOD RECOMMENDATION
# ============================================================================

def calculate_mood_recommendation(
    streak7: float,
    streak30: float,
    session_boredom: float,
    last_session_rate: float,
    top_session_mood: str
) -> str:
    """
    Calculate recommended session mood for user
    
    Documentation rules:
    - "relax": streak30 0-0.4 AND streak7 0-0.3
    - "playful": streak30 0-0.4 AND streak7 0-0.3 AND boredom > 0.5
    - "playful": boredom > 0.6
    - "effective": streak30 0-0.6 AND streak7 > 0.58 AND boredom <= 0.6
    - "effective": streak30 > 0.6 AND streak7 > 0.58 AND boredom <= 0.4
    - Otherwise: top_session_mood
    
    Args:
        streak7: 7-day streak rate
        streak30: 30-day streak rate
        session_boredom: Current session boredom
        last_session_rate: Last session completion rate
        top_session_mood: Most frequently used mood
    
    Returns:
        Recommended mood string
    """
    # High boredom → playful
    if session_boredom > 0.6:
        return "playful"
    
    # Low engagement → relax or playful
    if streak30 <= 0.4 and streak7 <= 0.3:
        if session_boredom > 0.5:
            return "playful"
        return "relax"
    
    # Good engagement + moderate/low boredom → effective
    if streak30 <= 0.6 and streak7 > 0.58 and session_boredom <= 0.6:
        return "effective"
    
    if streak30 > 0.6 and streak7 > 0.58 and session_boredom <= 0.4:
        return "effective"
    
    # Default to user's top mood
    return top_session_mood


# ============================================================================
# F. MODULO CALCULATION
# ============================================================================

async def calculate_modulo(
    user_id: str,
    session_mood: str,
    streak7: float,
    streak30: float,
    db_pool: asyncpg.Pool
) -> float:
    """
    Calculate modulo coefficient for malus reduction
    
    Documentation formula:
    modulo = session_mood_score × coefficient
    
    Where coefficient = average of:
    - streak30 score
    - streak7 score  
    - last_session_rate score
    - last_session_level_direction score
    
    Args:
        user_id: User ID
        session_mood: Selected session mood
        streak7: 7-day streak rate
        streak30: 30-day streak rate
        db_pool: Database connection pool
    
    Returns:
        Modulo value (0.0 - 1.0)
    """
    # Get session mood score
    mood_scores = {
        "effective": 1.0,
        "listening": 0.8,
        "cultural": 0.8,
        "playful": 0.6,
        "relax": 0.6
    }
    mood_score = mood_scores.get(session_mood.lower(), 0.8)
    
    # Get last session data
    async with db_pool.acquire() as conn:
        last_session = await conn.fetchrow("""
            SELECT 
                session_score,
                session_level_direction,
                session_nbr_cycle
            FROM session
            WHERE user_id = $1 
            AND status = 'completed'
            ORDER BY completed_at DESC
            LIMIT 1
        """, user_id)
    
    # Calculate coefficient components
    # Streak30 component
    if streak30 <= 0.2:
        streak30_component = 0.6
    elif streak30 <= 0.4:
        streak30_component = 0.7
    elif streak30 <= 0.6:
        streak30_component = 0.8
    elif streak30 <= 0.8:
        streak30_component = 0.9
    else:
        streak30_component = 1.0
    
    # Streak7 component
    if streak7 <= 0.15:
        streak7_component = 0.6
    elif streak7 <= 0.3:
        streak7_component = 0.7
    elif streak7 <= 0.58:
        streak7_component = 0.8
    elif streak7 <= 0.72:
        streak7_component = 0.9
    else:
        streak7_component = 1.0
    
    # Last session rate component
    if last_session:
        expected_score = last_session['session_nbr_cycle'] * 7 * 100
        last_rate = last_session['session_score'] / expected_score if expected_score > 0 else 0
        
        if last_rate <= 0.4:
            rate_component = 0.7
        elif last_rate <= 0.6:
            rate_component = 0.8
        elif last_rate <= 0.8:
            rate_component = 0.9
        else:
            rate_component = 1.0
        
        # Level direction component
        direction = (last_session['session_level_direction'] or 'stable').lower()
        direction_components = {"up": 1.0, "stable": 0.8, "down": 0.6}
        direction_component = direction_components.get(direction, 0.8)
    else:
        # Default for new users
        rate_component = 0.8
        direction_component = 0.8
    
    # Calculate average coefficient
    coefficient = (streak30_component + streak7_component + rate_component + direction_component) / 4
    
    # Final modulo
    modulo = round(mood_score * coefficient, 2)
    
    logger.debug(f"Modulo: {modulo:.2f} (mood: {mood_score}, coef: {coefficient:.2f})")
    return modulo


# ============================================================================
# K & L. SEEN CONTENT LISTS
# ============================================================================

async def get_seen_intents(
    user_id: str,
    db_pool: asyncpg.Pool
) -> List[str]:
    """
    Get list of intents seen in last 7 days (story/intent cycles)
    
    Documentation: "Make a search for all intents used in session 
    constrain by: in the last 7 days, in complete cycle with cycle goal 'story' or 'intent'"
    
    Args:
        user_id: User ID
        db_pool: Database connection pool
    
    Returns:
        List of intent IDs seen
    """
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT unnest(bi.intents) as intent_id
            FROM session_interaction si
            JOIN session_cycle sc ON si.cycle_id = sc.id
            JOIN session s ON sc.session_id = s.id
            JOIN brain_interaction bi ON si.brain_interaction_id = bi.id
            WHERE s.user_id = $1
            AND sc.cycle_goal IN ('story', 'intent')
            AND sc.status = 'completed'
            AND sc.completed_at > NOW() - INTERVAL '7 days'
        """, user_id)
        
        intents = [row['intent_id'] for row in rows if row['intent_id']]
        logger.debug(f"Found {len(intents)} seen intents for user {user_id}")
        return intents


async def get_seen_subtopics(
    user_id: str,
    db_pool: asyncpg.Pool
) -> List[str]:
    """
    Get list of subtopics seen in last 7 days (story/intent cycles)
    
    Documentation: "Make a search for all subtopics used in session
    constrain by: in the last 7 days, in complete cycle with cycle goal 'story' or 'intent'"
    
    Args:
        user_id: User ID
        db_pool: Database connection pool
    
    Returns:
        List of subtopic IDs seen
    """
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT sc.subtopic_id
            FROM session_cycle sc
            JOIN session s ON sc.session_id = s.id
            WHERE s.user_id = $1
            AND sc.cycle_goal IN ('story', 'intent')
            AND sc.status = 'completed'
            AND sc.completed_at > NOW() - INTERVAL '7 days'
            AND sc.subtopic_id IS NOT NULL
        """, user_id)
        
        subtopics = [row['subtopic_id'] for row in rows]
        logger.debug(f"Found {len(subtopics)} seen subtopics for user {user_id}")
        return subtopics


# ============================================================================
# HELPER: Get Last Session Data
# ============================================================================

async def get_last_session_data(
    user_id: str,
    db_pool: asyncpg.Pool
) -> Optional[Dict[str, Any]]:
    """
    Get comprehensive last session data for calculations
    
    Args:
        user_id: User ID
        db_pool: Database connection pool
    
    Returns:
        Dict with last session data or None if no history
    """
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT 
                id,
                session_score,
                session_level,
                session_level_direction,
                session_mood,
                session_boredom,
                session_nbr_cycle,
                streak7,
                streak30,
                completed_at
            FROM session
            WHERE user_id = $1 
            AND status = 'completed'
            ORDER BY completed_at DESC
            LIMIT 1
        """, user_id)
        
        if row:
            expected_score = row['session_nbr_cycle'] * 7 * 100
            return {
                "id": row['id'],
                "score": row['session_score'],
                "level": row['session_level'],
                "level_direction": row['session_level_direction'],
                "mood": row['session_mood'],
                "boredom": float(row['session_boredom']) if row['session_boredom'] else 0.0,
                "rate": row['session_score'] / expected_score if expected_score > 0 else 0,
                "streak7": float(row['streak7']) if row['streak7'] else 0.0,
                "streak30": float(row['streak30']) if row['streak30'] else 0.0,
                "completed_at": row['completed_at']
            }
        return None
