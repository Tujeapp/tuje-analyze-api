# session_management/answer_service.py
"""
Answer processing and storage service
Integrates with existing adjustment, matching, and GPT services
"""
import asyncpg
import logging
import uuid
from datetime import datetime
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class AnswerService:
    """Manages answer submission and processing"""
    
    async def create_answer(
        self,
        interaction_id: str,
        user_id: str,
        original_transcript: str,
        db_pool: asyncpg.Pool
    ) -> str:
        """
        Create new answer attempt
        
        Args:
            interaction_id: Parent interaction ID
            user_id: User ID
            original_transcript: Raw speech transcript
            db_pool: Database connection pool
            
        Returns:
            answer_id: New answer ID
        """
        async with db_pool.acquire() as conn:
            # Get session_id and attempt count
            result = await conn.fetchrow("""
                SELECT session_id, attempts_count 
                FROM session_interaction 
                WHERE id = $1
            """, interaction_id)
            
            session_id = result['session_id']
            attempt_number = result['attempts_count'] + 1
            
            # Generate answer ID
            answer_id = f"ANS_{uuid.uuid4().hex[:16].upper()}"
            
            # Create answer record
            await conn.execute("""
                INSERT INTO session_answer (
                    id, session_id, interaction_id, user_id,
                    attempt_number, original_transcript, created_at,
                    is_final_answer
                )
                VALUES ($1, $2, $3, $4, $5, $6, NOW(), FALSE)
            """, answer_id, session_id, interaction_id, user_id, 
                attempt_number, original_transcript)
        
        logger.info(f"✅ Answer created: {answer_id} (attempt #{attempt_number})")
        return answer_id
    
    async def update_answer_with_adjustment(
        self,
        answer_id: str,
        adjusted_transcript: str,
        completed_transcript: str,
        vocabulary_found: list,
        entities_found: list,
        notion_matches: list,
        db_pool: asyncpg.Pool
    ):
        """
        Update answer with adjustment service results
        
        Args:
            answer_id: Answer to update
            adjusted_transcript: Adjusted version
            completed_transcript: Completed version
            vocabulary_found: List of vocabulary matches
            entities_found: List of entity matches
            notion_matches: List of notion matches
            db_pool: Database connection pool
        """
        async with db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE session_answer
                SET 
                    adjusted_transcript = $2,
                    completed_transcript = $3,
                    vocabulary_found = $4::jsonb,
                    entities_found = $5::jsonb,
                    notion_matches = $6::jsonb
                WHERE id = $1
            """, answer_id, adjusted_transcript, completed_transcript,
                vocabulary_found, entities_found, notion_matches)
        
        logger.info(f"✅ Answer updated with adjustment: {answer_id}")
    
    async def update_answer_with_matching(
        self,
        answer_id: str,
        similarity_score: float,
        matched_answer_id: Optional[str],
        db_pool: asyncpg.Pool
    ):
        """
        Update answer with matching service results
        
        Args:
            answer_id: Answer to update
            similarity_score: Matching similarity (0-100)
            matched_answer_id: Matched brain_answer ID (if found)
            db_pool: Database connection pool
        """
        async with db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE session_answer
                SET 
                    similarity_score = $2,
                    matched_answer_id = $3
                WHERE id = $1
            """, answer_id, similarity_score, matched_answer_id)
        
        logger.info(f"✅ Answer updated with matching: {answer_id} (score: {similarity_score})")
    
    async def update_answer_with_gpt(
        self,
        answer_id: str,
        gpt_intent_detected: str,
        processing_method: str,
        db_pool: asyncpg.Pool
    ):
        """
        Update answer with GPT fallback results
        
        Args:
            answer_id: Answer to update
            gpt_intent_detected: Intent detected by GPT
            processing_method: Method used (for analytics)
            db_pool: Database connection pool
        """
        async with db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE session_answer
                SET 
                    used_gpt_fallback = TRUE,
                    gpt_intent_detected = $2,
                    processing_method = $3
                WHERE id = $1
            """, answer_id, gpt_intent_detected, processing_method)
        
        logger.info(f"✅ Answer updated with GPT: {answer_id}")
    
    async def mark_as_final_answer(
        self,
        answer_id: str,
        processing_method: str,
        cost_saved: float,
        db_pool: asyncpg.Pool
    ):
        """
        Mark answer as the final accepted answer
        
        Args:
            answer_id: Answer to mark
            processing_method: How it was processed (answer_match, vocab_intent, etc)
            cost_saved: Cost saved by not using GPT (if applicable)
            db_pool: Database connection pool
        """
        async with db_pool.acquire() as conn:
            # Unmark any previous final answers for this interaction
            await conn.execute("""
                UPDATE session_answer
                SET is_final_answer = FALSE
                WHERE interaction_id = (
                    SELECT interaction_id FROM session_answer WHERE id = $1
                )
            """, answer_id)
            
            # Mark this one as final
            await conn.execute("""
                UPDATE session_answer
                SET 
                    is_final_answer = TRUE,
                    processing_method = $2,
                    cost_saved = $3
                WHERE id = $1
            """, answer_id, processing_method, cost_saved)
        
        logger.info(f"✅ Answer marked as final: {answer_id}")
    
    async def get_answer(
        self,
        answer_id: str,
        db_pool: asyncpg.Pool
    ) -> Optional[dict]:
        """Get answer details"""
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM session_answer WHERE id = $1
            """, answer_id)
            
            if row:
                return dict(row)
            return None
    
    async def get_interaction_answers(
        self,
        interaction_id: str,
        db_pool: asyncpg.Pool
    ) -> list:
        """Get all answers for an interaction"""
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM session_answer
                WHERE interaction_id = $1
                ORDER BY attempt_number ASC
            """, interaction_id)
            
            return [dict(row) for row in rows]
    
    async def get_final_answer(
        self,
        interaction_id: str,
        db_pool: asyncpg.Pool
    ) -> Optional[dict]:
        """Get the final accepted answer for an interaction"""
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM session_answer
                WHERE interaction_id = $1
                AND is_final_answer = TRUE
            """, interaction_id)
            
            if row:
                return dict(row)
            return None
    
    async def get_user_answer_stats(
        self,
        user_id: str,
        days: int,
        db_pool: asyncpg.Pool
    ) -> Dict:
        """Get user's answer statistics for analytics"""
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total_answers,
                    COUNT(CASE WHEN is_final_answer THEN 1 END) as accepted_answers,
                    AVG(similarity_score) as avg_similarity,
                    AVG(attempts_count) as avg_attempts_per_interaction,
                    SUM(CASE WHEN used_gpt_fallback THEN 1 ELSE 0 END) as gpt_usage_count,
                    SUM(cost_saved) as total_cost_saved
                FROM session_answer sa
                JOIN session_interaction si ON sa.interaction_id = si.id
                WHERE sa.user_id = $1
                AND sa.created_at >= NOW() - INTERVAL '1 day' * $2
            """, user_id, days)
            
            if row:
                return {
                    "total_answers": row['total_answers'],
                    "accepted_answers": row['accepted_answers'],
                    "avg_similarity": round(row['avg_similarity'] or 0, 1),
                    "avg_attempts": round(row['avg_attempts_per_interaction'] or 0, 1),
                    "gpt_usage_count": row['gpt_usage_count'],
                    "total_cost_saved": round(row['total_cost_saved'] or 0, 4)
                }
            return None


# Global service instance
answer_service = AnswerService()
