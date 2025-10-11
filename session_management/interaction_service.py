# session_management/interaction_service.py
"""
Interaction management within cycles
Integrates with existing interaction search logic
"""
import asyncpg
import logging
import uuid
from datetime import datetime
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


class InteractionService:
    """Manages interaction lifecycle and selection"""
    
    async def create_interaction(
        self,
        cycle_id: str,
        brain_interaction_id: str,
        db_pool: asyncpg.Pool
    ) -> str:
        """
        Create next interaction in cycle
        
        Args:
            cycle_id: Parent cycle ID
            brain_interaction_id: ID from brain_interaction table
            db_pool: Database connection pool
            
        Returns:
            interaction_id: New interaction ID
        """
        async with db_pool.acquire() as conn:
            # Get current interaction count for this cycle
            current_count = await conn.fetchval("""
                SELECT COUNT(*) FROM session_interaction WHERE cycle_id = $1
            """, cycle_id)
            
            interaction_number = current_count + 1
            
            # Check if we exceeded 7 interactions
            if interaction_number > 7:
                raise ValueError(f"Cannot create interaction {interaction_number}: cycle only allows 7 interactions")
            
            # Get session_id from cycle
            session_id = await conn.fetchval("""
                SELECT session_id FROM session_cycle WHERE id = $1
            """, cycle_id)
            
            # Generate interaction ID
            interaction_id = f"INT_{uuid.uuid4().hex[:16].upper()}"
            
            # Create interaction
            await conn.execute("""
                INSERT INTO session_interaction (
                    id, session_id, cycle_id, brain_interaction_id,
                    interaction_number, status, started_at
                )
                VALUES ($1, $2, $3, $4, $5, 'active', NOW())
            """, interaction_id, session_id, cycle_id, brain_interaction_id, interaction_number)
            
            # Update session last activity
            await conn.execute("""
                UPDATE session
                SET last_activity_at = NOW()
                WHERE id = $1
            """, session_id)
        
        logger.info(f"✅ Interaction created: {interaction_id} (#{interaction_number} in cycle)")
        return interaction_id
    
    async def get_interaction(
        self,
        interaction_id: str,
        db_pool: asyncpg.Pool
    ) -> Optional[dict]:
        """Get interaction details"""
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT si.*,
                    bi.transcription_fr,
                    bi.transcription_en
                FROM session_interaction si
                JOIN brain_interaction bi ON si.brain_interaction_id = bi.id
                WHERE si.id = $1
            """, interaction_id)
            
            if row:
                return dict(row)
            return None
    
    async def get_current_interaction(
        self,
        cycle_id: str,
        db_pool: asyncpg.Pool
    ) -> Optional[dict]:
        """Get active interaction for cycle"""
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM session_interaction
                WHERE cycle_id = $1
                AND status = 'active'
                ORDER BY interaction_number DESC
                LIMIT 1
            """, cycle_id)
            
            if row:
                return dict(row)
            return None
    
    async def increment_attempt_count(
        self,
        interaction_id: str,
        db_pool: asyncpg.Pool
    ):
        """Increment attempt counter when user tries again"""
        async with db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE session_interaction
                SET attempts_count = attempts_count + 1
                WHERE id = $1
            """, interaction_id)
    
    async def complete_interaction(
        self,
        interaction_id: str,
        final_answer_id: str,
        interaction_score: int,
        db_pool: asyncpg.Pool
    ):
        """
        Mark interaction as completed with final score
        
        Args:
            interaction_id: Interaction to complete
            final_answer_id: ID of the accepted answer
            interaction_score: Final score (0-100)
            db_pool: Database connection pool
        """
        async with db_pool.acquire() as conn:
            # Get start time to calculate duration
            started_at = await conn.fetchval("""
                SELECT started_at FROM session_interaction WHERE id = $1
            """, interaction_id)
            
            # Update interaction
            await conn.execute("""
                UPDATE session_interaction
                SET 
                    status = 'completed',
                    completed_at = NOW(),
                    interaction_score = $2,
                    final_answer_id = $3,
                    duration_seconds = EXTRACT(EPOCH FROM (NOW() - started_at))::INTEGER
                WHERE id = $1
            """, interaction_id, interaction_score, final_answer_id)
            
            # Update cycle progress
            await conn.execute("""
                UPDATE session_cycle
                SET completed_interactions = (
                    SELECT COUNT(*) 
                    FROM session_interaction 
                    WHERE cycle_id = (
                        SELECT cycle_id FROM session_interaction WHERE id = $1
                    )
                    AND status = 'completed'
                )
                WHERE id = (
                    SELECT cycle_id FROM session_interaction WHERE id = $1
                )
            """, interaction_id)
            
            # Update session last activity
            session_id = await conn.fetchval("""
                SELECT session_id FROM session_interaction WHERE id = $1
            """, interaction_id)
            
            await conn.execute("""
                UPDATE session SET last_activity_at = NOW() WHERE id = $1
            """, session_id)
        
        logger.info(f"✅ Interaction completed: {interaction_id} (score: {interaction_score})")
    
    async def get_cycle_progress(
        self,
        cycle_id: str,
        db_pool: asyncpg.Pool
    ) -> Dict:
        """Get progress summary for a cycle"""
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT 
                    completed_interactions,
                    COALESCE(
                        (SELECT SUM(interaction_score) 
                         FROM session_interaction 
                         WHERE cycle_id = $1 AND status = 'completed'),
                        0
                    ) as current_score,
                    COALESCE(
                        (SELECT AVG(interaction_score) 
                         FROM session_interaction 
                         WHERE cycle_id = $1 AND status = 'completed'),
                        0
                    ) as average_score
                FROM session_cycle
                WHERE id = $1
            """, cycle_id)
            
            if row:
                return {
                    "completed_interactions": row['completed_interactions'],
                    "total_interactions": 7,
                    "current_score": row['current_score'],
                    "max_score": 700,
                    "average_score": round(row['average_score'], 1),
                    "progress_percentage": round((row['completed_interactions'] / 7) * 100, 1)
                }
            return None
    
    async def check_cycle_complete(
        self,
        cycle_id: str,
        db_pool: asyncpg.Pool
    ) -> bool:
        """Check if cycle has completed all 7 interactions"""
        async with db_pool.acquire() as conn:
            completed = await conn.fetchval("""
                SELECT completed_interactions FROM session_cycle WHERE id = $1
            """, cycle_id)
            
            return completed == 7
    
    async def get_next_interaction_number(
        self,
        cycle_id: str,
        db_pool: asyncpg.Pool
    ) -> int:
        """Get the next interaction number for a cycle (1-7)"""
        async with db_pool.acquire() as conn:
            count = await conn.fetchval("""
                SELECT COUNT(*) FROM session_interaction WHERE cycle_id = $1
            """, cycle_id)
            
            return count + 1

    async def record_hint_used(
        self,
        interaction_id: str,
        db_pool: asyncpg.Pool
    ):
        """
        Record that user used a hint for this interaction
    
        Args:
            interaction_id: Interaction ID
            db_pool: Database connection pool
        """
        async with db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE session_interaction
                SET hints_used = hints_used + 1
                WHERE id = $1
            """, interaction_id)
    
        logger.info(f"💡 Hint used recorded for interaction {interaction_id}")

# Global service instance
interaction_service = InteractionService()
