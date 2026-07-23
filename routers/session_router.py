# routers/session_router.py
"""
Session Management API Endpoints
Complete REST API for session, cycle, interaction, and answer management
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
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
    rescue_level: float
    always_silent: bool


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
    interaction_type_name: Optional[str] = None
    answer_mode: Optional[str] = "voice"


class SubmitAnswerRequest(BaseModel):
    interaction_id: str
    user_id: str
    answer_mode_used: str
    original_transcript: Optional[str] = None
    selected_answer_id: Optional[str] = None
    tapped_at_seconds: Optional[float] = None


class CycleSummary(BaseModel):
    cycle_id: str
    cycle_score: int
    cycle_rate: float
    average_interaction_score: float
    completed_interactions: int
    total_duration_seconds: int


class NextCycle(BaseModel):
    cycle_id: str
    cycle_number: int
    subtopic_id: str
    cycle_goal: str
    cycle_level: int
    cycle_boredom: float
    first_interaction_id: str
    first_brain_interaction_id: str
    total_interactions: int = 7


class SessionSummary(BaseModel):
    session_id: str
    status: str
    completed_cycles: int
    total_score: Optional[int] = None
    average_score_per_interaction: Optional[float] = None
    total_duration_seconds: Optional[int] = None
    completed_at: str


class SubmitAnswerResponse(BaseModel):
    # Existing answer-level fields
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

    # Cycle-level state
    cycle_complete: bool = False
    cycle_summary: Optional[CycleSummary] = None

    # Next-interaction state (mid-cycle advance)
    next_interaction_id: Optional[str] = None
    next_brain_interaction_id: Optional[str] = None
    interaction_number: Optional[int] = None

    # Next-cycle state (cycle just completed, new one opened)
    next_cycle: Optional[NextCycle] = None

    # Session-level state (final cycle complete)
    session_complete: bool = False
    session_summary: Optional[SessionSummary] = None


# ----------------------------------------------------------------------------
# CHUNK 1 — Split evaluate / commit / advance
# ----------------------------------------------------------------------------

class EvaluateAnswerRequest(BaseModel):
    interaction_id: str
    user_id: str
    answer_mode_used: str
    original_transcript: Optional[str] = None
    selected_answer_id: Optional[str] = None
    tapped_at_seconds: Optional[float] = None
    debug: bool = False


class EvaluateAnswerResponse(BaseModel):
    answer_id: str
    verdict: str
    similarity_score: float
    gpt_used: bool = False
    interpretation: Optional[str] = None
    mistakes: list = []
    matched_intents: list = []
    makes_sense: Optional[bool] = None
    debug: Optional[dict] = None
    status: str = "evaluated"


class InteractionHintResponse(BaseModel):
    found: bool
    hint_id: Optional[str] = None
    button: Optional[str] = None
    hint_level: Optional[int] = None
    type: Optional[str] = None
    media_kind: Optional[str] = None
    text_en: Optional[str] = None
    text_fr: Optional[str] = None
    text_phonetic: Optional[str] = None
    media_url: Optional[str] = None
    interaction_audio_url: Optional[str] = None


class HintVocabBlock(BaseModel):
    vocab_id: str
    audio_normal_url: Optional[str] = None
    audio_slow_url: Optional[str] = None
    text_fr: Optional[str] = None
    text_en: Optional[str] = None

class HintL3Reveal(BaseModel):
    transcription_fr: Optional[str] = None
    transcription_phonetic: Optional[str] = None
    transcription_en: Optional[str] = None

class InteractionHintL3Response(BaseModel):
    found: bool
    blocks: list[HintVocabBlock] = []
    reveal: Optional[HintL3Reveal] = None

class RecordNotUnderstoodVocabRequest(BaseModel):
    session_interaction_id: str
    vocab_ids: list[str] = []


class CommitAnswerRequest(BaseModel):
    interaction_id: str
    answer_id: str


class CommitAnswerResponse(BaseModel):
    interaction_id: str
    interaction_score: int
    verdict: str
    matched_answer_id: Optional[str] = None
    attempts_count: int
    completed_interactions: int
    total_interactions: int = 7
    interaction_complete: bool = True


class AdvanceInteractionRequest(BaseModel):
    interaction_id: str
    user_id: str


class AdvanceInteractionResponse(BaseModel):
    cycle_complete: bool = False
    already_advanced: bool = False
    next_interaction_id: Optional[str] = None
    next_brain_interaction_id: Optional[str] = None
    interaction_number: Optional[int] = None
    next_cycle: Optional[NextCycle] = None
    cycle_summary: Optional[CycleSummary] = None
    session_complete: bool = False
    session_summary: Optional[SessionSummary] = None

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

            # Fetch or create user_behavior row to get rescue_level
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

            return CreateSessionResponse(
                session_id=session_id,
                session_type=session['session_type'],
                expected_cycles=session['expected_cycles'],
                expected_total_score=session['expected_total_score'],
                status=session['status'],
                rescue_level=rescue_level,
                always_silent=always_silent
            )
            
        finally:
            await pool.close()
            
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class UpdateAlwaysSilentRequest(BaseModel):
    user_id: str
    always_silent: bool

@router.post("/update-always-silent")
async def update_always_silent(request: UpdateAlwaysSilentRequest):
    """Update user's persistent always_silent preference"""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        try:
            async with pool.acquire() as conn:
                await conn.execute("""
                    UPDATE user_behavior
                    SET always_silent = $2, updated_at = NOW()
                    WHERE user_id = $1
                """, request.user_id, request.always_silent)
            return {"status": "success", "always_silent": request.always_silent}
        finally:
            await pool.close()
    except Exception as e:
        logger.error(f"Failed to update always_silent: {e}")
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
                status=interaction['status'],
                interaction_type_name=interaction.get('interaction_type_name'),
                answer_mode=interaction.get('answer_mode', 'voice')
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
                db_pool=pool,
                answer_mode_used=request.answer_mode_used,
                original_transcript=request.original_transcript,
                selected_answer_id=request.selected_answer_id,
                tapped_at_seconds=request.tapped_at_seconds
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

