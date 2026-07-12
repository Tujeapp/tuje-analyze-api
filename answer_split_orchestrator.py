# answer_split_orchestrator.py
"""
Split answer pipeline: evaluate / commit / advance.
Additive replacement for the fused process_user_answer_complete.
answer_processing_orchestrator.py (legacy submit-answer) is left untouched.

Chunk 1: structural split only.
- Button correctness still uses the existing linkage check (Chunk 2 replaces it).
- Voice verdict thresholds are PLACEHOLDERS (Rémi supplies real cutoffs).
"""
import asyncpg
import json
import logging
from typing import Dict, Optional

from adjustement_adjuster import TranscriptionAdjuster
from adjustement_types import TranscriptionAdjustRequest
from matching_answer_service import answer_matching_service
from gpt_fallback_service import gpt_fallback_service

from session_management import (
    answer_service,
    interaction_service,
    scoring_service,
    session_service,
)

from cycle_manager.cycle_creation import advance_to_next_interaction, start_new_cycle
from cycle_manager.cycle_completion import complete_cycle as cycle_completion_complete
from cycle_manager.cycle_calculations import (
    calculate_cycle_level,
    calculate_cycle_boredom,
    calculate_cycle_goal,
)
from session_context import SessionContext

logger = logging.getLogger(__name__)

# ---- Voice verdict thresholds (PLACEHOLDER — Rémi to supply real cutoffs) ----
VERDICT_PERFECT_MIN = 95
VERDICT_GOOD_MIN = 80      # == current match threshold
VERDICT_WRONG_MIN = 50
# below VERDICT_WRONG_MIN  ->  not_understood

MATCH_THRESHOLD = 80
SINGLE_BUTTON_TOLERANCE_SECONDS = 2.0
GPT_THRESHOLD = 70


