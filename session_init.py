# ============================================================================
# session_init.py - Session Initialization by User State (IMPROVED)
# ============================================================================
# This module handles session initialization for all user states
# Integrates all calculations from "Logic of a Session" documentation
# ============================================================================

import asyncpg
import logging
from typing import Dict, Any, Optional
from models import UserHistory, UserState
from session_context import SessionContext
from helpers import generate_id, get_cycle_count

# Import new calculation modules
from session_calculations import (
    calculate_top_session_mood,
    calculate_session_boredom_full,
    calculate_mood_recommendation,
    calculate_modulo,
    get_seen_intents,
    get_seen_subtopics,
    get_last_session_data
)
from notion_management import process_notions_for_session_start, populate_intents_from_seen

logger = logging.getLogger(__name__)


# ============================================================================
# CASE 1: BRAND NEW USER
# ============================================================================

async def initialize_brand_new_user(
    user_id: str,
    session_type: str,
    session_mood: str,
    user_level: int,
    db_pool,
) -> Dict[str, Any]:
    """
    Initialize a session for a user with no regular-session history.

    Used for:
      - Truly brand-new users (no completed sessions of any kind).
      - Users who have completed an initial (onboarding) session but no regular
        session yet — per Option A in TuJe_Regular_Session_Spec.md, we route
        them here so the first regular session uses seed values rather than
        history-derived calculations.

    Seeds (deliberate; see spec):
      streak7=0, streak30=0, session_boredom=0, modulo=0.5,
      session_level_direction='stable', top_session_mood=session_mood (no
      history to compute it from), top_session_mood_rate=0,
      mood_recommendation=session_mood.

    user_level is supplied by the caller — for an initial-only user this comes
    from _bucket_to_session_level(brain_user.initial_level_bucket); for a truly
    brand-new user it comes from request.user_level (defaulting to 0).

    Returns a dict with every key the start-session handler reads.
    """
    session_id = generate_id("SESSION")
    session_nbr_cycle = get_cycle_count(session_type)
    # expected_total_score: 700 per cycle (initial-session convention).
    expected_total_score = session_nbr_cycle * 700

    # Seed values (no history to compute from).
    streak7 = 0.0
    streak30 = 0.0
    session_boredom = 0.0
    modulo = 0.5
    top_session_mood = session_mood
    top_session_mood_rate = 0.0
    mood_recommendation = session_mood
    session_level_direction = "stable"

    # Notion init for a brand-new user (writes session_notion seed rows;
    # short-circuits the decay/priority pipeline).
    notion_result = await process_notions_for_session_start(
        user_id=user_id,
        streak7=streak7,
        streak30=streak30,
        session_mood=session_mood,
        is_new_user=True,
        user_level=user_level,
        db_pool=db_pool,
    )

    # Empty SessionContext: no prior cycles/interactions to derive 'seen' sets
    # from. (Constructed directly rather than .load() — load() would query
    # session_cycle/session_interaction which have no user_id column populated
    # yet; see spec R6.)
    context = SessionContext(
        user_id=user_id,
        seen_subtopics=set(),
        seen_interaction_ids=set(),
        seen_intents=set(),
    )

    # Persist the session row. Every NOT NULL column on the live `session`
    # table must be populated here.
    await db_pool.execute(
        """
        INSERT INTO session (
            id, user_id, session_type, session_rank, status,
            session_level, session_level_direction,
            session_nbr_cycle, session_mood,
            streak7, streak30, session_boredom, modulo,
            top_session_mood, top_session_mood_rate, mood_recommendation,
            expected_cycles, expected_total_score,
            is_initial_session,
            started_at, last_activity_at
        ) VALUES (
            $1, $2, $3, 1, 'active',
            $4, $5,
            $6, $7,
            $8, $9, $10, $11,
            $12, $13, $14,
            $15, $16,
            FALSE,
            NOW(), NOW()
        )
        """,
        session_id, user_id, session_type,                       # $1 $2 $3
        user_level, session_level_direction,                     # $4 $5
        session_nbr_cycle, session_mood,                         # $6 $7
        streak7, streak30, session_boredom, modulo,              # $8 $9 $10 $11
        top_session_mood, top_session_mood_rate, mood_recommendation,  # $12 $13 $14
        session_nbr_cycle, expected_total_score,                 # $15 $16
    )

    return {
        # Core IDs / levels.
        "session_id": session_id,
        "user_level": user_level,
        "session_level": user_level,
        # Seed values, surfaced for the response.
        "streak7": streak7,
        "streak30": streak30,
        "session_boredom": session_boredom,
        "modulo": modulo,
        "top_session_mood": top_session_mood,
        "top_session_mood_rate": top_session_mood_rate,
        "mood_recommendation": mood_recommendation,
        # Notion result (is_new_user branch returns a dict with empty top_notions
        # and skipped_reason='new_user').
        "top_notions": notion_result.get("top_notions", []),
        "notion_processing": notion_result,
        # SessionContext (empty) and derived 'seen' lists.
        "context": context,
        "seen_intents": [],
        "seen_subtopics": [],
        # Flags read by the response builder.
        "is_new_user": True,
        "is_returning_user": False,
        "is_early_user": False,
        "welcome_message": "Welcome! Let's start your French journey. 🇫🇷",
        # No history → these are explicitly None.
        "available_history_days": None,
        "days_away": None,
        "level_adjusted_from": None,
    }


