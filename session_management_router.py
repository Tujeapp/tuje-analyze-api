# ============================================================================
# session_management_router.py - Session Management API Endpoints (IMPROVED)
# ============================================================================
# Updated to include all session start calculations per documentation
# ============================================================================

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
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
    log_session_summary
)
from models import UserState

logger = logging.getLogger(__name__)
router = APIRouter()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Missing required environment variable: DATABASE_URL")


# ============================================================================
# REQUEST/RESPONSE MODELS (EXPANDED)
# ============================================================================

class StartSessionRequest(BaseModel):
    """Request to start a new session"""
    user_id: str
    session_type: str  # "short", "medium", "long"
    session_mood: str  # "effective", "playful", "cultural", "relax", "listening"
    user_level: Optional[int] = None  # Required for brand new users (from onboarding)


class TopNotionInfo(BaseModel):
    """Summary of a top priority notion"""
    notion_id: str
    notion_name: str
    notion_rate: float
    priority_rate: float
    complexity_rate: float


class NotionProcessingInfo(BaseModel):
    """Results of notion processing at session start"""
    notions_decayed: int
    priorities_updated: int
    complexities_updated: int
    skipped_reason: Optional[str] = None


class StartSessionResponse(BaseModel):
    """
    Complete response for session start
    
    Includes all calculations from "Logic of a Session" Part 1:
    - Streaks (7 and 30 day)
    - Session boredom
    - Top session mood and rate
    - Mood recommendation
    - Modulo (for scoring)
    - Top notions list
    - Seen content lists
    """
    # Core identifiers
    session_id: str
    user_id: str
    session_rank: int
    
    # Levels
    user_level: int
    session_level: int
    
    # Streaks (B, C)
    streak7: float
    streak30: float
    
    # Boredom (D)
    session_boredom: float
    
    # Mood (A, E)
    session_mood: str
    top_session_mood: str
    top_session_mood_rate: float
    mood_recommendation: str
    
    # Modulo (F)
    modulo: float
    
    # Notions (G, H, I, J)
    top_notions: List[TopNotionInfo]
    notion_processing: NotionProcessingInfo
    
    # Seen content (K, L)
    seen_intents_count: int
    seen_subtopics_count: int
    
    # User state flags
    user_state: str
    is_new_user: bool = False
    is_returning_user: bool = False
    is_early_user: bool = False
    
    # Additional info
    welcome_message: str
    available_history_days: Optional[int] = None
    days_away: Optional[int] = None
    level_adjusted_from: Optional[int] = None


class StartCycleRequest(BaseModel):
    """Request to start a new cycle within a session"""
    session_id: str
    cycle_number: int
    session_mood: str


class StartCycleResponse(BaseModel):
    """Response for cycle start"""
    cycle_id: str
    subtopic_id: str
    first_interaction_id: str
    total_interactions: int
    cycle_level: int
    cycle_boredom: float
    cycle_goal: str


# ============================================================================
# SESSION ENDPOINTS
# ============================================================================