async def _fetch_answer_type_and_mistakes(interaction_answer_id, db_pool):
    """Given a matched brain_interaction_answer.id, return (answer_type, mistakes).
    answer_type drives the verdict (answer quality); mistakes are the linguistic
    errors attached to that join row. Never raises — failure returns (None, [])
    so evaluate still succeeds."""
    if not interaction_answer_id:
        return None, []
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT answer_type, mistake_ids
                FROM brain_interaction_answer WHERE id = $1
            """, interaction_answer_id)
            if not row:
                return None, []
            answer_type = row["answer_type"]
            mistake_ids = row["mistake_ids"]
            mistakes = []
            if mistake_ids:
                mrows = await conn.fetch("""
                    SELECT id, name_fr, name_en, description_fr, description_en, type
                    FROM brain_mistake
                    WHERE id = ANY($1::varchar[]) AND live = TRUE
                    ORDER BY name_fr ASC
                """, list(mistake_ids))
                mistakes = [
                    {
                        "id": r["id"],
                        "name_fr": r["name_fr"] or "",
                        "name_en": r["name_en"] or "",
                        "description_fr": r["description_fr"],
                        "description_en": r["description_en"],
                        "type": r["type"],
                    }
                    for r in mrows
                ]
        return answer_type, mistakes
    except Exception as e:
        logger.error(f"answer_type/mistakes fetch failed for {interaction_answer_id}: {e}")
        return None, []


def _answer_type_to_verdict(answer_type: str) -> str:
    """Answer quality → verdict. Mirrors the button model: perfect/good are
    correct; false good/wrong are 'wrong'. (Similarity only decided we matched
    this answer; answer_type decides whether the answer is any good.)"""
    if answer_type == "perfect":
        return "perfect"
    if answer_type == "good":
        return "good"
    # 'false good' and 'wrong' are both wrong-quality answers
    return "wrong"


def _voice_verdict(similarity: float) -> str:
    if similarity >= VERDICT_PERFECT_MIN:
        return "perfect"
    if similarity >= VERDICT_GOOD_MIN:
        return "good"
    if similarity >= VERDICT_WRONG_MIN:
        return "wrong"
    return "not_understood"


# ============================================================================
# EVALUATE
# ============================================================================

async def evaluate_user_answer(
    interaction_id: str,
    user_id: str,
    db_pool: asyncpg.Pool,
    answer_mode_used: str = "voice",
    original_transcript: Optional[str] = None,
    selected_answer_id: Optional[str] = None,
    tapped_at_seconds: Optional[float] = None,
) -> Dict:
    """Evaluate one attempt. Creates the answer row, increments the attempt
    counter, returns a verdict + provisional similarity. Does NOT complete or
    advance. Retry = call again."""
    answer_id = await answer_service.create_answer(
        interaction_id=interaction_id,
        user_id=user_id,
        db_pool=db_pool,
        answer_mode_used=answer_mode_used,
        original_transcript=original_transcript,
        selected_answer_id=selected_answer_id,
        tapped_at_seconds=tapped_at_seconds,
    )
    await interaction_service.increment_attempt_count(interaction_id, db_pool)

    if answer_mode_used == "voice":
        return await _evaluate_voice(interaction_id, user_id, answer_id, original_transcript, db_pool)
    elif answer_mode_used == "multipleButtons":
        return await _evaluate_multiple_buttons(interaction_id, answer_id, selected_answer_id, db_pool)
    elif answer_mode_used == "singleButton":
        return await _evaluate_single_button(interaction_id, answer_id, tapped_at_seconds, db_pool)
    else:
        raise ValueError(f"Unknown answer_mode_used: {answer_mode_used}")


async def _evaluate_voice(interaction_id, user_id, answer_id, original_transcript, db_pool) -> Dict:
    if not original_transcript:
        raise ValueError("original_transcript is required for voice mode")

    # The adjuster and matcher look up brain_interaction / brain_interaction_answer,
    # which are keyed by BRAIN interaction id. `interaction_id` here is the
    # session_interaction id, so resolve to the brain id for those lookups.
    # (create_answer / update_answer_* still use the session id — they key on
    # session_answer / session_interaction — so those calls are unchanged.)
    async with db_pool.acquire() as conn:
        brain_interaction_id = await conn.fetchval(
            "SELECT brain_interaction_id FROM session_interaction WHERE id = $1",
            interaction_id,
        )
    if not brain_interaction_id:
        raise ValueError(f"No brain_interaction_id for session interaction {interaction_id}")

    adjuster = TranscriptionAdjuster()
    adjustment_result = await adjuster.adjust_transcription(
        request=TranscriptionAdjustRequest(
            original_transcript=original_transcript,
            interaction_id=brain_interaction_id,
            user_id=user_id,
        ),
        pool=db_pool,
    )
    await answer_service.update_answer_with_adjustment(
        answer_id=answer_id,
        adjusted_transcript=adjustment_result.adjusted_transcript,
        completed_transcript=adjustment_result.completed_transcript,
        vocabulary_found=json.dumps([v.dict() for v in adjustment_result.list_of_vocabulary]),
        entities_found=json.dumps([e.dict() for e in adjustment_result.list_of_entities]),
        notion_matches=json.dumps(adjustment_result.list_of_notion_matches),
        db_pool=db_pool,
    )

    matching_result = await answer_matching_service.match_completed_transcript(
        interaction_id=brain_interaction_id,
        completed_transcript=adjustment_result.completed_transcript,
        threshold=MATCH_THRESHOLD,
    )
    similarity = matching_result.get("similarity_score") or 0
    await answer_service.update_answer_with_matching(
        answer_id=answer_id,
        similarity_score=similarity,
        matched_answer_id=matching_result.get("answer_id"),
        db_pool=db_pool,
    )

    # Match quality (similarity) tells us WHETHER we identified the answer;
    # answer_type tells us the QUALITY of that answer. Verdict = answer quality.
    match_found = bool(matching_result.get("match_found"))
    interaction_answer_id = matching_result.get("interaction_answer_id")

    answer_type, mistakes = await _fetch_answer_type_and_mistakes(
        interaction_answer_id, db_pool
    )

    if not match_found or answer_type is None:
        verdict = "not_understood"
    else:
        verdict = _answer_type_to_verdict(answer_type)

    interpretation = None
    gpt_used = False
    if verdict == "not_understood":
        interpretation, gpt_used = await _run_gpt_interpretation(
            interaction_id, original_transcript, db_pool
        )

    return {
        "answer_id": answer_id,
        "verdict": verdict,
        "similarity_score": similarity,
        "gpt_used": gpt_used,
        "interpretation": interpretation,
        "mistakes": mistakes,
        "status": "evaluated",
    }


async def _run_gpt_interpretation(session_interaction_id, original_transcript, db_pool):
    """Call GPT fallback for a not_understood voice answer. Never raises —
    a GPT failure returns (None, False) so evaluate still succeeds.
    Note: gpt_fallback_service expects the BRAIN interaction id."""
    try:
        async with db_pool.acquire() as conn:
            brain_interaction_id = await conn.fetchval(
                "SELECT brain_interaction_id FROM session_interaction WHERE id = $1",
                session_interaction_id,
            )
        if not brain_interaction_id:
            return None, False

        result = await gpt_fallback_service.analyze_intent(
            interaction_id=brain_interaction_id,
            original_transcript=original_transcript,
            threshold=GPT_THRESHOLD,
            pool=db_pool,
        )
        interpretation = (
            result.get("gpt_reasoning")
            if result.get("intent_matched")
            else result.get("gpt_alternative_interpretation")
        )
        return interpretation, True
    except Exception as e:
        logger.error(f"GPT interpretation failed: {e}")
        return None, False


async def _evaluate_multiple_buttons(interaction_id, answer_id, selected_answer_id, db_pool) -> Dict:
    if not selected_answer_id:
        raise ValueError("selected_answer_id is required for multipleButtons mode")

    # CHUNK 2: correctness + score derive from answer_type (not linkage).
    # Live answer_type values: 'perfect' | 'good' | 'false good' | 'wrong'.
    async with db_pool.acquire() as conn:
        answer_type = await conn.fetchval("""
            SELECT bia.answer_type
            FROM brain_interaction_answer bia
            WHERE bia.interaction_id = (
                SELECT brain_interaction_id FROM session_interaction WHERE id = $1
            )
            AND bia.answer_id = $2
        """, interaction_id, selected_answer_id)

    # answer_type -> (score, verdict). perfect/good = correct; false good/wrong = wrong.
    type_map = {
        "perfect":    (100.0, "perfect"),
        "good":       (70.0,  "good"),
        "false good": (50.0,  "wrong"),
        "wrong":      (30.0,  "wrong"),
    }

    if answer_type is None:
        # Selected id isn't linked to this interaction at all — treat as wrong, score 0.
        logger.warning(f"multipleButtons: answer {selected_answer_id} not linked to interaction {interaction_id}")
        score, verdict = 0.0, "wrong"
    else:
        score, verdict = type_map.get(answer_type, (0.0, "wrong"))
        if answer_type not in type_map:
            logger.warning(f"multipleButtons: unknown answer_type '{answer_type}' — scoring 0")

    await answer_service.update_answer_with_matching(
        answer_id=answer_id,
        similarity_score=score,
        matched_answer_id=selected_answer_id if verdict in ("perfect", "good") else None,
        db_pool=db_pool,
    )

    return {
        "answer_id": answer_id,
        "verdict": verdict,
        "similarity_score": score,
        "gpt_used": False,
        "interpretation": None,
        "status": "evaluated",
    }


async def _evaluate_single_button(interaction_id, answer_id, tapped_at_seconds, db_pool) -> Dict:
    if tapped_at_seconds is None:
        raise ValueError("tapped_at_seconds is required for singleButton mode")

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

    if not expected or expected["timer_seconds"] is None:
        await answer_service.update_answer_with_matching(
            answer_id=answer_id, similarity_score=0.0, matched_answer_id=None, db_pool=db_pool,
        )
        return {"answer_id": answer_id, "verdict": "incorrect", "similarity_score": 0.0,
                "gpt_used": False, "interpretation": None, "status": "evaluated"}

    delta = abs(tapped_at_seconds - float(expected["timer_seconds"]))
    is_correct = delta <= SINGLE_BUTTON_TOLERANCE_SECONDS
    similarity = (
        max(0.0, round((1.0 - delta / (SINGLE_BUTTON_TOLERANCE_SECONDS * 2)) * 100, 1))
        if is_correct else 0.0
    )

    await answer_service.update_answer_with_matching(
        answer_id=answer_id,
        similarity_score=similarity,
        matched_answer_id=expected["id"] if is_correct else None,
        db_pool=db_pool,
    )

    return {"answer_id": answer_id,
            "verdict": "correct" if is_correct else "incorrect",
            "similarity_score": similarity,
            "gpt_used": False, "interpretation": None, "status": "evaluated"}


# ============================================================================
# COMMIT
# ============================================================================

async def commit_answer(interaction_id: str, answer_id: str, db_pool: asyncpg.Pool) -> Dict:
    """Lock the chosen attempt and complete the interaction. Does NOT advance.
    Idempotent: re-committing an already-completed interaction returns its recap."""
    async with db_pool.acquire() as conn:
        interaction = await conn.fetchrow("""
            SELECT si.status, si.cycle_id, sc.cycle_level
            FROM session_interaction si
            JOIN session_cycle sc ON si.cycle_id = sc.id
            WHERE si.id = $1
        """, interaction_id)
    if not interaction:
        raise ValueError(f"Interaction not found: {interaction_id}")

    if interaction["status"] == "completed":
        logger.info(f"commit_answer: {interaction_id} already completed — returning existing recap")
        return await _commit_recap(interaction_id, db_pool)

    async with db_pool.acquire() as conn:
        answer = await conn.fetchrow("""
            SELECT answer_mode_used, similarity_score, matched_answer_id,
                   tapped_at_seconds, user_id
            FROM session_answer WHERE id = $1
        """, answer_id)
    if not answer:
        raise ValueError(f"Answer not found: {answer_id}")

    mode = answer["answer_mode_used"]
    similarity = float(answer["similarity_score"] or 0)
    matched_answer_id = answer["matched_answer_id"]
    user_level = interaction["cycle_level"] or 100

    if mode == "multipleButtons":
        # CHUNK 2: score was derived from answer_type at evaluate and stored on
        # the answer's similarity_score. Use it directly instead of the old
        # attempt-based calculate_multiple_buttons_score.
        score = int(round(similarity))
        method = "multiple_buttons"
    elif mode == "singleButton":
        async with db_pool.acquire() as conn:
            expected_seconds = await conn.fetchval("""
                SELECT ba.timer_seconds
                FROM brain_interaction_answer bia
                JOIN brain_answer ba ON bia.answer_id = ba.id
                WHERE bia.interaction_id = (
                    SELECT brain_interaction_id FROM session_interaction WHERE id = $1
                )
                AND ba.timer_seconds IS NOT NULL
                LIMIT 1
            """, interaction_id)
        score = await scoring_service.calculate_single_button_score(
            tapped_at_seconds=float(answer["tapped_at_seconds"] or 0.0),
            expected_seconds=float(expected_seconds or 0.0))
        method = "single_button"
    else:  # voice
        score = await scoring_service.calculate_interaction_score(
            interaction_id=interaction_id,
            matched_answer_id=matched_answer_id,
            similarity_score=similarity,
            user_id=answer["user_id"],
            user_level=user_level,
            db_pool=db_pool)
        method = "answer_match"

    await answer_service.mark_as_final_answer(
        answer_id=answer_id, processing_method=method, cost_saved=0.002, db_pool=db_pool)
    await interaction_service.complete_interaction(
        interaction_id=interaction_id, final_answer_id=answer_id,
        interaction_score=score, db_pool=db_pool)

    return await _commit_recap(interaction_id, db_pool)


async def _commit_recap(interaction_id: str, db_pool: asyncpg.Pool) -> Dict:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT si.interaction_score, si.attempts_count,
                   sc.completed_interactions,
                   sa.similarity_score, sa.matched_answer_id, sa.answer_mode_used
            FROM session_interaction si
            JOIN session_cycle sc ON si.cycle_id = sc.id
            LEFT JOIN session_answer sa ON si.final_answer_id = sa.id
            WHERE si.id = $1
        """, interaction_id)

    mode = row["answer_mode_used"]
    similarity = float(row["similarity_score"] or 0)
    if mode == "voice":
        verdict = _voice_verdict(similarity)
    else:
        verdict = "correct" if row["matched_answer_id"] is not None else "incorrect"

    return {
        "interaction_id": interaction_id,
        "interaction_score": row["interaction_score"] or 0,
        "verdict": verdict,
        "matched_answer_id": row["matched_answer_id"],
        "attempts_count": row["attempts_count"] or 0,
        "completed_interactions": row["completed_interactions"] or 0,
        "total_interactions": 7,
        "interaction_complete": True,
    }