# ============================================================================
# CASE 2: EARLY USER (< 30 days)
# ============================================================================

async def initialize_early_user(
    user_id: str,
    user_history: UserHistory,
    session_type: str,
    session_mood: str,
    db_pool: asyncpg.Pool
) -> Dict[str, Any]:
    """
    Initialize session for early user (< 30 days since first session)
    
    - Adaptive streak windows based on available history
    - Full calculation pipeline but with adjusted windows
    
    Args:
        user_id: User ID
        user_history: User history data
        session_type: "short", "medium", "long"
        session_mood: Selected mood
        db_pool: Database connection pool
    
    Returns:
        Complete session initialization data
    """
    logger.info(f"👶 EARLY USER: {user_id} ({user_history.available_history_days}d history)")
    
    async with db_pool.acquire() as conn:
        # Adaptive streak calculations based on available history
        history_days = user_history.available_history_days
        
        # Streak7 (adaptive window)
        streak7_window = min(history_days, 7)
        if streak7_window > 0:
            streak7 = await conn.fetchval(f"""
                SELECT ROUND(
                    (COUNT(DISTINCT DATE(completed_at))::float / $2)::numeric, 2
                )
                FROM session 
                WHERE user_id = $1 AND status = 'completed'
                AND completed_at > NOW() - INTERVAL '{streak7_window} days'
            """, user_id, streak7_window) or 0.0
        else:
            streak7 = 0.0
        
        # Streak30 (adaptive window)
        streak30_window = min(history_days, 30)
        if streak30_window > 0:
            streak30 = await conn.fetchval(f"""
                SELECT ROUND(
                    (COUNT(DISTINCT DATE(completed_at))::float / $2)::numeric, 2
                )
                FROM session 
                WHERE user_id = $1 AND status = 'completed'
                AND completed_at > NOW() - INTERVAL '{streak30_window} days'
            """, user_id, streak30_window) or 0.0
        else:
            streak30 = 0.0
    
    # Get last session data
    last_session = await get_last_session_data(user_id, db_pool)
    user_level = user_history.last_session_level or 0
    
    # A. Top session mood
    top_mood, top_mood_rate = await calculate_top_session_mood(user_id, db_pool)
    
    # D. Session boredom (adaptive calculation)
    session_boredom = await calculate_session_boredom_full(user_id, db_pool)
    
    # E. Mood recommendation
    last_rate = last_session['rate'] if last_session else 0.5
    mood_recommendation = calculate_mood_recommendation(
        streak7, streak30, session_boredom, last_rate, top_mood
    )
    
    # F. Modulo calculation
    modulo = await calculate_modulo(user_id, session_mood, streak7, streak30, db_pool)
    
    # G-J. Notion processing
    notion_result = await process_notions_for_session_start(
        user_id=user_id,
        streak7=streak7,
        streak30=streak30,
        session_mood=session_mood,
        is_new_user=False,
        user_level=user_level,
        db_pool=db_pool
    )
    
    # K. List of intents seen
    seen_intents = await get_seen_intents(user_id, db_pool)

    # §7: upsert session_intents from the seen set (placeholder scores, pending §8).
    await populate_intents_from_seen(user_id, seen_intents, db_pool)

    # L. List of subtopics seen
    seen_subtopics = await get_seen_subtopics(user_id, db_pool)
    
    # Load full context
    context = await SessionContext.load(user_id, db_pool)

    # Generate session
    session_id = generate_id("SESSION")
    session_rank = user_history.total_sessions + 1

    # M. Save to database
    await db_pool.execute("""
        INSERT INTO session (
            id, user_id, session_rank, status, session_level,
            session_level_direction, session_nbr_cycle, session_mood,
            session_type, expected_cycles, expected_total_score,
            streak7, streak30, session_boredom, modulo,
            top_session_mood, top_session_mood_rate,
            mood_recommendation,
            started_at, last_activity_at
        ) VALUES (
            $1, $2, $3, 'active', $4, 'stable', $5, $6,
            $7, $8, $9,
            $10, $11, $12, $13, $14, $15, $16,
            NOW(), NOW()
        )
    """, session_id, user_id, session_rank, user_level,
        get_cycle_count(session_type), session_mood,
        session_type, get_cycle_count(session_type), get_cycle_count(session_type) * 700,
        streak7, streak30, session_boredom, modulo,
        top_mood, top_mood_rate, mood_recommendation)
    
    return {
        "session_id": session_id,
        "user_level": user_level,
        "session_level": user_level,
        "session_boredom": session_boredom,
        "streak7": float(streak7),
        "streak30": float(streak30),
        "modulo": modulo,
        "top_session_mood": top_mood,
        "top_session_mood_rate": top_mood_rate,
        "mood_recommendation": mood_recommendation,
        "context": context,
        "seen_intents": seen_intents,
        "seen_subtopics": seen_subtopics,
        "top_notions": notion_result.get("top_notions", []),
        "notion_processing": notion_result,
        "is_new_user": False,
        "is_returning_user": False,
        "is_early_user": True,
        "available_history_days": history_days,
        "welcome_message": f"Day {history_days} - Keep going! 💪"
    }


