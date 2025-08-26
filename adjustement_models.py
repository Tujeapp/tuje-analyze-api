# adjustement_models.py

from fastapi import APIRouter, HTTPException
import asyncpg
import logging
import os

# FIXED: Import Pydantic models from separate types file (no circular import)
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

@router.get("/entity-status")
async def get_entity_status():
    """Get current entity availability status for monitoring"""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        try:
            # Load fresh cache to get current entity status
            await adjuster.cache_manager.ensure_cache_loaded(pool)
            cache_status = adjuster.get_cache_status()
            
            return {
                "live_entities": cache_status.get("live_entity_count", 0),
                "inactive_entities": cache_status.get("inactive_entity_count", 0),
                "total_entities": cache_status.get("live_entity_count", 0) + cache_status.get("inactive_entity_count", 0),
                "cache_age_seconds": cache_status.get("age_seconds"),
                "last_updated": datetime.now().isoformat(),
                "status": "healthy" if cache_status.get("loaded") else "cache_not_loaded"
            }
        finally:
            await pool.close()
    except Exception as e:
        logger.error(f"Entity status check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
