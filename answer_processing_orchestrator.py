# answer_processing_orchestrator.py
"""
Answer Processing Orchestrator
Coordinates all services for complete answer processing workflow.
Supports three answer modes: voice, multipleButtons, singleButton
"""
import asyncpg
import logging
from typing import Dict, Optional

# Import existing services
from adjustement_adjuster import TranscriptionAdjuster
from matching_answer_service import answer_matching_service
from gpt_fallback_service import gpt_fallback_service

# Import session management services
from session_management import (
    answer_service,
    interaction_service,
    scoring_service,
    bonus_malus_service,
    cycle_service
)

logger = logging.getLogger(__name__)

# Tolerance window in seconds for singleButton tap matching
SINGLE_BUTTON_TOLERANCE_SECONDS = 2.0


async def process_user_answer_complete(
    interaction_id: str,
    user_id: str,
    db_pool: asyncpg.Pool,
    answer_mode_used: str = "voice",
    original_transcript: Optional[str] = None,
    selected_answer_id: Optional[str] = None,
    tapped_at_seconds: Optional[float] = None
) -> Dict:
    """
    Complete answer processing pipeline.
    Routes to the correct processor based on answer_mode_used.

    Modes:
    - voice:           original_transcript required
    - multipleButtons: selected_answer_id required
    - singleButton:    tapped_at_seconds required
    """
    logger.info(f"🎯 Processing [{answer_mode_used}] answer for interaction {interaction_id}")

    try:
        # ====================================================================
        # STEP 1: Create Answer Record
        # ====================================================================
        answer_id = await answer_service.create_answer(
            interaction_id=interaction_id,
            user_id=user_id,
            db_pool=db_pool,
            answer_mode_used=answer_mode_used,
            original_transcript=original_transcript,
            selected_answer_id=selected_answer_id,
            tapped_at_seconds=tapped_at_seconds
        )

        await interaction_service.increment_attempt_count(interaction_id, db_pool)
        logger.info(f"✅ Answer record created: {answer_id}")

        # ====================================================================
        # STEP 2: Route to correct processing pipeline
        # ====================================================================
        if answer_mode_used == "voice":
            return await _process_voice_answer(
                interaction_id, user_id, answer_id,
                original_transcript, db_pool
            )

        elif answer_mode_used == "multipleButtons":
            return await _process_multiple_buttons_answer(
                interaction_id, user_id, answer_id,
                selected_answer_id, db_pool
            )

        elif answer_mode_used == "singleButton":
            return await _process_single_button_answer(
                interaction_id, user_id, answer_id,
                tapped_at_seconds, db_pool
            )

        else:
            raise ValueError(f"Unknown answer_mode_used: {answer_mode_used}")

    except Exception as e:
        logger.error(f"❌ Error processing answer: {e}", exc_info=True)
        raise


# ============================================================================
# VOICE PIPELINE — existing logic, unchanged
# ============================================================================

async def _process_voice_answer(
    interaction_id: str,
    user_id: str,
    answer_id: str,
    original_transcript: str,
    db_pool: asyncpg.Pool
) -> Dict:

    if not original_transcript:
        raise ValueError("original_transcript is required for voice mode")

    # Adjustment
    adjuster = TranscriptionAdjuster()
    adjustment_result = await adjuster.adjust_transcription(
        request={
            "original_transcript": original_transcript,
            "interaction_id": interaction_id,
            "user_id": user_id
        },
        pool=db_pool
    )

    await answer_service.update_answer_with_adjustment(
        answer_id=answer_id,
        adjusted_transcript=adjustment_result.adjusted_transcript,
        completed_transcript=adjustment_result.completed_transcript,
        vocabulary_found=adjustment_result.list_of_vocabulary,
        entities_found=adjustment_result.list_of_entities,
        notion_matches=adjustment_result.list_of_notions,
        db_pool=db_pool
    )

    # Matching
    matching_result = await answer_matching_service.match_completed_transcript(
        interaction_id=interaction_id,
        completed_transcript=adjustment_result.completed_transcript,
        threshold=80
    )

    await answer_service.update_answer_with_matching(
        answer_id=answer_id,
        similarity_score=matching_result.get('similarity_score', 0),
        matched_answer_id=matching_result.get('answer_id'),
        db_pool=db_pool
    )

    if matching_result['match_found'] and matching_result['similarity_score'] >= 80:
        return await _complete_interaction(
            interaction_id, user_id, answer_id,
            matched_answer_id=matching_result.get('answer_id'),
            similarity_score=matching_result['similarity_score'],
            method="answer_match",
            cost_saved=0.002,
            db_pool=db_pool
        )
    else:
        return {
            "answer_id": answer_id,
            "status": "retry",
            "method": "no_match",
            "similarity_score": matching_result.get('similarity_score', 0),
            "interaction_score": 0,
            "interaction_complete": False,
            "cycle_complete": False,
            "feedback": _get_retry_feedback(matching_result.get('similarity_score', 0)),
            "gpt_used": False,
            "cost_saved": 0
        }