# ============================================================================
# CHUNK 1 — EVALUATE / COMMIT / ADVANCE (additive; submit-answer untouched)
# ============================================================================

@router.post("/evaluate-answer", response_model=EvaluateAnswerResponse)
async def evaluate_answer(request: EvaluateAnswerRequest, http_request: Request):
    """Evaluate one attempt. Returns a verdict only — does not complete or advance."""
    try:
        from answer_split_orchestrator import evaluate_user_answer
        result = await evaluate_user_answer(
            interaction_id=request.interaction_id,
            user_id=request.user_id,
            db_pool=http_request.app.state.db_pool,
            answer_mode_used=request.answer_mode_used,
            original_transcript=request.original_transcript,
            selected_answer_id=request.selected_answer_id,
            tapped_at_seconds=request.tapped_at_seconds,
            debug=request.debug,
        )
        return EvaluateAnswerResponse(**result)
    except Exception as e:
        logger.error(f"Failed to evaluate answer: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/commit-answer", response_model=CommitAnswerResponse)
async def commit_answer_endpoint(request: CommitAnswerRequest, http_request: Request):
    """Lock the chosen attempt and complete the interaction. Does not advance."""
    try:
        from answer_split_orchestrator import commit_answer
        result = await commit_answer(
            interaction_id=request.interaction_id,
            answer_id=request.answer_id,
            db_pool=http_request.app.state.db_pool,
        )
        return CommitAnswerResponse(**result)
    except Exception as e:
        logger.error(f"Failed to commit answer: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/advance-interaction", response_model=AdvanceInteractionResponse)
async def advance_interaction_endpoint(request: AdvanceInteractionRequest, http_request: Request):
    """Advance after a committed interaction: next interaction / next cycle / session complete."""
    try:
        from answer_split_orchestrator import advance_after_interaction
        result = await advance_after_interaction(
            interaction_id=request.interaction_id,
            user_id=request.user_id,
            db_pool=http_request.app.state.db_pool,
        )
        return AdvanceInteractionResponse(**result)
    except Exception as e:
        logger.error(f"Failed to advance interaction: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/interaction-hint", response_model=InteractionHintResponse)
