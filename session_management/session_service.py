# session_management/session_service.py
"""
Session CRUD operations and lifecycle management
"""
import asyncpg
import logging
from datetime import datetime
from typing import Optional
import uuid

logger = logging.getLogger(__name__)


class SessionService:
    """Manages session lifecycle"""
    
    async def create_session(
        self,
        user_id: str,
        session_type: str,
        db_pool: asyncpg.Pool
    ) -> str:
        """
        Create a new session
        
        Args:
            user_id: User ID
            session_type: 'short' (3), 'medium' (5), or 'long' (7)
            db_pool: Database connection pool
            
        Returns:
            session_id: New session ID
        """
        # Map session type to expected cycles
        cycles_map = {
            'short': 3,
            'medium': 5,
            'long': 7
        }
        
        expected_cycles = cycles_map.get(session_type)
        if not expected_cycles:
            raise ValueError(f"Invalid session_type: {session_type}")
        
        # Calculate expected total score
        expected_total_score = expected_cycles * 7 * 100
        
        # Generate session ID
        session_id = f"SESSION_{uuid.uuid4().hex[:16].upper()}"
        
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO session (
                    id, user_id, session_type, expected_cycles,
                    expected_total_score, status, started_at, last_activity_at
                )
                VALUES ($1, $2, $3, $4, $5, 'active', NOW(), NOW())
            """, session_id, user_id, session_type, expected_cycles, expected_total_score)
        
        logger.info(f"✅ Session created: {session_id} ({session_type}, {expected_cycles} cycles)")
        return session_id
    
    async def get_session(
        self,
        session_id: str,
        db_pool: asyncpg.Pool
    ) -> Optional[dict]:
        """Get session details"""
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM session WHERE id = $1
            """, session_id)
            
            if row:
                return dict(row)
            return None
    
    async def get_active_session(
        self,
        user_id: str,
        db_pool: asyncpg.Pool
    ) -> Optional[dict]:
        """Get user's active session if exists"""
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM session 
                WHERE user_id = $1 
                AND status = 'active'
                ORDER BY started_at DESC
                LIMIT 1
            """, user_id)
            
            if row:
                return dict(row)
            return None
    
    async def update_last_activity(
        self,
        session_id: str,
        db_pool: asyncpg.Pool
    ):
        """Update session last activity timestamp"""
        async with db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE session 
                SET last_activity_at = NOW()
                WHERE id = $1
            """, session_id)
    
    async def complete_session(
        self,
        session_id: str,
        db_pool: asyncpg.Pool
    ):
        """Mark session as completed"""
        async with db_pool.acquire() as conn:
            # Calculate totals
            await conn.execute("""
                UPDATE session
                SET 
                    status = 'completed',
                    completed_at = NOW(),
                    total_score = (
                        SELECT COALESCE(SUM(cycle_score), 0)
                        FROM session_cycle
                        WHERE session_id = $1
                    ),
                    total_duration_seconds = (
                        SELECT COALESCE(SUM(duration_seconds), 0)
                        FROM session_cycle
                        WHERE session_id = $1
                    ),
                    average_score_per_interaction = (
                        SELECT ROUND(AVG(interaction_score), 2)
                        FROM session_interaction
                        WHERE session_id = $1
                    )
                WHERE id = $1
            """, session_id)
        
        logger.info(f"✅ Session completed: {session_id}")
    
    async def check_session_timeout(
        self,
        session_id: str,
        timeout_minutes: int,
        db_pool: asyncpg.Pool
    ) -> bool:
        """Check if session has timed out (returns True if timed out)"""
        async with db_pool.acquire() as conn:
            result = await conn.fetchval("""
                SELECT 
                    EXTRACT(EPOCH FROM (NOW() - last_activity_at)) / 60 > $2
                FROM session
                WHERE id = $1 AND status = 'active'
            """, session_id, timeout_minutes)
            
            if result:
                # Mark as incomplete
                await conn.execute("""
                    UPDATE session
                    SET status = 'incomplete'
                    WHERE id = $1
                """, session_id)
                logger.warning(f"⏱️ Session timed out: {session_id}")
                return True
            
            return False


# Global service instance
session_service = SessionService()
