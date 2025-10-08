# ============================================================================
# cycle_completion.py - Cycle Completion and Statistics
# ============================================================================

import asyncpg
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


async def complete_cycle(
    cycle_id: str,
    session_id: str,
    db_pool: asyncpg.Pool
) -> Dict[str, Any]:
    """
    Mark cycle as completed and calculate cycle stats
    
    Args:
        cycle_id: Cycle ID to complete
        session_id: Parent session ID
        db_pool: Database connection pool
    
    Returns:
        Dict with cycle stats (cycle_score, cycle_rate, etc.)
    """
    
    async with db_pool.acquire() as conn:
        # Get all interaction scores for this cycle
        interactions = await conn.fetch("""
            SELECT 
                interaction_score,
                interaction_number,
                duration_seconds
            FROM session_interaction
            WHERE cycle_id = $1
            AND status = 'completed'
            ORDER BY interaction_number ASC
        """, cycle_id)
        
        if len(interactions) < 7:
            logger.warning(f"Cycle {cycle_id} has only {len(interactions)} completed interactions")
        
        # Calculate cycle score (sum of all interaction scores)
        cycle_score = sum(row['interaction_score'] for row in interactions)
        
        # Calculate cycle rate (0-1 scale)
        # cycle_score is 0-700 (7 interactions × 100 max each)
        cycle_rate = round(cycle_score / 700.0, 2)
        
        # Calculate average interaction score
        avg_score = round(cycle_score / len(interactions), 2) if interactions else 0.0
        
        # Calculate total duration
        total_duration = sum(row['duration_seconds'] for row in interactions)
        
        # Update cycle record
        await conn.execute("""
            UPDATE session_cycle
            SET 
                status = 'completed',
                completed_at = NOW(),
                completed_interactions = $2,
                cycle_score = $3,
                average_interaction_score = $4,
                duration_seconds = $5
            WHERE id = $1
        """, cycle_id, len(interactions), cycle_score, avg_score, total_duration)
        
        # Update session completed_cycles count
        await conn.execute("""
            UPDATE session
            SET completed_cycles = completed_cycles + 1,
                last_activity_at = NOW()
            WHERE id = $1
        """, session_id)
        
        logger.info(f"""
        ✅ Cycle completed:
        - Cycle ID: {cycle_id}
        - Score: {cycle_score}/700 (rate: {cycle_rate})
        - Avg per interaction: {avg_score}
        - Duration: {total_duration}s
        """)
        
        return {
            "cycle_id": cycle_id,
            "cycle_score": cycle_score,
            "cycle_rate": cycle_rate,
            "average_interaction_score": avg_score,
            "completed_interactions": len(interactions),
            "total_duration_seconds": total_duration
        }


async def update_cycle_level_direction(
    cycle_id: str,
    initial_cycle_level: int,
    db_pool: asyncpg.Pool
) -> str:
    """
    Calculate and update cycle level direction
    
    Args:
        cycle_id: Cycle ID
        initial_cycle_level: Level at cycle start
        db_pool: Database connection pool
    
    Returns:
        Level direction: "up", "stable", or "down"
    """
    
    async with db_pool.acquire() as conn:
        # Get final cycle score
        cycle_data = await conn.fetchrow("""
            SELECT cycle_score, completed_interactions
            FROM session_cycle
            WHERE id = $1
        """, cycle_id)
        
        if not cycle_data:
            return "stable"
        
        # Calculate cycle rate
        cycle_rate = cycle_data['cycle_score'] / 700.0 if cycle_data['completed_interactions'] == 7 else 0
        
        # Determine new level (not rounded to 50)
        if cycle_rate >= 0.8:
            new_level = initial_cycle_level + 50
            direction = "up"
        elif cycle_rate < 0.6:
            new_level = initial_cycle_level - 50
            direction = "down"
        else:
            new_level = initial_cycle_level
            direction = "stable"
        
        # Check if difference from initial is within ±10
        if abs(new_level - initial_cycle_level) <= 10:
            direction = "stable"
        
        logger.debug(f"Cycle level direction: {direction} (from {initial_cycle_level} → {new_level})")
        
        return direction


async def get_cycle_summary(
    cycle_id: str,
    db_pool: asyncpg.Pool
) -> Dict[str, Any]:
    """
    Get complete cycle summary for display to user
    
    Args:
        cycle_id: Cycle ID
        db_pool: Database connection pool
    
    Returns:
        Dict with complete cycle summary
    """
    
    async with db_pool.acquire() as conn:
        # Get cycle data
        cycle = await conn.fetchrow("""
            SELECT 
                c.id,
                c.cycle_number,
                c.cycle_goal,
                c.cycle_level,
                c.cycle_boredom,
                c.cycle_score,
                c.average_interaction_score,
                c.completed_interactions,
                c.duration_seconds,
                s.name_fr as subtopic_name
            FROM session_cycle c
            LEFT JOIN brain_subtopic s ON c.subtopic_id = s.id
            WHERE c.id = $1
        """, cycle_id)
        
        if not cycle:
            return {}
        
        # Get all interactions for this cycle
        interactions = await conn.fetch("""
            SELECT 
                interaction_number,
                interaction_score,
                attempts_count,
                duration_seconds
            FROM session_interaction
            WHERE cycle_id = $1
            ORDER BY interaction_number ASC
        """, cycle_id)
        
        return {
            "cycle_id": cycle['id'],
            "cycle_number": cycle['cycle_number'],
            "cycle_goal": cycle['cycle_goal'],
            "cycle_level": cycle['cycle_level'],
            "cycle_boredom": float(cycle['cycle_boredom']),
            "subtopic_name": cycle['subtopic_name'],
            "cycle_score": cycle['cycle_score'],
            "cycle_rate": round(cycle['cycle_score'] / 700.0, 2),
            "average_score": float(cycle['average_interaction_score']) if cycle['average_interaction_score'] else 0.0,
            "completed_interactions": cycle['completed_interactions'],
            "duration_seconds": cycle['duration_seconds'],
            "interactions": [
                {
                    "number": row['interaction_number'],
                    "score": row['interaction_score'],
                    "attempts": row['attempts_count'],
                    "duration": row['duration_seconds']
                }
                for row in interactions
            ]
        }