async def get_interaction_hint(
    http_request: Request,
    interaction_id: str,
    button: str,
    hint_level: int,
):
    """Serve one authored hint for an interaction, filtered by button + level.
    Resolves through brain_interaction.hint_ids. `button`/`type`/`usage` are
    author-managed text — we filter structurally on button + hint_level + live,
    never on hardcoded type/usage values. Returns found=false when nothing matches."""
    try:
        pool = http_request.app.state.db_pool
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT h.id, h.button, h.hint_level, h.type, h.media_kind,
                       h.text_en, h.text_fr, h.text_phonetic, h.media_url,
                       i.simplified_audio_url
                FROM brain_interaction i
                JOIN brain_hint h ON h.id = ANY(i.hint_ids)
                WHERE i.id = $1
                  AND h.button = $2
                  AND h.hint_level = $3
                  AND h.live = TRUE
                ORDER BY h.id ASC
                LIMIT 1
            """, interaction_id, button, hint_level)

        if not row:
            return InteractionHintResponse(found=False)

        return InteractionHintResponse(
            found=True,
            hint_id=row["id"],
            button=row["button"],
            hint_level=row["hint_level"],
            type=row["type"],
            media_kind=row["media_kind"],
            text_en=row["text_en"],
            text_fr=row["text_fr"],
            text_phonetic=row["text_phonetic"],
            media_url=row["media_url"],
            interaction_audio_url=row["simplified_audio_url"],
        )
    except Exception as e:
        logger.error(f"Failed to fetch interaction hint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/interaction-hint-l3", response_model=InteractionHintL3Response)
async def get_interaction_hint_l3(
    http_request: Request,
    interaction_id: str,
):
    """Serve the Understand-L3 vocab-block comprehension flow for an interaction:
    the ordered vocab blocks (each with normal+slow audio) and the final
    translation reveal (fr / phonetic / en). Blocks come from
    brain_interaction.interaction_vocab_id in ARRAY ORDER (order authored in
    Airtable, preserved through sync). found=false when no L3 hint is authored
    or no blocks are linked."""
    try:
        pool = http_request.app.state.db_pool
        async with pool.acquire() as conn:
            # Gate: only serve L3 if an understand/level-3 hint is authored & live.
            has_l3 = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1
                    FROM brain_interaction i
                    JOIN brain_hint h ON h.id = ANY(i.hint_ids)
                    WHERE i.id = $1 AND h.button = 'understand'
                      AND h.hint_level = 3 AND h.live = TRUE
                )
            """, interaction_id)
            if not has_l3:
                return InteractionHintL3Response(found=False)

            # Interaction: ordered vocab id list + reveal fields.
            irow = await conn.fetchrow("""
                SELECT interaction_vocab_id,
                       transcription_fr, transcription_phonetic, transcription_en
                FROM brain_interaction WHERE id = $1
            """, interaction_id)
            if not irow or not irow["interaction_vocab_id"]:
                return InteractionHintL3Response(found=False)

            ordered_ids = list(irow["interaction_vocab_id"])

            # Fetch the block vocab rows (unordered from DB), then re-order in Python
            # to match interaction_vocab_id's array order (the authored sequence).
            vrows = await conn.fetch("""
                SELECT id, audio_normal_url, audio_slow_url,
                       transcription_fr, transcription_en
                FROM brain_vocab
                WHERE id = ANY($1::varchar[]) AND live = TRUE
            """, ordered_ids)
            by_id = {r["id"]: r for r in vrows}

            blocks = []
            for vid in ordered_ids:
                r = by_id.get(vid)
                if not r:
                    continue  # skip missing/non-live vocab, preserve order of the rest
                blocks.append(HintVocabBlock(
                    vocab_id=r["id"],
                    audio_normal_url=r["audio_normal_url"],
                    audio_slow_url=r["audio_slow_url"],
                    text_fr=r["transcription_fr"],
                    text_en=r["transcription_en"],
                ))

        reveal = HintL3Reveal(
            transcription_fr=irow["transcription_fr"],
            transcription_phonetic=irow["transcription_phonetic"],
            transcription_en=irow["transcription_en"],
        )
        return InteractionHintL3Response(found=True, blocks=blocks, reveal=reveal)
    except Exception as e:
        logger.error(f"Failed to fetch L3 hint flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/record-not-understood-vocab")
async def record_not_understood_vocab(
    http_request: Request,
    request: RecordNotUnderstoodVocabRequest,
):
    """L3b: persist which vocab blocks the user marked as not understood during
    the Understand-L3 flow. Written to session_interaction.not_understood_vocab_ids.
    Replaces (not appends) — the L3 flow runs once per interaction. An empty list
    is valid and meaningful (user understood every block)."""
    try:
        pool = http_request.app.state.db_pool
        async with pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE session_interaction
                SET not_understood_vocab_ids = $2::text[]
                WHERE id = $1
            """, request.session_interaction_id, list(request.vocab_ids))
        updated = result.split()[-1] if result else "0"
        if updated == "0":
            logger.warning(
                f"record-not-understood-vocab: no session_interaction matched "
                f"{request.session_interaction_id}"
            )
        return {"status": "recorded", "count": len(request.vocab_ids)}
    except Exception as e:
        logger.error(f"Failed to record not-understood vocab: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

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
