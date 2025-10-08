# ============================================================================
# session_init.py - Session Initialization by User State
# ============================================================================

import asyncpg
import logging
from typing import Dict, Any
from .models import UserHistory, UserState
from .session_context import SessionContext
from .helpers import generate_id, get_cycle_count, calculate_adaptive_boredom

logger = logging.getLogger(__name__)


async def initialize_brand_new_user(
    user_id: str,
    session_type: str,
    session_mood: str,
    db_pool: asyncpg.Pool
) -> Dict[str, Any]:
    """
    CASE 1: Brand new user (first session ever)
    
    - Start at level 0
    - No streaks
    - No notion rates
    - Empty context
    """
    
    logger.info(f"🆕 Initializing BRAND NEW user: {user_id}")
    
    user_level = 0
    session_level = 0
    streak7 = 0.0
    streak30 = 0.0
    session_boredom = 0.0
    
    context = SessionContext(
        user_id=user_id,
        seen_subtopics=set(),
        seen_interaction_ids=set(),
        seen_intents=set()
    )
    
    session_id = generate_id("SESSION")
    
    await db_pool.execute("""
        INSERT INTO session (
            id, user_id, session_rank, session_status, session_level,
            session_level_direction, session_nbr_cycle, session_mood,
            streak7, streak30, session_boredom, created_at
        ) VALUES ($1, $2, 1, 'active', $3, 'stable', $4, $5, 0, 0, 0, NOW())
    """, session_id, user_id, session_level,
        get_cycle_count(session_type), session_mood)
    
    return {
        "session_id": session_id,
        "user_level": user_level,
        "session_level": session_level,
        "context": context,
        "session_boredom": session_boredom,
        "streak7": streak7,
        "streak30": streak30,
        "is_new_user": True,
        "welcome_message": "Welcome to TuJe! Let's start your French journey! 🇫🇷"
    }


async def initialize_early_user(
    user_id: str,
    user_history: UserHistory,
    session_type: str,
    session_mood: str,
    db_pool: asyncpg.Pool
) -> Dict[str, Any]:
    """
    CASE 2: Early user (< 30 days since first session)
    
    - Adaptive streak windows
    - Partial history
    - Progressive onboarding
    """
    
    logger.info(f"👶 EARLY USER: {user_id} ({user_history.available_history_days}d history)")
    
    async with db_pool.acquire() as conn:
        # Adaptive streaks
        if user_history.streak7_days > 0:
            streak7 = await conn.fetchval(f"""
                SELECT ROUND((COUNT(DISTINCT DATE(completed_at))::float / $2)::numeric, 2)
                FROM session WHERE user_id = $1 AND status = 'completed'
                AND completed_at > NOW() - INTERVAL '{user_history.streak7_days} days'
            """, user_id, user_history.streak7_days) or 0.0
        else:
            streak7 = 0.0
        
        if user_history.streak30_days > 0:
            streak30 = await conn.fetchval(f"""
                SELECT ROUND((COUNT(DISTINCT DATE(completed_at))::float / $2)::numeric, 2)
                FROM session WHERE user_id = $1 AND status = 'completed'
                AND completed_at > NOW() - INTERVAL '{user_history.streak30_days} days'
            """, user_id, user_history.streak30_days) or 0.0
        else:
            streak30 = 0.0
        
        user_level = user_history.last_session_level or 0
        session_boredom = await calculate_adaptive_boredom(
            user_id, user_history.available_history_days, db_pool
        )
    
    context = await SessionContext.load(user_id, db_pool)
    session_id = generate_id("SESSION")
    session_rank = user_history.total_sessions + 1
    
    await db_pool.execute("""
        INSERT INTO session (
            id, user_id, session_rank, session_status, session_level,
            session_level_direction, session_nbr_cycle, session_mood,
            streak7, streak30, session_boredom, created_at
        ) VALUES ($1, $2, $3, 'active', $4, 'stable', $5, $6, $7, $8, $9, NOW())
    """, session_id, user_id, session_rank, user_level,
        get_cycle_count(session_type), session_mood, streak7, streak30, session_boredom)
    
    return {
        "session_id": session_id,
        "user_level": user_level,
        "session_level": user_level,
        "context": context,
        "session_boredom": session_boredom,
        "streak7": streak7,
        "streak30": streak30,
        "is_early_user": True,
        "welcome_message": f"Day {user_history.available_history_days} - Keep going! 💪"
    }


