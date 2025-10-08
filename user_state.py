# ============================================================================
# user_state.py - User State Detection
# ============================================================================

import asyncpg
import logging
from datetime import datetime
from .models import UserState, UserHistory

logger = logging.getLogger(__name__)


async def detect_user_state(user_id: str, db_pool: asyncpg.Pool) -> UserHistory:
    """
    Detect user state and available history
    
    Returns UserHistory with:
    - User state (brand_new, early, active, returning)
    - Available history days
    - Adaptive streak windows
    """
    
    async with db_pool.acquire() as conn:
        history = await conn.fetchrow("""
            SELECT 
                MIN(created_at) as first_session_date,
                MAX(completed_at) as last_session_date,
                COUNT(*) as total_sessions,
                MAX(session_level) FILTER (WHERE status = 'completed') as last_session_level
            FROM session
            WHERE user_id = $1
            AND status IN ('completed', 'incomplete')
        """, user_id)
        
        now = datetime.now()
        first_session = history['first_session_date']
        last_session = history['last_session_date']
        total_sessions = history['total_sessions'] or 0
        
        # Determine state
        if total_sessions == 0 or first_session is None:
            state = UserState.BRAND_NEW
            days_since_first = 0
            days_since_last = 0
            available_history_days = 0
        else:
            days_since_first = (now - first_session).days
            days_since_last = (now - last_session).days if last_session else 999
            
            if days_since_last > 30:
                state = UserState.RETURNING_USER
                available_history_days = 0
            elif days_since_first < 30:
                state = UserState.EARLY_USER
                available_history_days = days_since_first
            else:
                state = UserState.ACTIVE_USER
                available_history_days = 30
        
        # Adaptive streak windows
        if state in [UserState.BRAND_NEW, UserState.RETURNING_USER]:
            streak7_days = 0
            streak30_days = 0
        else:
            streak7_days = min(available_history_days, 7)
            streak30_days = min(available_history_days, 30)
        
        return UserHistory(
            user_id=user_id,
            first_session_date=first_session,
            last_session_date=last_session,
            total_sessions=total_sessions,
            days_since_first_session=days_since_first,
            days_since_last_session=days_since_last,
            last_session_level=history['last_session_level'],
            state=state,
            available_history_days=available_history_days,
            streak7_days=streak7_days,
            streak30_days=streak30_days
        )

