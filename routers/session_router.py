# routers/session_router.py
"""
Session Management API Endpoints
Complete REST API for session, cycle, interaction, and answer management
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List
import asyncpg
import logging
import os

from session_management import (
    session_service,
    cycle_service,
    interaction_service,
    answer_service,
    scoring_service,
    bonus_malus_service
)

logger = logging.getLogger(__name__)
router = APIRouter()

DATABASE_URL = os.getenv("DATABASE_URL")

# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class CreateSessionRequest(BaseModel):
    user_id: str
    session_type: str  # "short", "medium", "long"


class CreateSessionResponse(BaseModel):
    session_id: str
    session_type: str
    expected_cycles: int
    expected_total_score: int
    status: str


class StartCycleRequest(BaseModel):
    session_id: str
    subtopic_id: str
    cycle_goal: str = "story"
    cycle_level: int = 100


class StartCycleResponse(BaseModel):
    cycle_id: str
    cycle_number: int
    subtopic_id: str
    status: str


class StartInteractionRequest(BaseModel):
    cycle_id: str
    brain_interaction_id: str


class StartInteractionResponse(BaseModel):
    interaction_id: str
    interaction_number: int
    brain_interaction_id: str
    status: str


class SubmitAnswerRequest(BaseModel):
    interaction_id: str
    user_id: str
    original_transcript: str


class SubmitAnswerResponse(BaseModel):
    answer_id: str
    status: str  # "success", "retry", "partial_success"
    method: str
    similarity_score: float
    interaction_score: int
    interaction_complete: bool
    feedback: str
    gpt_used: bool
    cost_saved: float = 0
    bonus_malus_applied: Optional[dict] = None


# ============================================================================
# SESSION ENDPOINTS
# ============================================================================

@router.post("/create-session", response_model=CreateSessionResponse)
async def create_session(request: CreateSessionRequest):
    """
    Create a new learning session
    
    Session types:
    - short: 3 cycles (10-15 min)
    - medium: 5 cycles (20-25 min)
    - long: 7 cycles (35-40 min)
    """
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=5)
        
        try:
            session_id = await session_service.create_session(
                user_id=request.user_id,
                session_type=request.session_type,
                db_pool=pool
            )
            
            # Get session details
            session = await session_service.get_session(session_id, pool)
            
            return CreateSessionResponse(
                session_id=session_id,
                session_type=session['session_type'],
                expected_cycles=session['expected_cycles'],
                expected_total_score=session['expected_total_score'],
                status=session['status']
            )
            
        finally:
            await pool.close()
            
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/{session_id}")
async def get_session(session_id: str):
    """Get session details and current status"""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        
        try:
            session = await session_service.get_session(session_id, pool)
            
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            
            # Get statistics
            stats = await scoring_service.get_session_statistics(session_id, pool)
            
            return {
                "session": session,
                "statistics": stats
            }
            
        finally:
            await pool.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/active-session/{user_id}")
async def get_active_session(user_id: str):
    """Get user's active session if exists"""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        
        try:
            session = await session_service.get_active_session(user_id, pool)
            
            if not session:
                return {
                    "has_active_session": False,
                    "session": None
                }
            
            # Get statistics
            stats = await scoring_service.get_session_statistics(session['id'], pool)
            
            return {
                "has_active_session": True,
                "session": session,
                "statistics": stats
            }
            
        finally:
            await pool.close()
            
    except Exception as e:
        logger.error(f"Failed to get active session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/complete-session/{session_id}")
