# ============================================================================
# session_management_router.py - Session Management API Endpoints
# ============================================================================

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Dict, Any, Optional
import asyncpg
import logging
import os

# Import session management modules
from user_state import detect_user_state
from session_init import (
    initialize_brand_new_user,
    initialize_early_user,
    initialize_returning_user,
    initialize_active_user
)
from cycle_manager.cycle_creation import start_new_cycle, advance_to_next_interaction
from cycle_manager.cycle_completion import complete_cycle, get_cycle_summary
from cycle_manager.cycle_calculations import (
    calculate_cycle_level,
    calculate_cycle_boredom,
    calculate_cycle_goal
)
from helpers import (
    validate_session_type,
    validate_session_mood,
    log_session_summary,
    log_cycle_summary
)
from models import UserState

logger = logging.getLogger(__name__)
router = APIRouter()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Missing required environment variable: DATABASE_URL")


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class StartSessionRequest(BaseModel):
    user_id: str
    session_type: str  # "short", "medium", "long"
    session_mood: str  # "effective", "playful", "cultural", "relax", "listening"


class StartSessionResponse(BaseModel):
    session_id: str
    user_level: int
    session_level: int
    session_boredom: float
    streak7: float
    streak30: float
    user_state: str
    welcome_message: str
    is_new_user: Optional[bool] = False
    is_returning_user: Optional[bool] = False
    is_early_user: Optional[bool] = False


class StartCycleRequest(BaseModel):
    session_id: str
    cycle_number: int
    session_mood: str


class StartCycleResponse(BaseModel):
    cycle_id: str
    subtopic_id: str
    first_interaction_id: str
    total_interactions: int
    cycle_level: int
    cycle_boredom: float
    cycle_goal: str


class CompleteCycleRequest(BaseModel):
    cycle_id: str
    session_id: str


class CompleteCycleResponse(BaseModel):
    cycle_id: str
    cycle_score: int
    cycle_rate: float
    average_interaction_score: float
    completed_interactions: int
    total_duration_seconds: int


# ============================================================================
# SESSION ENDPOINTS
# ============================================================================

@router.post("/start-session", response_model=StartSessionResponse)
async def start_session_endpoint(request: StartSessionRequest):
    """
    Start a new session for a user
    
    Handles all user states:
    - Brand new users
    - Early users (< 30 days)
    - Active users
    - Returning users (inactive 30+ days)
    """
    try:
        # Validate inputs
        if not validate_session_type(request.session_type):
            raise HTTPException(status_code=400, detail="Invalid session_type. Use: short, medium, or long")
        
        if not validate_session_mood(request.session_mood):
            raise HTTPException(status_code=400, detail="Invalid session_mood")
        
        logger.info(f"🎬 Starting session for user: {request.user_id}")
        
        # Create database pool
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
        
        try:
            # Detect user state
            user_history = await detect_user_state(request.user_id, pool)
            
            # Initialize session based on user state
            if user_history.state == UserState.BRAND_NEW:
                session_data = await initialize_brand_new_user(
                    request.user_id, request.session_type, request.session_mood, pool
                )
            elif user_history.state == UserState.RETURNING_USER:
                session_data = await initialize_returning_user(
                    request.user_id, user_history, request.session_type, request.session_mood, pool
                )
            elif user_history.state == UserState.EARLY_USER:
                session_data = await initialize_early_user(
                    request.user_id, user_history, request.session_type, request.session_mood, pool
                )
            else:  # ACTIVE_USER
                session_data = await initialize_active_user(
                    request.user_id, user_history, request.session_type, request.session_mood, pool
                )
            
            # Log summary
            log_session_summary({
                **session_data,
                "user_id": request.user_id,
                "session_type": request.session_type,
                "session_mood": request.session_mood,
                "user_state": user_history.state.value
            })
            
            return StartSessionResponse(
                session_id=session_data['session_id'],
                user_level=session_data['user_level'],
                session_level=session_data['session_level'],
                session_boredom=session_data['session_boredom'],
                streak7=session_data['streak7'],
                streak30=session_data['streak30'],
                user_state=user_history.state.value,
                welcome_message=session_data.get('welcome_message', ''),
                is_new_user=session_data.get('is_new_user', False),
                is_returning_user=session_data.get('is_returning_user', False),
                is_early_user=session_data.get('is_early_user', False)
            )
            
        finally:
            await pool.close()
            
    except Exception as e:
        logger.error(f"Failed to start session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/{session_id}")