@router.post("/start-session", response_model=StartSessionResponse)
async def start_session_endpoint(request: StartSessionRequest):
    """
    Start a new session for a user
    
    Performs all calculations from "Logic of a Session" Part 1:
    A. Define Top session mood
    B. Calculate Streak30
    C. Calculate Streak7
    D. Calculate Session Boredom
    E. Calculate Session Mood Recommendation
    F. Calculate Modulo
    G. Update notion rates (decay)
    H. Calculate notion priority rates
    I. Calculate notion complexity rates
    J. Define list of top notions
    K. Define list of intents seen
    L. Define list of subtopics seen
    M. Save data in database
    
    Handles all user states:
    - Brand new users (first session)
    - Early users (< 30 days)
    - Active users (normal operation)
    - Returning users (inactive 30+ days)
    """
    try:
        # Validate inputs
        if not validate_session_type(request.session_type):
            raise HTTPException(
                status_code=400, 
                detail="Invalid session_type. Use: short, medium, or long"
            )
        
        if not validate_session_mood(request.session_mood):
            raise HTTPException(
                status_code=400,
                detail="Invalid session_mood. Use: effective, playful, cultural, relax, or listening"
            )
        
        logger.info(f"🎬 Starting session for user: {request.user_id}")
        
        # Create database pool
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
        
        try:
            # Detect user state
            user_history = await detect_user_state(request.user_id, pool)
            
            # Initialize session based on user state
            if user_history.state == UserState.BRAND_NEW:
                # Require user_level for brand new users
                user_level = request.user_level if request.user_level is not None else 0
                session_data = await initialize_brand_new_user(
                    request.user_id, 
                    request.session_type, 
                    request.session_mood,
                    user_level,
                    pool
                )
                
            elif user_history.state == UserState.RETURNING_USER:
                session_data = await initialize_returning_user(
                    request.user_id, 
                    user_history, 
                    request.session_type, 
                    request.session_mood, 
                    pool
                )
                
            elif user_history.state == UserState.EARLY_USER:
                session_data = await initialize_early_user(
                    request.user_id, 
                    user_history, 
                    request.session_type, 
                    request.session_mood, 
                    pool
                )
                
            else:  # ACTIVE_USER
                session_data = await initialize_active_user(
                    request.user_id, 
                    user_history, 
                    request.session_type, 
                    request.session_mood, 
                    pool
                )
            
            # Log summary
            log_session_summary({
                **session_data,
                "user_id": request.user_id,
                "session_type": request.session_type,
                "session_mood": request.session_mood,
                "user_state": user_history.state.value
            })
            
            # Build response
            notion_processing = session_data.get("notion_processing", {})
            top_notions = session_data.get("top_notions", [])
            
            return StartSessionResponse(
                # Core identifiers
                session_id=session_data['session_id'],
                user_id=request.user_id,
                session_rank=user_history.total_sessions + 1,
                
                # Levels
                user_level=session_data['user_level'],
                session_level=session_data['session_level'],
                
                # Streaks
                streak7=session_data['streak7'],
                streak30=session_data['streak30'],
                
                # Boredom
                session_boredom=session_data['session_boredom'],
                
                # Mood
                session_mood=request.session_mood,
                top_session_mood=session_data.get('top_session_mood', request.session_mood),
                top_session_mood_rate=session_data.get('top_session_mood_rate', 0.0),
                mood_recommendation=session_data.get('mood_recommendation', request.session_mood),
                
                # Modulo
                modulo=session_data.get('modulo', 0.5),
                
                # Notions
                top_notions=[
                    TopNotionInfo(
                        notion_id=n.get('notion_id', ''),
                        notion_name=n.get('notion_name', ''),
                        notion_rate=n.get('notion_rate', 0),
                        priority_rate=n.get('priority_rate', 0),
                        complexity_rate=n.get('complexity_rate', 0)
                    )
                    for n in top_notions
                ],
                notion_processing=NotionProcessingInfo(
                    notions_decayed=notion_processing.get('notions_decayed', 0),
                    priorities_updated=notion_processing.get('priorities_updated', 0),
                    complexities_updated=notion_processing.get('complexities_updated', 0),
                    skipped_reason=notion_processing.get('skipped_reason')
                ),
                
                # Seen content
                seen_intents_count=len(session_data.get('seen_intents', [])),
                seen_subtopics_count=len(session_data.get('seen_subtopics', [])),
                
                # User state
                user_state=user_history.state.value,
                is_new_user=session_data.get('is_new_user', False),
                is_returning_user=session_data.get('is_returning_user', False),
                is_early_user=session_data.get('is_early_user', False),
                
                # Additional info
                welcome_message=session_data.get('welcome_message', ''),
                available_history_days=session_data.get('available_history_days'),
                days_away=session_data.get('days_away'),
                level_adjusted_from=session_data.get('level_adjusted_from')
            )
            
        finally:
            await pool.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/{session_id}")
async def get_session_status(session_id: str):
    """Get current session status with all calculated values"""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        
        try:
            async with pool.acquire() as conn:
                session = await conn.fetchrow("""
                    SELECT 
                        id, user_id, status, session_level,
                        session_mood, session_rank, session_nbr_cycle,
                        streak7, streak30, session_boredom, modulo,
                        top_session_mood, top_session_mood_rate,
                        mood_recommendation, completed_cycles,
                        session_score, is_returning_user,
                        created_at, completed_at
                    FROM session
                    WHERE id = $1
                """, session_id)
                
                if not session:
                    raise HTTPException(status_code=404, detail="Session not found")
                
                return {
                    "session_id": session['id'],
                    "user_id": session['user_id'],
                    "status": session['status'],
                    "rank": session['session_rank'],
                    "level": session['session_level'],
                    "mood": session['session_mood'],
                    "completed_cycles": session['completed_cycles'] or 0,
                    "total_cycles": session['session_nbr_cycle'],
                    "score": session['session_score'] or 0,
                    
                    # Calculated values
                    "streak7": float(session['streak7'] or 0),
                    "streak30": float(session['streak30'] or 0),
                    "boredom": float(session['session_boredom'] or 0),
                    "modulo": float(session['modulo'] or 0.5),
                    "top_mood": session['top_session_mood'],
                    "top_mood_rate": float(session['top_session_mood_rate'] or 0),
                    "mood_recommendation": session['mood_recommendation'],
                    
                    # Flags
                    "is_returning_user": session['is_returning_user'] or False,
                    
                    # Timestamps
                    "created_at": session['created_at'].isoformat() if session['created_at'] else None,
                    "completed_at": session['completed_at'].isoformat() if session['completed_at'] else None
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
                    SELECT user_id, session_level, session_boredom, modulo
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
                float(session['session_boredom'] or 0),
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
            
            return StartCycleResponse(
                cycle_id=cycle_data['cycle_id'],
                subtopic_id=cycle_data['subtopic_id'],
                first_interaction_id=cycle_data['first_interaction_id'],
                total_interactions=len(cycle_data.get('ordered_interactions', [])),
                cycle_level=cycle_level,
                cycle_boredom=cycle_boredom,
                cycle_goal=cycle_goal
            )
            
        finally:
            await pool.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start cycle: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# HEALTH CHECK
# ============================================================================

@router.get("/health")
async def session_management_health():
    """Health check for session management service"""
    return {
        "status": "healthy",
        "service": "session_management",
        "version": "2.0.0",
        "features": {
            "user_state_detection": "✅",
            "streak_calculations": "✅",
            "boredom_calculations": "✅",
            "mood_recommendation": "✅",
            "modulo_calculation": "✅",
            "notion_rate_decay": "✅",
            "notion_priority_calculation": "✅",
            "notion_complexity_calculation": "✅",
            "seen_content_tracking": "✅"
        }
    }
