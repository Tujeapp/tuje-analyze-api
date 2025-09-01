# 1. CREATE NEW FILE: adjustement_types.py (Pydantic models ONLY)
from pydantic import BaseModel, validator
from typing import List, Optional

class TranscriptionAdjustRequest(BaseModel):
    original_transcript: str
    user_id: Optional[str] = None
    interaction_id: Optional[str] = None
    expected_entities_ids: Optional[List[str]] = None  
    
    @validator('original_transcript')
    def validate_transcript(cls, v):
        if not v or not v.strip():
            raise ValueError("Original transcript cannot be empty")
        if len(v) > 1000:
            raise ValueError("Transcript too long (max 1000 characters)")
        return v.strip()

class VocabularyMatch(BaseModel):
    id: str
    transcription_fr: str
    transcription_adjusted: str

class EntityMatch(BaseModel):
    id: str
    name: str
    value: str

class NotionMatch(BaseModel):
    notion_id: str
    vocabulary_id: str
    vocabulary_transcription: str

class AdjustmentResult(BaseModel):
    original_transcript: str
    pre_adjusted_transcript: str
    adjusted_transcript: str
    completed_transcript: str
    list_of_vocabulary: List[VocabularyMatch]
    list_of_entities: List[EntityMatch]
    list_of_notion_matches: List[str]  # ✅ ADD THIS LINE
    processing_time_ms: float

class BatchAdjustRequest(BaseModel):
    requests: List[TranscriptionAdjustRequest]
    
    @validator('requests')
    def validate_batch_size(cls, v):
        if len(v) > 50:
            raise ValueError("Batch size too large (max 50)")
        if len(v) == 0:
            raise ValueError("Batch cannot be empty")
        return v

class BatchAdjustResult(BaseModel):
    batch_results: List[dict]
    processed_count: int
    success_count: int
    error_count: int

# 2. UPDATE adjustement_models.py (API routes ONLY, no models)
from fastapi import APIRouter, HTTPException
import asyncpg
import logging
import os

# FIXED: Import from types file instead of defining models here
from adjustement_types import (
    TranscriptionAdjustRequest,
    AdjustmentResult,
    BatchAdjustRequest,
    BatchAdjustResult
)
from adjustement_adjuster import TranscriptionAdjuster

logger = logging.getLogger(__name__)
router = APIRouter()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Missing required environment variable: DATABASE_URL")

# Global adjuster instance
adjuster = TranscriptionAdjuster()

@router.post("/adjust-transcription", response_model=AdjustmentResult)
async def adjust_transcription_endpoint(request: TranscriptionAdjustRequest):
    """API endpoint for single transcription adjustment"""
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    
    try:
        result = await adjuster.adjust_transcription(request, pool)
        return result
    except Exception as e:
        logger.error(f"Transcription adjustment failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await pool.close()

@router.post("/batch-adjust-transcriptions", response_model=BatchAdjustResult)
async def batch_adjust_transcriptions(request: BatchAdjustRequest):
    """Batch processing for cost optimization"""
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=5)
    
    try:
        results = []
        success_count = 0
        error_count = 0
        
        for single_request in request.requests:
            try:
                result = await adjuster.adjust_transcription(single_request, pool)
                results.append({"success": True, "result": result})
                success_count += 1
            except Exception as e:
                results.append({
                    "success": False, 
                    "error": str(e), 
                    "original": single_request.original_transcript
                })
                error_count += 1
        
        return BatchAdjustResult(
            batch_results=results,
            processed_count=len(results),
            success_count=success_count,
            error_count=error_count
        )
        
    finally:
        await pool.close()

@router.get("/adjustment-metrics")
async def get_adjustment_metrics():
    """Get performance metrics for monitoring"""
    return {
        "cache_status": adjuster.get_cache_status(),
        "performance_tips": [
            "Use batch processing for multiple transcriptions",
            "Cache is automatically refreshed every 5 minutes",
            "Consider keeping connections open for high-frequency usage"
        ]
    }

@router.post("/test-adjustment-cases")
async def test_adjustment_cases():
    """Test endpoint with predefined cases"""
    test_cases = [
        {
            "name": "Simple number word",
            "input": "J'ai vingt ans",
        },
        {
            "name": "Compound number",
            "input": "J'ai vingt-cinq ans",
        },
        {
            "name": "Un peu case (should revert)",
            "input": "J'aime un peu de café",
        },
        {
            "name": "Mixed numbers", 
            "input": "Un café coûte 2 euros",
        },
        {
            "name": "Entity replacement test",
            "input": "Je suis Canadien",
        },
        {
            "name": "Decimal numbers",
            "input": "Ça coûte 1,50 euros",
        }
    ]
    
    results = []
    
    for case in test_cases:
        try:
            request = TranscriptionAdjustRequest(original_transcript=case["input"])
            result = await adjust_transcription_endpoint(request)
            
            results.append({
                "test_name": case["name"],
                "input": case["input"],
                "result": {
                    "pre_adjusted": result.pre_adjusted_transcript,
                    "final": result.adjusted_transcript,
                    "completed": result.completed_transcript,
                    "vocab_count": len(result.list_of_vocabulary),
                    "entity_count": len(result.list_of_entities)
                },
                "processing_time": result.processing_time_ms
            })
        except Exception as e:
            results.append({
                "test_name": case["name"],
                "error": str(e)
            })
    
    return {"test_results": results}

# 3. UPDATE adjustement_adjuster.py (change import)
# FROM:
# from adjustement_models import AdjustmentResult

# TO:
from adjustement_types import AdjustmentResult

# 4. UPDATE adjustement_vocabulary_finder.py (change import)
# FROM:
# from adjustement_models import VocabularyMatch

# TO:
from adjustement_types import VocabularyMatch

# 5. UPDATE adjustement_entity_mapper.py (change import)
# FROM:
# from adjustement_models import EntityMatch

# TO:
from adjustement_types import EntityMatch

# 6. The import chain will now be:
# main.py → adjustement_main_router.py → adjustement_models.py → adjustement_adjuster.py
# adjustement_adjuster.py → adjustement_vocabulary_finder.py → adjustement_types.py ✅ (No circular import!)
