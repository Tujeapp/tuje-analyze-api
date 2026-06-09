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
from routers.initial_session_router import _bucket_to_session_level
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
    session_type: str
    session_mood: str
    user_level: Optional[int] = None
    is_initial_session: Optional[bool] = None


class MoodRecommendationResponse(BaseModel):
    """Response for GET /mood-recommendation"""
    recommended_mood: str
    available_moods: List[str]


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
    Lean session-start response. Returns only what the iOS client reads:
    the session id (to drive the cycle call) and the two user_behavior values
    (rescue_level -> FrustrationTracker; always_silent -> voice/silent toggle).
    The full session calculation pipeline still runs server-side and is persisted
    on the session row / logged via log_session_summary; it is intentionally not
    returned here (no client consumer). See R25.
    """
    session_id: str
    rescue_level: float
    always_silent: bool


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

            # Determine if this should be an initial (curated onboarding) session.
            # Explicit flag wins; otherwise auto-detect from onboarding_phase.
            is_initial_session = request.is_initial_session
            user_goal_id = None
            user_bucket = None

            if user_history.state == UserState.BRAND_NEW:
                # Fetch user's onboarding_phase, goal_id, initial_level_bucket from brain_user
                async with pool.acquire() as conn:
                    user_row = await conn.fetchrow("""
                        SELECT onboarding_phase, goal_id, initial_level_bucket
                        FROM brain_user
                        WHERE id = $1
                    """, request.user_id)

                if user_row:
                    user_goal_id = user_row["goal_id"]
                    user_bucket = user_row["initial_level_bucket"]

                    # Auto-detect if not explicitly set
                    if is_initial_session is None:
                        is_initial_session = (user_row["onboarding_phase"] == "phase_1_in_progress")
            
            # Initialize session based on user state
            if user_history.state == UserState.BRAND_NEW:
                # Level for a user with no regular history comes from their onboarding
                # bucket (same mapping used at initial-session close-out). request.user_level
                # overrides if explicitly provided.
                if request.user_level is not None:
                    user_level = request.user_level
                else:
                    user_level = _bucket_to_session_level(user_bucket)
                session_data = await initialize_brand_new_user(
                    user_id=request.user_id,
                    session_type=request.session_type,
                    session_mood=request.session_mood,
                    user_level=user_level,
                    db_pool=pool,
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
            
            # Fetch or create user_behavior row (rescue_level, always_silent).
            # Mirrors the proven pattern in routers/session_router.py.
            async with pool.acquire() as conn:
                behavior = await conn.fetchrow("""
                    SELECT rescue_level, always_silent
                    FROM user_behavior WHERE user_id = $1
                """, request.user_id)

                if behavior is None:
                    await conn.execute("""
                        INSERT INTO user_behavior (user_id, rescue_level, always_silent)
                        VALUES ($1, 0.50, FALSE)
                    """, request.user_id)
                    rescue_level = 0.50
                    always_silent = False
                else:
                    rescue_level = float(behavior['rescue_level'])
                    always_silent = bool(behavior['always_silent'])

            return StartSessionResponse(
                session_id=session_data['session_id'],
                rescue_level=rescue_level,
                always_silent=always_silent,
            )
            
        finally:
            await pool.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mood-recommendation", response_model=MoodRecommendationResponse)
async def mood_recommendation(user_id: str):
    """
    Return the user's recommended session mood and the full list of available
    moods. iOS uses this to render the mood-selection panel before
    /start-session is called.

    Per TuJe_Session_RampUp_and_Cycle_Goal_Logic.md §4, the default
    recommendation is "effective". The full recommendation algorithm
    (based on history) is deferred — placeholder returns "effective"
    unconditionally for now. user_id is accepted so the contract is stable
    when the algorithm lands.
    """
    try:
        logger.info(f"Mood recommendation requested for user: {user_id}")

        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT name
                    FROM brain_session_mood
                    WHERE live = TRUE
                    ORDER BY name ASC
                """)
                available_moods = [row["name"] for row in rows]

            # Placeholder recommendation (per ramp-up doc §4). The casing matches
            # brain_session_mood.name (capitalized) — the canonical source for
            # what iOS receives and sends back to /start-session. helpers.py's
            # get_mood_types() lowercases internally so the existing search code
            # still works.
            recommended_mood = "Effective"

            # Defensive: if "effective" somehow isn't in the live list (e.g.
            # disabled in Airtable), fall back to the alphabetically-first
            # available mood.
            if recommended_mood not in available_moods:
                if available_moods:
                    logger.warning(
                        f"Recommended mood 'effective' is not live in "
                        f"brain_session_mood; falling back to "
                        f"{available_moods[0]!r}."
                    )
                    recommended_mood = available_moods[0]
                else:
                    # Truly empty list — return effective anyway with a warning.
                    # iOS will at least have something; the underlying data
                    # gap needs fixing in Airtable.
                    logger.error(
                        "brain_session_mood is empty or has no live rows. "
                        "Returning 'effective' as recommendation; iOS will "
                        "have no other choices to show."
                    )
                    available_moods = ["effective"]

            return MoodRecommendationResponse(
                recommended_mood=recommended_mood,
                available_moods=available_moods,
            )

        finally:
            await pool.close()

    except Exception as e:
        logger.error(f"Failed to get mood recommendation: {e}", exc_info=True)
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
                        started_at AS created_at, completed_at
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