# ============================================================================
# ADVANCE
# ============================================================================

async def advance_after_interaction(interaction_id: str, user_id: str, db_pool: asyncpg.Pool) -> Dict:
    """Advance after a committed interaction: next interaction, or open next
    cycle, or complete session. Idempotent guards prevent double-advance."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT si.cycle_id, si.interaction_number, si.session_id,
                   s.session_level, s.session_boredom, s.session_mood
            FROM session_interaction si
            JOIN session s ON si.session_id = s.id
            WHERE si.id = $1
        """, interaction_id)
    if not row:
        raise ValueError(f"Interaction not found: {interaction_id}")

    cycle_id = row["cycle_id"]
    interaction_number = row["interaction_number"]
    session_id = row["session_id"]
    session_level = row["session_level"]
    session_boredom = float(row["session_boredom"] or 0)
    session_mood = row["session_mood"]

    base = {
        "cycle_complete": False,
        "already_advanced": False,
        "next_interaction_id": None,
        "next_brain_interaction_id": None,
        "interaction_number": None,
        "next_cycle": None,
        "cycle_summary": None,
        "session_complete": False,
        "session_summary": None,
    }

    cycle_complete = await interaction_service.check_cycle_complete(cycle_id, db_pool)

    if not cycle_complete:
        async with db_pool.acquire() as conn:
            existing_next = await conn.fetchrow("""
                SELECT id, brain_interaction_id, interaction_number
                FROM session_interaction
                WHERE cycle_id = $1 AND interaction_number = $2
            """, cycle_id, interaction_number + 1)
        if existing_next:
            base.update({
                "next_interaction_id": existing_next["id"],
                "next_brain_interaction_id": existing_next["brain_interaction_id"],
                "interaction_number": existing_next["interaction_number"],
            })
            return base

        async with db_pool.acquire() as conn:
            pool_ids = await conn.fetchval(
                "SELECT candidate_pool_ids FROM session_cycle WHERE id = $1", cycle_id)
        if not pool_ids or len(pool_ids) < 7:
            logger.error(f"Cycle {cycle_id} has no candidate pool "
                         f"(size={len(pool_ids) if pool_ids else 0}). Cannot advance.")
            return base

        advance_result = await advance_to_next_interaction(
            cycle_id=cycle_id,
            session_id=session_id,
            current_interaction_number=interaction_number,
            ordered_interaction_ids=list(pool_ids),
            db_pool=db_pool,
        )
        if not advance_result.get("cycle_complete"):
            base.update({
                "next_interaction_id": advance_result["next_interaction_id"],
                "next_brain_interaction_id": advance_result["brain_interaction_id"],
                "interaction_number": advance_result["interaction_number"],
            })
        return base

    base["cycle_complete"] = True

    async with db_pool.acquire() as conn:
        cycle_status = await conn.fetchval(
            "SELECT status FROM session_cycle WHERE id = $1", cycle_id)
    if cycle_status == "completed":
        logger.info(f"advance: cycle {cycle_id} already completed — already_advanced")
        base["already_advanced"] = True
        return base

    cycle_result = await cycle_completion_complete(
        cycle_id=cycle_id, session_id=session_id, db_pool=db_pool)
    base["cycle_summary"] = {
        "cycle_id": cycle_result["cycle_id"],
        "cycle_score": cycle_result["cycle_score"],
        "cycle_rate": cycle_result["cycle_rate"],
        "average_interaction_score": cycle_result["average_interaction_score"],
        "completed_interactions": cycle_result["completed_interactions"],
        "total_duration_seconds": cycle_result["total_duration_seconds"],
    }

    async with db_pool.acquire() as conn:
        completed_cycles = await conn.fetchval(
            "SELECT completed_cycles FROM session WHERE id = $1", session_id)

    if completed_cycles < 3:
        next_cycle_number = completed_cycles + 1
        next_cycle_level = await calculate_cycle_level(
            session_id, next_cycle_number, session_level, db_pool)
        next_cycle_boredom = await calculate_cycle_boredom(
            session_id, next_cycle_number, session_boredom, db_pool)
        next_cycle_goal = await calculate_cycle_goal(
            session_id, next_cycle_number, db_pool)

        next_context = await SessionContext.load(user_id, db_pool)
        next_cycle_result = await start_new_cycle(
            session_id=session_id,
            context=next_context,
            cycle_number=next_cycle_number,
            cycle_goal=next_cycle_goal,
            cycle_boredom=next_cycle_boredom,
            cycle_level=next_cycle_level,
            interaction_user_level=next_cycle_level,
            session_mood=session_mood,
            db_pool=db_pool,
        )
        base["next_cycle"] = {
            "cycle_id": next_cycle_result["cycle_id"],
            "cycle_number": next_cycle_number,
            "subtopic_id": next_cycle_result["subtopic_id"],
            "cycle_goal": next_cycle_goal,
            "cycle_level": next_cycle_level,
            "cycle_boredom": float(next_cycle_boredom),
            "first_interaction_id": next_cycle_result["first_interaction_id"],
            "first_brain_interaction_id": next_cycle_result["ordered_interactions"][0],
        }
    else:
        base["session_complete"] = True
        await session_service.complete_session(session_id, db_pool)
        async with db_pool.acquire() as conn:
            cs = await conn.fetchrow("""
                SELECT id, status, completed_cycles, total_score,
                       average_score_per_interaction, total_duration_seconds, completed_at
                FROM session WHERE id = $1
            """, session_id)
        base["session_summary"] = {
            "session_id": cs["id"],
            "status": cs["status"],
            "completed_cycles": cs["completed_cycles"],
            "total_score": cs["total_score"],
            "average_score_per_interaction": (
                float(cs["average_score_per_interaction"])
                if cs["average_score_per_interaction"] is not None else None
            ),
            "total_duration_seconds": cs["total_duration_seconds"],
            "completed_at": cs["completed_at"].isoformat() if cs["completed_at"] else None,
        }

    return base