# ============================================================================
# MULTIPLE BUTTONS PIPELINE
# ============================================================================

async def _process_multiple_buttons_answer(
    interaction_id: str,
    user_id: str,
    answer_id: str,
    selected_answer_id: Optional[str],
    db_pool: asyncpg.Pool
) -> Dict:

    if not selected_answer_id:
        raise ValueError("selected_answer_id is required for multipleButtons mode")

    # Check if selected answer is linked to this interaction
    async with db_pool.acquire() as conn:
        is_correct = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM brain_interaction_answer
                WHERE interaction_id = (
                    SELECT brain_interaction_id 
                    FROM session_interaction 
                    WHERE id = $1
                )
                AND answer_id = $2
            )
        """, interaction_id, selected_answer_id)

    if is_correct:
        await answer_service.update_answer_with_matching(
            answer_id=answer_id,
            similarity_score=100.0,
            matched_answer_id=selected_answer_id,
            db_pool=db_pool
        )
        return await _complete_interaction(
            interaction_id, user_id, answer_id,
            matched_answer_id=selected_answer_id,
            similarity_score=100.0,
            method="multiple_buttons",
            cost_saved=0.002,
            db_pool=db_pool,
            answer_mode_used="multipleButtons"
        )
    else:
        await answer_service.update_answer_with_matching(
            answer_id=answer_id,
            similarity_score=0.0,
            matched_answer_id=None,
            db_pool=db_pool
        )
        return {
            "answer_id": answer_id,
            "status": "retry",
            "method": "multiple_buttons",
            "similarity_score": 0.0,
            "interaction_score": 0,
            "interaction_complete": False,
            "cycle_complete": False,
            "feedback": "Not quite — try again! 💪",
            "gpt_used": False,
            "cost_saved": 0
        }


# ============================================================================
# SINGLE BUTTON PIPELINE
# ============================================================================

async def _process_single_button_answer(
    interaction_id: str,
    user_id: str,
    answer_id: str,
    tapped_at_seconds: Optional[float],
    db_pool: asyncpg.Pool
) -> Dict:

    if tapped_at_seconds is None:
        raise ValueError("tapped_at_seconds is required for singleButton mode")

    # Fetch expected timer from brain_answer linked to this interaction
    async with db_pool.acquire() as conn:
        expected = await conn.fetchrow("""
            SELECT ba.id, ba.timer_seconds
            FROM brain_interaction_answer bia
            JOIN brain_answer ba ON bia.answer_id = ba.id
            WHERE bia.interaction_id = (
                SELECT brain_interaction_id 
                FROM session_interaction 
                WHERE id = $1
            )
            AND ba.timer_seconds IS NOT NULL
            LIMIT 1
        """, interaction_id)

    if not expected or expected['timer_seconds'] is None:
        logger.warning(f"⚠️ No timer_seconds found for interaction {interaction_id}")
        return {
            "answer_id": answer_id,
            "status": "retry",
            "method": "single_button",
            "similarity_score": 0.0,
            "interaction_score": 0,
            "interaction_complete": False,
            "cycle_complete": False,
            "feedback": "Tap when you catch the key moment! 👂",
            "gpt_used": False,
            "cost_saved": 0
        }

    delta = abs(tapped_at_seconds - float(expected['timer_seconds']))
    is_correct = delta <= SINGLE_BUTTON_TOLERANCE_SECONDS
    similarity = max(0.0, round((1.0 - delta / (SINGLE_BUTTON_TOLERANCE_SECONDS * 2)) * 100, 1))

    await answer_service.update_answer_with_matching(
        answer_id=answer_id,
        similarity_score=similarity if is_correct else 0.0,
        matched_answer_id=expected['id'] if is_correct else None,
        db_pool=db_pool
    )

    if is_correct:
        return await _complete_interaction(
            interaction_id, user_id, answer_id,
            matched_answer_id=expected['id'],
            similarity_score=similarity,
            method="single_button",
            cost_saved=0.002,
            db_pool=db_pool,
            answer_mode_used="singleButton",
            tapped_at_seconds=tapped_at_seconds,
            expected_seconds=float(expected['timer_seconds'])
        )
    else:
        return {
            "answer_id": answer_id,
            "status": "retry",
            "method": "single_button",
            "similarity_score": 0.0,
            "interaction_score": 0,
            "interaction_complete": False,
            "cycle_complete": False,
            "feedback": "Not quite — try to catch the right moment! 🎯",
            "gpt_used": False,
            "cost_saved": 0
        }


# ============================================================================
# SHARED: Complete interaction after any successful answer
# ============================================================================

async def _complete_interaction(
    interaction_id: str,
    user_id: str,
    answer_id: str,
    matched_answer_id: Optional[str],
    similarity_score: float,
    method: str,
    cost_saved: float,
    db_pool: asyncpg.Pool,
    answer_mode_used: str = "voice",
    tapped_at_seconds: Optional[float] = None,
    expected_seconds: Optional[float] = None
) -> Dict:

    if answer_mode_used == "multipleButtons":
        interaction_score = await scoring_service.calculate_multiple_buttons_score(
            interaction_id=interaction_id,
            db_pool=db_pool
        )
    elif answer_mode_used == "singleButton":
        interaction_score = await scoring_service.calculate_single_button_score(
            tapped_at_seconds=tapped_at_seconds or 0.0,
            expected_seconds=expected_seconds or 0.0
        )
    else:
        async with db_pool.acquire() as conn:
            user_level = await conn.fetchval("""
                SELECT sc.cycle_level
                FROM session_interaction si
                JOIN session_cycle sc ON si.cycle_id = sc.id
                WHERE si.id = $1
            """, interaction_id) or 100

        interaction_score = await scoring_service.calculate_interaction_score(
            interaction_id=interaction_id,
            matched_answer_id=matched_answer_id,
            similarity_score=similarity_score,
            user_id=user_id,
            user_level=user_level,
            db_pool=db_pool
        )

    await answer_service.mark_as_final_answer(
        answer_id=answer_id,
        processing_method=method,
        cost_saved=cost_saved,
        db_pool=db_pool
    )

    await interaction_service.complete_interaction(
        interaction_id=interaction_id,
        final_answer_id=answer_id,
        interaction_score=interaction_score,
        db_pool=db_pool
    )

    async with db_pool.acquire() as conn:
        cycle_id = await conn.fetchval("""
            SELECT cycle_id FROM session_interaction WHERE id = $1
        """, interaction_id)

    cycle_complete = await interaction_service.check_cycle_complete(cycle_id, db_pool)

    if cycle_complete:
        logger.info("🎊 Cycle completed!")
        await cycle_service.complete_cycle(cycle_id, db_pool)

    return {
        "answer_id": answer_id,
        "status": "success",
        "method": method,
        "similarity_score": similarity_score,
        "interaction_score": interaction_score,
        "interaction_complete": True,
        "cycle_complete": cycle_complete,
        "feedback": _get_feedback_for_score(interaction_score),
        "gpt_used": False,
        "cost_saved": cost_saved
    }


# ============================================================================
# Feedback helpers
# ============================================================================

def _get_feedback_for_score(score: int) -> str:
    if score >= 90:
        return "Excellent! Perfect answer! 🌟"
    elif score >= 80:
        return "Very good! Well done! 👍"
    elif score >= 70:
        return "Good job! 👌"
    elif score >= 60:
        return "Not bad! Keep practicing! 💪"
    else:
        return "Keep trying! You're learning! 📚"


def _get_retry_feedback(similarity: float) -> str:
    if similarity >= 60:
        return "Close! Try to be more specific. 🎯"
    elif similarity >= 40:
        return "You're on the right track. Try again! 💪"
    else:
        return "Not quite. Listen carefully and try again! 👂"
