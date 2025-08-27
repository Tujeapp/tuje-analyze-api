# matching_answer_router.py
"""
FastAPI router for answer matching endpoints
Follows the same architecture as adjustement_models.py
"""
from fastapi import APIRouter, HTTPException
import asyncpg
import logging
import time
import os
from datetime import datetime

# Import types and service
from matching_answer_types import (
    MatchAnswerRequest,
    MatchAnswerResponse,
    BatchMatchRequest,
    BatchMatchResponse,
    CombinedAdjustmentAndMatchRequest,
    CombinedAdjustmentAndMatchResponse,
    MatchingServiceStats
)
from matching_answer_service import answer_matching_service

# Import adjustment service for combined endpoint
from adjustement_types import TranscriptionAdjustRequest
from adjustement_models import adjust_transcription_endpoint

logger = logging.getLogger(__name__)
router = APIRouter()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Missing required environment variable: DATABASE_URL")

# -------------------------
# Core Answer Matching Endpoint
# -------------------------
@router.post("/match-answer", response_model=MatchAnswerResponse)
async def match_completed_transcript(request: MatchAnswerRequest):
    """
    Match a completed transcript against interaction answers
    
    This endpoint expects the transcript to already be processed by the adjustment service.
    For raw transcripts, use /combined-adjust-and-match instead.
    """
    try:
        logger.info(f"🔍 Matching request: interaction={request.interaction_id}, "
                   f"transcript='{request.completed_transcript}', threshold={request.threshold}")
        
        # Use the service to perform matching
        result = await answer_matching_service.match_completed_transcript(
            interaction_id=request.interaction_id,
            completed_transcript=request.completed_transcript,
            threshold=request.threshold
        )
        
        # Convert service result to Pydantic response
        return MatchAnswerResponse(**result)
        
    except Exception as e:
        logger.error(f"Answer matching failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# -------------------------
# Batch Matching Endpoint
# -------------------------
@router.post("/batch-match-answers", response_model=BatchMatchResponse)
async def batch_match_answers(request: BatchMatchRequest):
    """
    Batch matching for cost optimization
    Useful when processing multiple transcripts at once
    """
    start_time = time.time()
    
    try:
        # Create connection pool for batch processing
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=5)
        
        try:
            results = []
            matches_found = 0
            errors_count = 0
            
            for single_request in request.matches:
                try:
                    result = await answer_matching_service.match_completed_transcript(
                        interaction_id=single_request.interaction_id,
                        completed_transcript=single_request.completed_transcript,
                        threshold=single_request.threshold,
                        pool=pool  # Reuse connection pool
                    )
                    
                    response = MatchAnswerResponse(**result)
                    results.append(response)
                    
                    if response.match_found:
                        matches_found += 1
                        
                except Exception as e:
                    error_response = MatchAnswerResponse(
                        match_found=False,
                        interaction_id=single_request.interaction_id,
                        completed_transcription=single_request.completed_transcript,
                        interaction_answer_id=None,
                        answer_id=None,
                        threshold=single_request.threshold,
                        error=str(e),
                        processing_time_ms=0,
                        timestamp=datetime.now().isoformat()
                    )
                    results.append(error_response)
                    errors_count += 1
            
            total_time = time.time() - start_time
            
            return BatchMatchResponse(
                results=results,
                total_processed=len(results),
                matches_found=matches_found,
                errors_count=errors_count,
                total_processing_time_ms=round(total_time * 1000, 2)
            )
            
        finally:
            await pool.close()
            
    except Exception as e:
        logger.error(f"Batch matching failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# -------------------------
# Combined Adjustment + Matching Endpoint (RECOMMENDED)
# -------------------------
@router.post("/combined-adjust-and-match", response_model=CombinedAdjustmentAndMatchResponse)
async def combined_adjust_and_match(request: CombinedAdjustmentAndMatchRequest):
    """
    RECOMMENDED ENDPOINT: Complete workflow from raw transcript to answer match
    
    This is the most efficient endpoint for the mobile app:
    1. Takes raw user transcript
    2. Applies transcription adjustment 
    3. Matches result against interaction answers
    4. Returns comprehensive results in single API call
    
    Benefits:
    - Single API call reduces latency
    - Shared database connection pool
    - Complete audit trail
    - Optimized for mobile app workflow
    """
    start_time = time.time()
    
    try:
        adjustment_successful = False
        match_found = False
        adjustment_time = 0
        matching_time = 0
        
        # STEP 1: Transcription Adjustment
        completed_transcript = request.original_transcript  # Fallback
        adjustment_result = None
        
        if request.auto_adjust:
            logger.info(f"🔧 Starting adjustment for: '{request.original_transcript}'")
            adjustment_start = time.time()
            
            try:
                # Create adjustment request
                adjustment_request = TranscriptionAdjustRequest(
                    original_transcript=request.original_transcript,
                    user_id=request.user_id,
                    interaction_id=request.interaction_id,
                    expected_entities_ids=request.expected_entities_ids
                )
                
                # Call adjustment service
                adjustment_result = await adjust_transcription_endpoint(adjustment_request)
                completed_transcript = adjustment_result.completed_transcript
                adjustment_successful = True
                adjustment_time = time.time() - adjustment_start
                
                logger.info(f"✅ Adjustment successful: '{request.original_transcript}' → '{completed_transcript}'")
                
            except Exception as e:
                adjustment_time = time.time() - adjustment_start
                logger.warning(f"⚠️ Adjustment failed: {e}")
                logger.info("Continuing with original transcript")
                # Continue with original transcript
        
        # STEP 2: Answer Matching
        logger.info(f"🔍 Starting matching for: '{completed_transcript}'")
        matching_start = time.time()
        
        try:
            match_result = await answer_matching_service.match_completed_transcript(
                interaction_id=request.interaction_id,
                completed_transcript=completed_transcript,
                threshold=request.threshold
            )
            
            matching_time = time.time() - matching_start
            match_found = match_result.get('match_found', False)
            
            logger.info(f"🎯 Matching result: {match_found}, "
                       f"score={match_result.get('similarity_score', 0)}")
            
        except Exception as e:
            matching_time = time.time() - matching_start
            logger.error(f"Matching failed: {e}")
            match_result = {
                'match_found': False,
                'error': str(e)
            }
        
        # STEP 3: Build Combined Response
        total_time = time.time() - start_time
        
        response_data = {
            # Overall status
            'adjustment_successful': adjustment_successful,
            'match_found': match_found,
            
            # Adjustment details
            'original_transcript': request.original_transcript,
            'completed_transcript': completed_transcript,
            
            # Matching details
            'interaction_id': request.interaction_id,
            'threshold': request.threshold,
            
            # Performance
            'total_time_ms': round(total_time * 1000, 2),
            'timestamp': datetime.now().isoformat()
        }
        
        # Add adjustment details if successful
        if adjustment_result:
            response_data.update({
                'pre_adjusted_transcript': adjustment_result.pre_adjusted_transcript,
                'adjusted_transcript': adjustment_result.adjusted_transcript,
                'vocabulary_found': [v.dict() for v in adjustment_result.list_of_vocabulary],
                'entities_found': [e.dict() for e in adjustment_result.list_of_entities],
                'adjustment_time_ms': round(adjustment_time * 1000, 2)
            })
        
        # Add matching details
        if match_result.get('match_found'):
            response_data.update({
                'interaction_answer_id': match_result.get('interaction_answer_id'),
                'answer_id': match_result.get('answer_id'),
                'similarity_score': match_result.get('similarity_score'),
                'expected_transcript': match_result.get('expected_transcript'),
                'answer_details': match_result.get('answer_details')
            })
        
        # Add error/reason info
        if match_result.get('error'):
            response_data['error'] = match_result['error']
        elif match_result.get('reason'):
            response_data['reason'] = match_result['reason']
        
        response_data['matching_time_ms'] = round(matching_time * 1000, 2)
        
        return CombinedAdjustmentAndMatchResponse(**response_data)
        
    except Exception as e:
        total_time = time.time() - start_time
        logger.error(f"Combined workflow failed: {e}")
        
        # Return error response with available information
        return CombinedAdjustmentAndMatchResponse(
            adjustment_successful=False,
            match_found=False,
            original_transcript=request.original_transcript,
            completed_transcript=request.original_transcript,
            interaction_id=request.interaction_id,
            threshold=request.threshold,
            total_time_ms=round(total_time * 1000, 2),
            error=str(e),
            timestamp=datetime.now().isoformat()
        )

# -------------------------
# Service Management Endpoints
# -------------------------
@router.get("/matching-service-stats", response_model=MatchingServiceStats)
async def get_matching_service_stats():
    """Get service statistics for monitoring and debugging"""
    try:
        stats = await answer_matching_service.get_service_stats()
        return MatchingServiceStats(**stats)
    except Exception as e:
        logger.error(f"Failed to get service stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/test-matching-workflow")
async def test_matching_workflow(
    interaction_id: str,
    original_transcript: str,
    threshold: int = 85,
    auto_adjust: bool = True
):
    """
    Test the complete workflow with debugging information
    Useful for development and troubleshooting
    """
    try:
        # Test the combined workflow
        request = CombinedAdjustmentAndMatchRequest(
            interaction_id=interaction_id,
            original_transcript=original_transcript,
            threshold=threshold,
            auto_adjust=auto_adjust,
            user_id="test_user"
        )
        
        result = await combined_adjust_and_match(request)
        
        # Return enhanced debugging info
        return {
            "test_input": {
                "interaction_id": interaction_id,
                "original_transcript": original_transcript,
                "threshold": threshold,
                "auto_adjust": auto_adjust
            },
            "workflow_result": result.dict(),
            "performance_summary": {
                "adjustment_time_ms": result.adjustment_time_ms,
                "matching_time_ms": result.matching_time_ms,
                "total_time_ms": result.total_time_ms,
                "adjustment_worked": result.adjustment_successful,
                "match_found": result.match_found,
                "similarity_score": result.similarity_score
            },
            "recommendations": {
                "use_combined_endpoint": "Yes - most efficient for mobile apps",
                "threshold_optimization": "Consider lowering threshold if no matches found",
                "caching": "Service automatically caches interaction answers"
            }
        }
        
    except Exception as e:
        logger.error(f"Test workflow failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# -------------------------
# Health Check
# -------------------------
@router.get("/matching-health")
async def matching_service_health():
    """Health check for the matching service"""
    try:
        # Test database connection
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        try:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            
            return {
                "status": "healthy",
                "service": "answer_matching_service",
                "database": "connected",
                "endpoints": {
                    "single_match": "/match-answer",
                    "batch_match": "/batch-match-answers", 
                    "combined_workflow": "/combined-adjust-and-match (RECOMMENDED)",
                    "test": "/test-matching-workflow",
                    "stats": "/matching-service-stats"
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
