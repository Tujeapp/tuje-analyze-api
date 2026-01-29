"""
Mistakes Analysis Endpoint for Bubble Integration
=================================================

This module provides an endpoint to fetch detailed mistake information
after a user's answer has been matched to a brain_interaction_answer record.

Usage Flow:
1. User answers → Whisper transcription → Adjustment → Answer matching
2. Match found → Get interaction_answer record (which has list_of_mistakes)
3. Call this endpoint → Get full mistake details for UI display

Endpoint: POST /api/bubble/get-answer-mistakes
"""

import logging
import time
import asyncpg
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, validator
import os

logger = logging.getLogger(__name__)
router = APIRouter()

DATABASE_URL = os.getenv("DATABASE_URL")


# ============================================================
# PYDANTIC MODELS
# ============================================================

class MistakeDetail(BaseModel):
    """Full details of a single mistake"""
    id: str
    name_fr: str
    name_en: str
    description_fr: Optional[str] = None
    description_en: Optional[str] = None
    type: Optional[str] = None
    rule_code: Optional[str] = None
    conditions: Optional[str] = None


class GetAnswerMistakesRequest(BaseModel):
    """
    Request model - can use either:
    - interaction_answer_id: Direct ID of the brain_interaction_answer record
    - OR interaction_id + answer_id: The combination to find the record
    """
    interaction_answer_id: Optional[str] = None
    interaction_id: Optional[str] = None
    answer_id: Optional[str] = None
    
    @validator('interaction_answer_id', 'interaction_id', 'answer_id', pre=True)
    def clean_ids(cls, v):
        if v is not None:
            v = str(v).strip()
            return v if v else None
        return None
    
    def __init__(self, **data):
        super().__init__(**data)
        # Validate that we have either interaction_answer_id OR both interaction_id and answer_id
        if not self.interaction_answer_id and not (self.interaction_id and self.answer_id):
            raise ValueError(
                "Either 'interaction_answer_id' OR both 'interaction_id' and 'answer_id' must be provided"
            )


class GetAnswerMistakesResponse(BaseModel):
    """Response with full mistake details"""
    success: bool
    processing_time_ms: float
    timestamp: str
    
    # Input reference
    interaction_answer_id: Optional[str] = None
    interaction_id: Optional[str] = None
    answer_id: Optional[str] = None
    
    # Results
    has_mistakes: bool
    mistake_count: int
    mistakes: List[MistakeDetail]
    
    # For cost tracking (useful for analytics)
    mistake_ids: List[str] = []  # Raw IDs for reference
    
    # Error handling
    error: Optional[str] = None


# ============================================================
# ENDPOINT
# ============================================================

