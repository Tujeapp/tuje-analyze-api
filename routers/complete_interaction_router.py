from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import asyncpg
import os
import logging
import uuid
from datetime import datetime

router = APIRouter()
logger = logging.getLogger(__name__)
DATABASE_URL = os.getenv("DATABASE_URL")

class CompleteInteractionRequest(BaseModel):
    session_id: str
    cycle_id: str
    interaction_id: str
    match_found: bool
    similarity_score: float = 0.0

class CompleteInteractionResponse(BaseModel):
    success: bool
    session_complete: bool = False
    cycle_complete: bool = False
    next_interaction_id: Optional[str] = None
    error: Optional[str] = None

@router.post("/complete-interaction", response_model=CompleteInteractionResponse)
async def complete_interaction(request: CompleteInteractionRequest):
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:

            # 1. Mark current interaction complete
            interaction_score = int(request.similarity_score)
            await conn.execute("""
                UPDATE session_interaction
                SET status = 'complete',
                    interaction_score = $1,
                    completed_at = NOW()
                WHERE id = $2
            """, interaction_score, request.interaction_id)

            # 2. Count completed interactions in this cycle
            completed_count = await conn.fetchval("""
                SELECT COUNT(*) FROM session_interaction
                WHERE cycle_id = $1 AND status = 'complete'
            """, request.cycle_id)

            # 3. Cycle complete after 7 interactions
            if completed_count >= 7:

                # Mark cycle complete
                await conn.execute("""
                    UPDATE session_cycle
                    SET status = 'complete',
                        completed_at = NOW(),
                        completed_interactions = $1
                    WHERE id = $2
                """, completed_count, request.cycle_id)

                # Count completed cycles in session
                completed_cycles = await conn.fetchval("""
                    SELECT COUNT(*) FROM session_cycle
                    WHERE session_id = $1 AND status = 'complete'
                """, request.session_id)

                if completed_cycles >= 3:
                    # Mark session complete
                    await conn.execute("""
                        UPDATE session
                        SET status = 'complete',
                            completed_at = NOW(),
                            completed_cycles = $1
                        WHERE id = $2
                    """, completed_cycles, request.session_id)
                    return CompleteInteractionResponse(
                        success=True,
                        session_complete=True
                    )

                # Start new cycle
                subtopic = await conn.fetchrow("""
                    SELECT id FROM brain_subtopic
                    WHERE live = TRUE
                    ORDER BY RANDOM() LIMIT 1
                """)

                if not subtopic:
                    raise HTTPException(status_code=500, detail="No subtopics available")

                new_cycle_id = f"CYCLE_{uuid.uuid4().hex[:16].upper()}"
                cycle_number = await conn.fetchval("""
                    SELECT COALESCE(MAX(cycle_number), 0) + 1
                    FROM session_cycle WHERE session_id = $1
                """, request.session_id)

                await conn.execute("""
                    INSERT INTO session_cycle
                    (id, session_id, subtopic_id, cycle_number, status, started_at)
                    VALUES ($1, $2, $3, $4, 'active', NOW())
                """, new_cycle_id, request.session_id,
                    subtopic['id'], cycle_number)

                # Pick first interaction for new cycle
                next_interaction = await conn.fetchrow("""
                    SELECT id FROM brain_interaction
                    WHERE live = TRUE
                    AND id NOT IN (
                        SELECT brain_interaction_id FROM session_interaction
                        WHERE session_id = $1
                    )
                    ORDER BY RANDOM() LIMIT 1
                """, request.session_id)

                if not next_interaction:
                    return CompleteInteractionResponse(
                        success=True, session_complete=True
                    )

                new_interaction_id = f"SINT_{uuid.uuid4().hex[:12].upper()}"
                await conn.execute("""
                    INSERT INTO session_interaction
                    (id, session_id, cycle_id, brain_interaction_id,
                     interaction_number, status, started_at)
                    VALUES ($1, $2, $3, $4, 1, 'active', NOW())
                """, new_interaction_id, request.session_id,
                    new_cycle_id, next_interaction['id'])

                return CompleteInteractionResponse(
                    success=True,
                    cycle_complete=True,
                    next_interaction_id=next_interaction['id']
                )

            # 4. Still in cycle — pick next interaction
            next_interaction = await conn.fetchrow("""
                SELECT id FROM brain_interaction
                WHERE live = TRUE
                AND id NOT IN (
                    SELECT brain_interaction_id FROM session_interaction
                    WHERE session_id = $1
                )
                ORDER BY RANDOM() LIMIT 1
            """, request.session_id)

            if not next_interaction:
                return CompleteInteractionResponse(
                    success=True, session_complete=True
                )

            new_interaction_id = f"SINT_{uuid.uuid4().hex[:12].upper()}"
            await conn.execute("""
                INSERT INTO session_interaction
                (id, session_id, cycle_id, brain_interaction_id,
                 interaction_number, status, started_at)
                VALUES ($1, $2, $3, $4, $5, 'active', NOW())
            """, new_interaction_id, request.session_id,
                request.cycle_id, next_interaction['id'],
                int(completed_count) + 1)

            return CompleteInteractionResponse(
                success=True,
                next_interaction_id=next_interaction['id']
            )

    except Exception as e:
        logger.error(f"complete_interaction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await pool.close()