async def initialize_returning_user(
    user_id: str,
    user_history: UserHistory,
    session_type: str,
    session_mood: str,
    db_pool: asyncpg.Pool
) -> Dict[str, Any]:
    """
    CASE 3: Returning user (inactive 30+ days)
    
    - Reduce level by 50
    - Reset streaks
    - Reset notion rates
    - Fresh context
    """
    
    logger.warning(f"🔄 RETURNING: {user_id} (away {user_history.days_since_last_session}d)")
    
    last_level = user_history.last_session_level or 0
    user_level = max(0, last_level - 50)
    
    # Reset notion rates for returning user
    await db_pool.execute("""
        UPDATE session_notion
        SET notion_rate = CASE
            WHEN notion_level_owned <= $2 THEN 0.7
            ELSE 0.0
        END, updated_at = NOW()
        WHERE user_id = $1 AND notion_rate > 0
    """, user_id, user_level)
    
    context = SessionContext(
        user_id=user_id,
        seen_subtopics=set(),
        seen_interaction_ids=set(),
        seen_intents=set()
    )
    
    session_id = generate_id("SESSION")
    session_rank = user_history.total_sessions + 1
    
    await db_pool.execute("""
        INSERT INTO session (
            id, user_id, session_rank, session_status, session_level,
            session_level_direction, session_nbr_cycle, session_mood,
            streak7, streak30, session_boredom, is_returning_user, created_at
        ) VALUES ($1, $2, $3, 'active', $4, 'down', $5, $6, 0, 0, 0.1, true, NOW())
    """, session_id, user_id, session_rank, user_level,
        get_cycle_count(session_type), session_mood)
    
    return {
        "session_id": session_id,
        "user_level": user_level,
        "session_level": user_level,
        "context": context,
        "session_boredom": 0.1,
        "streak7": 0.0,
        "streak30": 0.0,
        "is_returning_user": True,
        "welcome_message": f"Welcome back! Adjusted to level {user_level}. Let's refresh! 🎉"
    }


async def initialize_active_user(
    user_id: str,
    user_history: UserHistory,
    session_type: str,
    session_mood: str,
    db_pool: asyncpg.Pool
) -> Dict[str, Any]:
    """
    CASE 4: Active user (normal operation)
    
    - Full 30-day history
    - Normal streak calculations
    - Complete notion tracking
    """
    
    logger.info(f"✅ ACTIVE USER: {user_id}")
    
    async with db_pool.acquire() as conn:
        streak7 = await conn.fetchval("""
            SELECT ROUND((COUNT(DISTINCT DATE(completed_at))::float / 7)::numeric, 2)
            FROM session WHERE user_id = $1 AND status = 'completed'
            AND completed_at > NOW() - INTERVAL '7 days'
        """, user_id) or 0.0
        
        streak30 = await conn.fetchval("""
            SELECT ROUND((COUNT(DISTINCT DATE(completed_at))::float / 30)::numeric, 2)
            FROM session WHERE user_id = $1 AND status = 'completed'
            AND completed_at > NOW() - INTERVAL '30 days'
        """, user_id) or 0.0
        
        user_level = user_history.last_session_level or 0
        session_boredom = await calculate_adaptive_boredom(user_id, 30, db_pool)
    
    context = await SessionContext.load(user_id, db_pool)
    session_id = generate_id("SESSION")
    session_rank = user_history.total_sessions + 1
    
    await db_pool.execute("""
        INSERT INTO session (
            id, user_id, session_rank, session_status, session_level,
            session_level_direction, session_nbr_cycle, session_mood,
            streak7, streak30, session_boredom, created_at
        ) VALUES ($1, $2, $3, 'active', $4, 'stable', $5, $6, $7, $8, $9, NOW())
    """, session_id, user_id, session_rank, user_level,
        get_cycle_count(session_type), session_mood, streak7, streak30, session_boredom)
    
    return {
        "session_id": session_id,
        "user_level": user_level,
        "session_level": user_level,
        "context": context,
        "session_boredom": session_boredom,
        "streak7": streak7,
        "streak30": streak30
    }
