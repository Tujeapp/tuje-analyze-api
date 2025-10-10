# session_management/scoring_service.py
"""
Scoring service - Calculates interaction scores based on business logic
Implements the scoring formula from "Details of logic of session"
"""
import asyncpg
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ScoringService:
    """Manages score calculations for interactions"""
    
    async def calculate_interaction_score(
        self,
        interaction_id: str,
        matched_answer_id: Optional[str],
        similarity_score: float,
        db_pool: asyncpg.Pool
    ) -> int:
        """
        Calculate final interaction score using your business logic
        
        Steps:
        1. Get gross score (100 for first attempt, or previous score)
        2. Get required levels (interaction, answer, cycle)
        3. Calculate coefficient
        4. Calculate gross interaction score
        5. Apply bonus-malus (placeholder for now)
        6. Return final score (0-100)
        
        Args:
            interaction_id: Current interaction ID
            matched_answer_id: Matched brain_answer ID (can be None)
            similarity_score: Similarity percentage (0-100)
            db_pool: Database connection pool
            
        Returns:
            Final interaction score (0-100)
        """
        
        async with db_pool.acquire() as conn:
            # ============================================================
            # STEP 1: Get Gross Score
            # ============================================================
            current_interaction_score = await conn.fetchval("""
                SELECT interaction_score 
                FROM session_interaction 
                WHERE id = $1
            """, interaction_id)
            
            # First attempt: use 100
            # Subsequent attempts: use previous score
            gross_score = 100 if current_interaction_score is None else current_interaction_score
            
            logger.info(f"📊 Gross score: {gross_score}")
            
            # ============================================================
            # STEP 2: Get Required Data
            # ============================================================
            
            # Get interaction optimum level and cycle level
            interaction_data = await conn.fetchrow("""
                SELECT 
                    bi.level_from as interaction_optimum_level,
                    sc.cycle_level
                FROM session_interaction si
                JOIN brain_interaction bi ON si.brain_interaction_id = bi.id
                JOIN session_cycle sc ON si.cycle_id = sc.id
                WHERE si.id = $1
            """, interaction_id)
            
            if not interaction_data:
                logger.error(f"Cannot find interaction data for {interaction_id}")
                return 0
            
            interaction_optimum_level = interaction_data['interaction_optimum_level']
            cycle_level = interaction_data['cycle_level']
            
            # Get answer optimum level (if we have a matched answer)
            if matched_answer_id:
                answer_optimum_level = await conn.fetchval("""
                    SELECT answer_optimum_level 
                    FROM brain_answer 
                    WHERE id = $1
                """, matched_answer_id)
            else:
                # No matched answer - use interaction level as default
                answer_optimum_level = interaction_optimum_level
            
            logger.info(f"📊 Levels - Interaction: {interaction_optimum_level}, "
                       f"Answer: {answer_optimum_level}, Cycle: {cycle_level}")
            
            # ============================================================
            # STEP 3: Calculate Coefficient
            # ============================================================
            
            # Handle division by zero
            if interaction_optimum_level == 0 or cycle_level == 0:
                logger.warning("Level is 0, using coefficient 1.0")
                coefficient = 1.0
            else:
                coefficient = (
                    (answer_optimum_level / interaction_optimum_level) + 
                    (answer_optimum_level / cycle_level)
                ) / 2
            
            logger.info(f"📊 Coefficient: {coefficient:.3f}")
            
            # ============================================================
            # STEP 4: Calculate Gross Interaction Score
            # ============================================================
            
            # Apply similarity score factor
            # If similarity is 95%, we use 0.95 of the gross score
            similarity_factor = similarity_score / 100
            adjusted_gross_score = gross_score * similarity_factor
            
            # Apply coefficient
            gross_interaction_score = adjusted_gross_score * coefficient
            
            # Round to integer
            gross_interaction_score = int(round(gross_interaction_score))
            
            # Ensure within bounds
            gross_interaction_score = max(0, min(100, gross_interaction_score))
            
            logger.info(f"📊 Gross interaction score: {gross_interaction_score}")
            
            # ============================================================
            # STEP 5: Apply Bonus-Malus (Placeholder)
            # ============================================================
            
            # TODO: Implement bonus-malus logic when requirements are defined
            # For now, bonus_malus = 0
            bonus_malus = 0
            
            # Calculate final score
            final_score = gross_interaction_score + bonus_malus
            
            # Ensure within bounds after bonus-malus
            final_score = max(0, min(100, final_score))
            
            logger.info(f"✅ Final interaction score: {final_score}")
            
            return final_score
    
    async def calculate_simple_score(
        self,
        similarity_score: float
    ) -> int:
        """
        Simple scoring without levels (for testing or basic mode)
        Just converts similarity percentage to score
        
        Args:
            similarity_score: Similarity percentage (0-100)
            
        Returns:
            Score (0-100)
        """
        return int(round(min(100, max(0, similarity_score))))
    
    async def get_cycle_statistics(
        self,
        cycle_id: str,
        db_pool: asyncpg.Pool
    ) -> Dict:
        """
        Get comprehensive statistics for a cycle
        
        Returns:
            {
                "completed_interactions": 5,
                "total_interactions": 7,
                "cycle_score": 430,
                "max_cycle_score": 700,
                "average_score": 86.0,
                "progress_percentage": 71.4,
                "scores_breakdown": [95, 88, 90, 82, 75]
            }
        """
        async with db_pool.acquire() as conn:
            # Get cycle summary
            cycle_data = await conn.fetchrow("""
                SELECT 
                    completed_interactions,
                    cycle_score,
                    average_interaction_score
                FROM session_cycle
                WHERE id = $1
            """, cycle_id)
            
            if not cycle_data:
                return None
            
            # Get individual interaction scores
            scores = await conn.fetch("""
                SELECT interaction_score
                FROM session_interaction
                WHERE cycle_id = $1
                AND status = 'completed'
                ORDER BY interaction_number ASC
            """, cycle_id)
            
            scores_list = [row['interaction_score'] for row in scores]
            
            return {
                "completed_interactions": cycle_data['completed_interactions'],
                "total_interactions": 7,
                "cycle_score": cycle_data['cycle_score'] or 0,
                "max_cycle_score": 700,
                "average_score": round(cycle_data['average_interaction_score'] or 0, 1),
                "progress_percentage": round((cycle_data['completed_interactions'] / 7) * 100, 1),
                "scores_breakdown": scores_list
            }
    
    async def get_session_statistics(
        self,
        session_id: str,
        db_pool: asyncpg.Pool
    ) -> Dict:
        """
        Get comprehensive statistics for entire session
        
        Returns:
            {
                "completed_cycles": 3,
                "expected_cycles": 5,
                "total_score": 1850,
                "max_total_score": 3500,
                "average_score_per_interaction": 88.1,
                "progress_percentage": 60.0,
                "cycles_breakdown": [
                    {"cycle_number": 1, "score": 620, "avg": 88.6},
                    {"cycle_number": 2, "score": 610, "avg": 87.1},
                    {"cycle_number": 3, "score": 620, "avg": 88.6}
                ]
            }
        """
        async with db_pool.acquire() as conn:
            # Get session summary
            session_data = await conn.fetchrow("""
                SELECT 
                    completed_cycles,
                    expected_cycles,
                    total_score,
                    expected_total_score,
                    average_score_per_interaction
                FROM session
                WHERE id = $1
            """, session_id)
            
            if not session_data:
                return None
            
            # Get cycle breakdown
            cycles = await conn.fetch("""
                SELECT 
                    cycle_number,
                    cycle_score,
                    average_interaction_score
                FROM session_cycle
                WHERE session_id = $1
                AND status = 'completed'
                ORDER BY cycle_number ASC
            """, session_id)
            
            cycles_breakdown = [
                {
                    "cycle_number": row['cycle_number'],
                    "score": row['cycle_score'],
                    "avg": round(row['average_interaction_score'], 1)
                }
                for row in cycles
            ]
            
            return {
                "completed_cycles": session_data['completed_cycles'],
                "expected_cycles": session_data['expected_cycles'],
                "total_score": session_data['total_score'] or 0,
                "max_total_score": session_data['expected_total_score'],
                "average_score_per_interaction": round(
                    session_data['average_score_per_interaction'] or 0, 1
                ),
                "progress_percentage": round(
                    (session_data['completed_cycles'] / session_data['expected_cycles']) * 100, 1
                ),
                "cycles_breakdown": cycles_breakdown
            }


# Global service instance
scoring_service = ScoringService()