@router.get("/get-answer-mistakes/{interaction_answer_id}", response_model=GetAnswerMistakesResponse)
async def get_answer_mistakes_by_id(interaction_answer_id: str):
    """
    Get full mistake details using interaction_answer_id.
    
    **URL:** GET /api/bubble/get-answer-mistakes/INTANS202407190601
    
    **Response:**
    ```json
    {
        "success": true,
        "has_mistakes": true,
        "mistake_count": 1,
        "mistakes": [
            {
                "id": "MIST202407271502",
                "name_fr": "Accord du participe passé",
                "name_en": "Past participle agreement",
                "description_fr": "...",
                "type": "grammar"
            }
        ]
    }
    ```
    """
    start_time = time.time()
    
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        try:
            # Step 1: Get the interaction_answer record
            ia_row = await conn.fetchrow("""
                SELECT id, interaction_id, answer_id, list_of_mistakes
                FROM brain_interaction_answer
                WHERE id = $1 AND live = TRUE
            """, interaction_answer_id.strip())
            
            if not ia_row:
                processing_time = round((time.time() - start_time) * 1000, 2)
                return GetAnswerMistakesResponse(
                    success=False,
                    processing_time_ms=processing_time,
                    timestamp=datetime.now().isoformat(),
                    interaction_answer_id=interaction_answer_id,
                    has_mistakes=False,
                    mistake_count=0,
                    mistakes=[],
                    error="Interaction-Answer record not found"
                )
            
            list_of_mistakes = ia_row['list_of_mistakes'] or []
            
            # Step 2: No mistakes = return early
            if not list_of_mistakes:
                processing_time = round((time.time() - start_time) * 1000, 2)
                return GetAnswerMistakesResponse(
                    success=True,
                    processing_time_ms=processing_time,
                    timestamp=datetime.now().isoformat(),
                    interaction_answer_id=ia_row['id'],
                    interaction_id=ia_row['interaction_id'],
                    answer_id=ia_row['answer_id'],
                    has_mistakes=False,
                    mistake_count=0,
                    mistakes=[],
                    mistake_ids=[]
                )
            
            # Step 3: Fetch full mistake details
            mistakes_rows = await conn.fetch("""
                SELECT 
                    id, name_fr, name_en,
                    description_fr, description_en,
                    type, rule_code, conditions
                FROM brain_mistake
                WHERE id = ANY($1::varchar[]) AND live = TRUE
                ORDER BY name_fr ASC
            """, list_of_mistakes)
            
            mistakes = [
                MistakeDetail(
                    id=row['id'],
                    name_fr=row['name_fr'] or "",
                    name_en=row['name_en'] or "",
                    description_fr=row['description_fr'],
                    description_en=row['description_en'],
                    type=row['type'],
                    rule_code=row['rule_code'],
                    conditions=row['conditions']
                )
                for row in mistakes_rows
            ]
            
            processing_time = round((time.time() - start_time) * 1000, 2)
            logger.info(f"✅ Retrieved {len(mistakes)} mistakes in {processing_time}ms")
            
            return GetAnswerMistakesResponse(
                success=True,
                processing_time_ms=processing_time,
                timestamp=datetime.now().isoformat(),
                interaction_answer_id=ia_row['id'],
                interaction_id=ia_row['interaction_id'],
                answer_id=ia_row['answer_id'],
                has_mistakes=len(mistakes) > 0,
                mistake_count=len(mistakes),
                mistakes=mistakes,
                mistake_ids=list_of_mistakes
            )
            
        finally:
            await conn.close()
            
    except Exception as e:
        processing_time = round((time.time() - start_time) * 1000, 2)
        logger.error(f"❌ Error fetching mistakes: {e}")
        return GetAnswerMistakesResponse(
            success=False,
            processing_time_ms=processing_time,
            timestamp=datetime.now().isoformat(),
            interaction_answer_id=interaction_answer_id,
            has_mistakes=False,
            mistake_count=0,
            mistakes=[],
            error=str(e)
        )


# ============================================================
# ALTERNATIVE: Lightweight endpoint for just checking if mistakes exist
# ============================================================

class CheckMistakesResponse(BaseModel):
    """Lightweight response for quick mistake check"""
    success: bool
    has_mistakes: bool
    mistake_count: int
    mistake_ids: List[str] = []
    interaction_answer_id: Optional[str] = None
    error: Optional[str] = None


@router.get("/check-mistakes/{interaction_answer_id}", response_model=CheckMistakesResponse)
async def check_mistakes(interaction_answer_id: str):
    """
    Quick check if an answer has mistakes (without full details).
    
    Uses the interaction_answer_id directly from the matching process result.
    
    **URL:** GET /api/bubble/check-mistakes/INTANS202407190601
    
    **Response:**
    ```json
    {
        "success": true,
        "has_mistakes": true,
        "mistake_count": 2,
        "mistake_ids": ["MIST202407271502", "MIST202407271503"],
        "interaction_answer_id": "INTANS202407190601"
    }
    ```
    """
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        try:
            row = await conn.fetchrow("""
                SELECT list_of_mistakes
                FROM brain_interaction_answer
                WHERE id = $1 AND live = TRUE
            """, interaction_answer_id.strip())
            
            if not row:
                return CheckMistakesResponse(
                    success=False,
                    has_mistakes=False,
                    mistake_count=0,
                    interaction_answer_id=interaction_answer_id,
                    error="Interaction-Answer record not found"
                )
            
            mistakes = row['list_of_mistakes'] or []
            
            return CheckMistakesResponse(
                success=True,
                has_mistakes=len(mistakes) > 0,
                mistake_count=len(mistakes),
                mistake_ids=mistakes,
                interaction_answer_id=interaction_answer_id
            )
            
        finally:
            await conn.close()
            
    except Exception as e:
        logger.error(f"Error checking mistakes: {e}")
        return CheckMistakesResponse(
            success=False,
            has_mistakes=False,
            mistake_count=0,
            interaction_answer_id=interaction_answer_id,
            error=str(e)
        )
