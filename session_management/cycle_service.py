# session_management/cycle_service.py
"""
Cycle management within sessions
"""
import asyncpg
import logging
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)


class CycleService:
    """Manages cycle lifecycle"""
    
    async def create_cycle(
        self,
        session_id: str,
        subtopic_id: str,
        cycle_goal: str,
        db_pool: asyncpg.Pool
    ) -> str:
        """
        Create next cycle in session
        
        Args:
            session_id: Parent session ID
            subtopic_id: Subtopic for this cycle
            cycle_goal: 'story' or 'intent'
            db_pool: Database connection pool
            
        Returns:
            cycle_id: New cycle ID
        """
        async with db_pool.acquire() as conn:
            # Get current cycle count
            current_count = await conn.fetchval("""
                SELECT COUNT(*) FROM session_cycle WHERE session_id = $1
            """, session_id)
            
            cycle_number = current_count + 1
            
            # Check if we exceeded expected cycles
            expected_cycles = await conn.fetchval("""
                SELECT expected_cycles FROM session WHERE id = $1
            """, session_id)
            
            if cycle_number > expected_cycles:
                raise ValueError(f"Cannot create cycle {cycle_number}: session only allows {expected_cycles} cycles")
            
            # Generate cycle ID
            cycle_id = f"CYCLE_{uuid.uuid4().hex[:16].upper()}"
            
            # Create cycle
            await conn.execute("""
                INSERT INTO session_cycle (
                    id, session_id, cycle_number, subtopic_id, cycle_goal,
                    status, started_at
                )
                VALUES ($1, $2, $3, $4, $5, 'active', NOW())
            """, cycle_id, session_id, cycle_number, subtopic_id, cycle_goal)
            
            # Update session
            await conn.execute("""
                UPDATE session
                SET completed_cycles = $2,
                    last_activity_at = NOW()
                WHERE id = $1
            """, session_id, cycle_number)
        
        logger.info(f"✅ Cycle created: {cycle_id} (cycle {cycle_number}/{expected_cycles})")
        return cycle_id
    
    async def get_current_cycle(
        self,
        session_id: str,
        db_pool: asyncpg.Pool
    ) -> Optional[dict]:
        """Get active cycle for session"""
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM session_cycle
                WHERE session_id = $1
                AND status = 'active'
                ORDER BY cycle_number DESC
                LIMIT 1
            """, session_id)
            
            if row:
                return dict(row)
            return None
    
    async def complete_cycle(
        self,
        cycle_id: str,
        db_pool: asyncpg.Pool
    ):
        """Mark cycle as completed and calculate scores"""
        async with db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE session_cycle
                SET 
                    status = 'completed',
                    completed_at = NOW(),
                    cycle_score = (
                        SELECT COALESCE(SUM(interaction_score), 0)
                        FROM session_interaction
                        WHERE cycle_id = $1
                    ),
                    average_interaction_score = (
                        SELECT ROUND(AVG(interaction_score), 2)
                        FROM session_interaction
                        WHERE cycle_id = $1
                    ),
                    duration_seconds = (
                        SELECT COALESCE(SUM(duration_seconds), 0)
                        FROM session_interaction
                        WHERE cycle_id = $1
                    )
                WHERE id = $1
            """, cycle_id)
        
        logger.info(f"✅ Cycle completed: {cycle_id}")


# Global service instance
cycle_service = CycleService()