# ============================================================================
# CASE 3: RETURNING USER (inactive 30+ days)
# ============================================================================

async def initialize_returning_user(
    user_id: str,
    user_history: UserHistory,
    session_type: str,
    session_mood: str,
    db_pool: asyncpg.Pool
) -> Dict[str, Any]:
    """
    Initialize session for returning user (inactive 30+ days)
    
    Documentation behavior:
    - Reduce level by 50
    - Reset streaks to 0
    - Session boredom = 0.1 (slight fresh start boredom)
    - Reset/adjust notion rates for returning user
    
    Args:
        user_id: User ID
        user_history: User history data
        session_type: "short", "medium", "long"
        session_mood: Selected mood
        db_pool: Database connection pool
    
    Returns:
        Complete session initialization data
    """
    logger.warning(f"🔄 RETURNING USER: {user_id} (away {user_history.days_since_last_session}d)")
    
    # Level reduction for returning user
    last_level = user_history.last_session_level or 0
    user_level = max(0, last_level - 50)  # Reduce by 50, min 0
    
    # Reset values for returning user
    streak7 = 0.0
    streak30 = 0.0
    session_boredom = 0.1  # Small boredom to encourage fresh content
    modulo = 0.6  # Slightly reduced malus impact for returning users
    
    # A. Top session mood (from old history, still useful)
    top_mood, top_mood_rate = await calculate_top_session_mood(user_id, db_pool)
    
    # E. Mood recommendation (suggest something engaging for returning user)
    mood_recommendation = "playful"  # Encourage engagement for returning user
    
    # Reset notion rates for returning user
    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE session_notion
            SET 
                notion_rate = CASE
                    WHEN notion_rate >= 0.8 THEN 0.7  -- High mastery: reduce a bit
                    WHEN notion_rate >= 0.5 THEN 0.4  -- Medium: reduce more
                    ELSE 0.1  -- Low: keep low
                END,
                updated_at = NOW()
            WHERE user_id = $1 
            AND notion_rate > 0 
            AND notion_rate < 1
        """, user_id)
    
    # Calculate priority and complexity after reset
    notion_result = await process_notions_for_session_start(
        user_id=user_id,
        streak7=0.0,
        streak30=0.0,
        session_mood=session_mood,
        is_new_user=False,  # Not new, but reset context
        user_level=user_level,
        db_pool=db_pool
    )
    
    # Fresh context for returning user
    context = SessionContext(
        user_id=user_id,
        seen_subtopics=set(),
        seen_interaction_ids=set(),
        seen_intents=set(),
        seen_transcriptions=set()
    )
    
    session_id = generate_id("SESSION")
    session_rank = user_history.total_sessions + 1
    
    await db_pool.execute("""
        INSERT INTO session (
            id, user_id, session_rank, status, session_level,
            session_level_direction, session_nbr_cycle, session_mood,
            session_type, expected_cycles, expected_total_score,
            streak7, streak30, session_boredom, modulo,
            top_session_mood, top_session_mood_rate,
            mood_recommendation, is_returning_user,
            started_at, last_activity_at
        ) VALUES (
            $1, $2, $3, 'active', $4, 'down', $5, $6,
            $7, $8, $9,
            0, 0, 0.1, $10, $11, $12, $13, true,
            NOW(), NOW()
        )
    """, session_id, user_id, session_rank, user_level,
        get_cycle_count(session_type), session_mood,
        session_type, get_cycle_count(session_type), get_cycle_count(session_type) * 700,
        modulo,
        top_mood, top_mood_rate, mood_recommendation)
    
    return {
        "session_id": session_id,
        "user_level": user_level,
        "session_level": user_level,
        "session_boredom": session_boredom,
        "streak7": streak7,
        "streak30": streak30,
        "modulo": modulo,
        "top_session_mood": top_mood,
        "top_session_mood_rate": top_mood_rate,
        "mood_recommendation": mood_recommendation,
        "context": context,
        "seen_intents": [],  # Fresh start
        "seen_subtopics": [],  # Fresh start
        "top_notions": notion_result.get("top_notions", []),
        "notion_processing": notion_result,
        "is_new_user": False,
        "is_returning_user": True,
        "is_early_user": False,
        "days_away": user_history.days_since_last_session,
        "level_adjusted_from": last_level,
        "welcome_message": f"Welcome back! Adjusted to level {user_level}. Let's refresh! 🎉"
    }


# ============================================================================
# CASE 4: ACTIVE USER (normal operation)
# ============================================================================

async def initialize_active_user(
    user_id: str,
    user_history: UserHistory,
    session_type: str,
    session_mood: str,
    db_pool: asyncpg.Pool
) -> Dict[str, Any]:
    """
    Initialize session for active user (normal operation)
    
    Full calculation pipeline with 30-day windows:
    A. Top session mood
    B. Streak30
    C. Streak7
    D. Session boredom
    E. Mood recommendation
    F. Modulo
    G. Update notion rates (decay)
    H. Notion priority rates
    I. Notion complexity rates
    J. Top notions list
    K. Intents seen
    L. Subtopics seen
    M. Save to database
    
    Args:
        user_id: User ID
        user_history: User history data
        session_type: "short", "medium", "long"
        session_mood: Selected mood
        db_pool: Database connection pool
    
    Returns:
        Complete session initialization data
    """
    logger.info(f"✅ ACTIVE USER: {user_id}")
    
    async with db_pool.acquire() as conn:
        # B. Calculate Streak30
        streak30 = await conn.fetchval("""
            SELECT ROUND(
                (COUNT(DISTINCT DATE(completed_at))::float / 30)::numeric, 2
            )
            FROM session 
            WHERE user_id = $1 AND status = 'completed'
            AND completed_at > NOW() - INTERVAL '30 days'
        """, user_id) or 0.0
        
        # C. Calculate Streak7
        streak7 = await conn.fetchval("""
            SELECT ROUND(
                (COUNT(DISTINCT DATE(completed_at))::float / 7)::numeric, 2
            )
            FROM session 
            WHERE user_id = $1 AND status = 'completed'
            AND completed_at > NOW() - INTERVAL '7 days'
        """, user_id) or 0.0
    
    # Get last session data
    last_session = await get_last_session_data(user_id, db_pool)
    user_level = user_history.last_session_level or 0
    
    # A. Top session mood
    top_mood, top_mood_rate = await calculate_top_session_mood(user_id, db_pool)
    
    # D. Session boredom (full calculation)
    session_boredom = await calculate_session_boredom_full(user_id, db_pool)
    
    # E. Mood recommendation
    last_rate = last_session['rate'] if last_session else 0.5
    mood_recommendation = calculate_mood_recommendation(
        float(streak7), float(streak30), session_boredom, last_rate, top_mood
    )
    
    # F. Modulo calculation
    modulo = await calculate_modulo(
        user_id, session_mood, float(streak7), float(streak30), db_pool
    )
    
    # G-J. Notion processing (decay, priority, complexity, top list)
    notion_result = await process_notions_for_session_start(
        user_id=user_id,
        streak7=float(streak7),
        streak30=float(streak30),
        session_mood=session_mood,
        is_new_user=False,
        user_level=user_level,
        db_pool=db_pool
    )
    
    # K. List of intents seen (last 7 days)
    seen_intents = await get_seen_intents(user_id, db_pool)

    # §7: upsert session_intents from the seen set (placeholder scores, pending §8).
    await populate_intents_from_seen(user_id, seen_intents, db_pool)

    # L. List of subtopics seen (last 7 days)
    seen_subtopics = await get_seen_subtopics(user_id, db_pool)
    
    # Load full session context
    context = await SessionContext.load(user_id, db_pool)

    # Generate session
    session_id = generate_id("SESSION")
    session_rank = user_history.total_sessions + 1

    # M. Save to database
    await db_pool.execute("""
        INSERT INTO session (
            id, user_id, session_rank, status, session_level,
            session_level_direction, session_nbr_cycle, session_mood,
            session_type, expected_cycles, expected_total_score,
            streak7, streak30, session_boredom, modulo,
            top_session_mood, top_session_mood_rate,
            mood_recommendation,
            started_at, last_activity_at
        ) VALUES (
            $1, $2, $3, 'active', $4, 'stable', $5, $6,
            $7, $8, $9,
            $10, $11, $12, $13, $14, $15, $16,
            NOW(), NOW()
        )
    """, session_id, user_id, session_rank, user_level,
        get_cycle_count(session_type), session_mood,
        session_type, get_cycle_count(session_type), get_cycle_count(session_type) * 700,
        streak7, streak30, session_boredom, modulo,
        top_mood, top_mood_rate, mood_recommendation)
    
    return {
        "session_id": session_id,
        "user_level": user_level,
        "session_level": user_level,
        "session_boredom": session_boredom,
        "streak7": float(streak7),
        "streak30": float(streak30),
        "modulo": modulo,
        "top_session_mood": top_mood,
        "top_session_mood_rate": top_mood_rate,
        "mood_recommendation": mood_recommendation,
        "context": context,
        "seen_intents": seen_intents,
        "seen_subtopics": seen_subtopics,
        "top_notions": notion_result.get("top_notions", []),
        "notion_processing": notion_result,
        "is_new_user": False,
        "is_returning_user": False,
        "is_early_user": False,
        "welcome_message": "Welcome back! Ready for your session? 🎯"
    }