async def get_session_status(session_id: str):
    """Get current session status"""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        
        try:
            async with pool.acquire() as conn:
                session = await conn.fetchrow("""
                    SELECT 
                        id, user_id, session_status, session_level,
                        session_mood, completed_cycles, session_nbr_cycle,
                        streak7, streak30, session_boredom, created_at
                    FROM session
                    WHERE id = $1
                """, session_id)
                
                if not session:
                    raise HTTPException(status_code=404, detail="Session not found")
                
                return {
                    "session_id": session['id'],
                    "user_id": session['user_id'],
                    "status": session['session_status'],
                    "level": session['session_level'],
                    "mood": session['session_mood'],
                    "completed_cycles": session['completed_cycles'],
                    "total_cycles": session['session_nbr_cycle'],
                    "streak7": float(session['streak7']),
                    "streak30": float(session['streak30']),
                    "boredom": float(session['session_boredom']),
                    "created_at": session['created_at'].isoformat()
                }
        finally:
            await pool.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get session status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# CYCLE ENDPOINTS
# ============================================================================

@router.post("/start-cycle", response_model=StartCycleResponse)
async def start_cycle_endpoint(request: StartCycleRequest):
    """Start a new cycle within a session"""
    try:
        logger.info(f"🔄 Starting cycle {request.cycle_number} for session: {request.session_id}")
        
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
        
        try:
            # Get session data
            async with pool.acquire() as conn:
                session = await conn.fetchrow("""
                    SELECT user_id, session_level, session_boredom
                    FROM session
                    WHERE id = $1
                """, request.session_id)
                
                if not session:
                    raise HTTPException(status_code=404, detail="Session not found")
            
            # Load session context
            from session_context import SessionContext
            context = await SessionContext.load(session['user_id'], pool)
            
            # Calculate cycle parameters
            cycle_level = await calculate_cycle_level(
                request.session_id,
                request.cycle_number,
                session['session_level'],
                pool
            )
            
            cycle_boredom = await calculate_cycle_boredom(
                request.session_id,
                request.cycle_number,
                session['session_boredom'],
                pool
            )
            
            cycle_goal = await calculate_cycle_goal(
                request.session_id,
                request.cycle_number,
                pool
            )
            
            # Start the cycle
            cycle_data = await start_new_cycle(
                session_id=request.session_id,
                context=context,
                cycle_number=request.cycle_number,
                cycle_goal=cycle_goal,
                cycle_boredom=cycle_boredom,
                cycle_level=cycle_level,
                interaction_user_level=cycle_level,
                session_mood=request.session_mood,
                db_pool=pool
            )
            
            log_cycle_summary({
                **cycle_data,
                "cycle_number": request.cycle_number,
                "cycle_goal": cycle_goal,
                "cycle_level": cycle_level,
                "cycle_boredom": cycle_boredom
            })
            
            return StartCycleResponse(
                cycle_id=cycle_data['cycle_id'],
                subtopic_id=cycle_data['subtopic_id'],
                first_interaction_id=cycle_data['first_interaction_id'],
                total_interactions=cycle_data['total_interactions'],
                cycle_level=cycle_level,
                cycle_boredom=cycle_boredom,
                cycle_goal=cycle_goal
            )
            
        finally:
            await pool.close()
            
    except Exception as e:
        logger.error(f"Failed to start cycle: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/complete-cycle", response_model=CompleteCycleResponse)
async def complete_cycle_endpoint(request: CompleteCycleRequest):
    """Mark a cycle as completed and get statistics"""
    try:
        logger.info(f"✅ Completing cycle: {request.cycle_id}")
        
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        
        try:
            cycle_stats = await complete_cycle(
                request.cycle_id,
                request.session_id,
                pool
            )
            
            return CompleteCycleResponse(**cycle_stats)
            
        finally:
            await pool.close()
            
    except Exception as e:
        logger.error(f"Failed to complete cycle: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cycle/{cycle_id}/summary")
async def get_cycle_summary_endpoint(cycle_id: str):
    """Get complete cycle summary"""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        
        try:
            summary = await get_cycle_summary(cycle_id, pool)
            
            if not summary:
                raise HTTPException(status_code=404, detail="Cycle not found")
            
            return summary
            
        finally:
            await pool.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get cycle summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# HEALTH CHECK
# ============================================================================

@router.get("/session-management-health")
async def session_management_health():
    """Health check for session management service"""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        try:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            
            return {
                "status": "healthy",
                "service": "session_management",
                "database": "connected",
                "endpoints": {
                    "start_session": "/start-session",
                    "get_session": "/session/{session_id}",
                    "start_cycle": "/start-cycle",
                    "complete_cycle": "/complete-cycle",
                    "cycle_summary": "/cycle/{cycle_id}/summary"
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