async def complete_session(session_id: str):
    """Mark session as completed"""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        
        try:
            await session_service.complete_session(session_id, pool)
            
            # Get final statistics
            stats = await scoring_service.get_session_statistics(session_id, pool)
            
            return {
                "status": "completed",
                "session_id": session_id,
                "statistics": stats
            }
            
        finally:
            await pool.close()
            
    except Exception as e:
        logger.error(f"Failed to complete session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# CYCLE ENDPOINTS
# ============================================================================

@router.post("/start-cycle", response_model=StartCycleResponse)
async def start_cycle(request: StartCycleRequest):
    """Start a new cycle within a session"""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=5)
        
        try:
            cycle_id = await cycle_service.create_cycle(
                session_id=request.session_id,
                subtopic_id=request.subtopic_id,
                cycle_goal=request.cycle_goal,
                db_pool=pool
            )
            
            # Update cycle level
            async with pool.acquire() as conn:
                await conn.execute("""
                    UPDATE session_cycle
                    SET cycle_level = $2
                    WHERE id = $1
                """, cycle_id, request.cycle_level)
            
            # Get cycle details
            cycle = await cycle_service.get_current_cycle(request.session_id, pool)
            
            return StartCycleResponse(
                cycle_id=cycle_id,
                cycle_number=cycle['cycle_number'],
                subtopic_id=cycle['subtopic_id'],
                status=cycle['status']
            )
            
        finally:
            await pool.close()
            
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to start cycle: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cycle/{cycle_id}")
async def get_cycle(cycle_id: str):
    """Get cycle details and progress"""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        
        try:
            # Get progress
            progress = await interaction_service.get_cycle_progress(cycle_id, pool)
            
            if not progress:
                raise HTTPException(status_code=404, detail="Cycle not found")
            
            # Get statistics
            stats = await scoring_service.get_cycle_statistics(cycle_id, pool)
            
            return {
                "progress": progress,
                "statistics": stats
            }
            
        finally:
            await pool.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get cycle: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/complete-cycle/{cycle_id}")
async def complete_cycle(cycle_id: str):
    """Mark cycle as completed"""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        
        try:
            await cycle_service.complete_cycle(cycle_id, pool)
            
            # Get final statistics
            stats = await scoring_service.get_cycle_statistics(cycle_id, pool)
            
            return {
                "status": "completed",
                "cycle_id": cycle_id,
                "statistics": stats
            }
            
        finally:
            await pool.close()
            
    except Exception as e:
        logger.error(f"Failed to complete cycle: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# INTERACTION ENDPOINTS
# ============================================================================

@router.post("/start-interaction", response_model=StartInteractionResponse)
async def start_interaction(request: StartInteractionRequest):
    """Start a new interaction within a cycle"""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=5)
        
        try:
            interaction_id = await interaction_service.create_interaction(
                cycle_id=request.cycle_id,
                brain_interaction_id=request.brain_interaction_id,
                db_pool=pool
            )
            
            # Get interaction details
            interaction = await interaction_service.get_interaction(interaction_id, pool)
            
            return StartInteractionResponse(
                interaction_id=interaction_id,
                interaction_number=interaction['interaction_number'],
                brain_interaction_id=interaction['brain_interaction_id'],
                status=interaction['status']
            )
            
        finally:
            await pool.close()
            
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to start interaction: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/interaction/{interaction_id}")
async def get_interaction(interaction_id: str):
    """Get interaction details"""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        
        try:
            interaction = await interaction_service.get_interaction(interaction_id, pool)
            
            if not interaction:
                raise HTTPException(status_code=404, detail="Interaction not found")
            
            # Get all answers for this interaction
            answers = await answer_service.get_interaction_answers(interaction_id, pool)
            
            return {
                "interaction": interaction,
                "answers": answers,
                "attempts_count": len(answers)
            }
            
        finally:
            await pool.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get interaction: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ANSWER SUBMISSION (MAIN WORKFLOW)
# ============================================================================

