# diagnostic_router.py
"""
Diagnostic / test-harness router — COMPLETELY PARALLEL to the session system.
Analyzes one interaction's voice answer (adjust + match) with NO session,
NO cycle, NO scoring, NO user history, and writes NOTHING to the DB.
Dev-only tool. Reuses the same services the split orchestrator uses.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import asyncpg
import logging
import os

from adjustement_adjuster import TranscriptionAdjuster
from adjustement_types import TranscriptionAdjustRequest
from matching_answer_service import answer_matching_service

logger = logging.getLogger(__name__)
router = APIRouter()

DATABASE_URL = os.getenv("DATABASE_URL")
MATCH_THRESHOLD = 80


class AnalyzeAnswerRequest(BaseModel):
    interaction_id: str          # brain_interaction id
    original_transcript: str


@router.post("/analyze-answer")
async def analyze_answer(request: AnalyzeAnswerRequest):
    """Session-free: adjust -> match -> return metadata. Writes nothing."""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        try:
            adjuster = TranscriptionAdjuster()
            adjustment = await adjuster.adjust_transcription(
                request=TranscriptionAdjustRequest(
                    original_transcript=request.original_transcript,
                    interaction_id=request.interaction_id,
                ),
                pool=pool,
            )

            match = await answer_matching_service.match_completed_transcript(
                interaction_id=request.interaction_id,
                completed_transcript=adjustment.completed_transcript,
                threshold=MATCH_THRESHOLD,
            )

            return {
                "interaction_id": request.interaction_id,
                "original_transcript": adjustment.original_transcript,
                "adjusted_transcript": adjustment.adjusted_transcript,
                "completed_transcript": adjustment.completed_transcript,
                "vocabulary_found": [v.dict() for v in adjustment.list_of_vocabulary],
                "entities_found": [e.dict() for e in adjustment.list_of_entities],
                "notion_matches": adjustment.list_of_notion_matches,
                "intent_matches": adjustment.list_of_intent_matches,
                "similarity_score": match.get("similarity_score") or 0,
                "matched_answer_id": match.get("answer_id"),
                "match_found": match.get("match_found", False),
            }
        finally:
            await pool.close()
    except Exception as e:
        logger.error(f"Diagnostic analyze-answer failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def diagnostic_health():
    return {"status": "healthy", "service": "diagnostic"}