@router.post("/submit-answer", response_model=SubmitAnswerResponse)
async def submit_answer(request: SubmitAnswerRequest):
    """
    Submit user answer - Complete processing workflow
    
    This is the MAIN endpoint that Bubble calls when user speaks.
    It orchestrates all services:
    1. Creates answer record
    2. Calls adjustment service
    3. Calls matching service
    4. Optionally calls GPT
    5. Calculates score with bonus-malus
    6. Completes interaction if successful
    
    Returns detailed results for Bubble to display
    """
    try:
        # Import the orchestrator
        from answer_processing_orchestrator import process_user_answer_complete
        
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=5)
        
        try:
            result = await process_user_answer_complete(
                interaction_id=request.interaction_id,
                user_id=request.user_id,
                original_transcript=request.original_transcript,
                db_pool=pool
            )
            
            return SubmitAnswerResponse(**result)
            
        finally:
            await pool.close()
            
    except Exception as e:
        logger.error(f"Failed to submit answer: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# HINT TRACKING
# ============================================================================

@router.post("/record-hint")
async def record_hint_used(interaction_id: str):
    """
    Record that user used a hint
    Called when user clicks hint button in Bubble
    """
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        
        try:
            await interaction_service.record_hint_used(interaction_id, pool)
            
            # Get current hint count
            async with pool.acquire() as conn:
                hints_count = await conn.fetchval("""
                    SELECT hints_used FROM session_interaction WHERE id = $1
                """, interaction_id)
            
            return {
                "status": "success",
                "message": "Hint recorded",
                "interaction_id": interaction_id,
                "hints_used": hints_count,
                "malus_info": {
                    "points_per_hint": -5,
                    "total_malus": hints_count * -5,
                    "note": "Each hint applies -5 points to your final score"
                }
            }
            
        finally:
            await pool.close()
            
    except Exception as e:
        logger.error(f"Failed to record hint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hints-used/{interaction_id}")
async def get_hints_used(interaction_id: str):
    """Get number of hints used for an interaction"""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        
        try:
            async with pool.acquire() as conn:
                hints_count = await conn.fetchval("""
                    SELECT hints_used FROM session_interaction WHERE id = $1
                """, interaction_id)
            
            if hints_count is None:
                raise HTTPException(status_code=404, detail="Interaction not found")
            
            return {
                "interaction_id": interaction_id,
                "hints_used": hints_count,
                "malus_applied": hints_count * -5
            }
            
        finally:
            await pool.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get hints: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# STATISTICS & PROGRESS
# ============================================================================

@router.get("/session-stats/{session_id}")
async def get_session_statistics(session_id: str):
    """Get comprehensive session statistics"""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        
        try:
            stats = await scoring_service.get_session_statistics(session_id, pool)
            
            if not stats:
                raise HTTPException(status_code=404, detail="Session not found")
            
            return stats
            
        finally:
            await pool.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get session stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cycle-stats/{cycle_id}")
async def get_cycle_statistics(cycle_id: str):
    """Get comprehensive cycle statistics"""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        
        try:
            stats = await scoring_service.get_cycle_statistics(cycle_id, pool)
            
            if not stats:
                raise HTTPException(status_code=404, detail="Cycle not found")
            
            return stats
            
        finally:
            await pool.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get cycle stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/user-answer-stats/{user_id}")
async def get_user_answer_statistics(user_id: str, days: int = 7):
    """Get user's answer statistics for analytics"""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        
        try:
            stats = await answer_service.get_user_answer_stats(user_id, days, pool)
            
            return stats or {
                "total_answers": 0,
                "accepted_answers": 0,
                "avg_similarity": 0,
                "avg_attempts": 0,
                "gpt_usage_count": 0,
                "total_cost_saved": 0
            }
            
        finally:
            await pool.close()
            
    except Exception as e:
        logger.error(f"Failed to get user stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# HEALTH CHECK
# ============================================================================

@router.get("/health")
async def session_management_health():
    """Health check for session management system"""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        
        try:
            async with pool.acquire() as conn:
                # Test database connection
                await conn.fetchval("SELECT 1")
                
                # Test tables exist
                tables = await conn.fetch("""
                    SELECT table_name FROM information_schema.tables
                    WHERE table_name IN ('session', 'session_cycle', 'session_interaction', 'session_answer')
                """)
                
                table_count = len(tables)
            
            return {
                "status": "healthy",
                "service": "session_management",
                "database": "connected",
                "tables": f"{table_count}/4 tables found",
                "endpoints": {
                    "session": "✅ Ready",
                    "cycle": "✅ Ready",
                    "interaction": "✅ Ready",
                    "answer": "✅ Ready",
                    "hints": "✅ Ready",
                    "statistics": "✅ Ready"
                }
            }
            
        finally:
            await pool.close()
            
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }
