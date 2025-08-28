# gpt_fallback_router.py
"""
FastAPI router for GPT fallback intent detection endpoints
Follows the same architecture as matching_answer_router.py
"""
from fastapi import APIRouter, HTTPException
import asyncpg
import logging
import time
import os
from datetime import datetime

# Import types and service
from gpt_fallback_types import (
    GPTFallbackRequest,
    GPTFallbackResponse,
    BatchGPTFallbackRequest,
    BatchGPTFallbackResponse,
    ConditionalGPTFallbackRequest,
    GPTFallbackServiceStats,
    TriggerCondition
)
from gpt_fallback_service import gpt_fallback_service

logger = logging.getLogger(__name__)
router = APIRouter()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Missing required environment variable: DATABASE_URL")

# -------------------------
# Core GPT Fallback Endpoint
# -------------------------
@router.post("/analyze-intent", response_model=GPTFallbackResponse)
async def analyze_original_transcript_intent(request: GPTFallbackRequest):
    """
    Analyze original transcript for intent detection using GPT
    
    This endpoint is designed to be called independently when:
    - Adjustment process returns many vocabnotfound entries
    - Answer matching process finds no matches
    - Manual intent analysis is needed
    """
    try:
        logger.info(f"🧠 GPT intent analysis: interaction={request.interaction_id}, "
                   f"transcript='{request.original_transcript}', threshold={request.threshold}")
        
        # Use the service to perform GPT analysis
        result = await gpt_fallback_service.analyze_intent(
            interaction_id=request.interaction_id,
            original_transcript=request.original_transcript,
            threshold=request.threshold,
            custom_intent_ids=request.custom_intent_ids
        )
        
        # Convert service result to Pydantic response
        return GPTFallbackResponse(**result)
        
    except Exception as e:
        logger.error(f"GPT intent analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# -------------------------
# Conditional GPT Fallback (Smart Triggering)
# -------------------------
@router.post("/conditional-analyze-intent", response_model=GPTFallbackResponse)
async def conditional_gpt_fallback(request: ConditionalGPTFallbackRequest):
    """
    GPT fallback with intelligent triggering based on previous process results
    
    This endpoint decides whether to run GPT analysis based on:
    - Number of vocabnotfound in adjustment results
    - Answer matching scores
    - Manual override conditions
    """
    try:
        # Evaluate trigger conditions
        should_trigger = await _evaluate_trigger_conditions(request)
        
        if not should_trigger:
            logger.info(f"⏭️ GPT fallback not triggered for {request.interaction_id}: "
                       f"trigger={request.trigger_condition.trigger_reason}")
            
            # Return no-analysis result
            return GPTFallbackResponse(
                interaction_id=request.interaction_id,
                original_transcription=request.original_transcript,
                intent_matched=False,
                threshold=request.threshold,
                candidates_analyzed=0,
                gpt_reasoning="GPT analysis not triggered - conditions not met",
                processing_time_ms=0,
                timestamp=datetime.now().isoformat()
            )
        
        # Trigger conditions met - run normal GPT analysis
        logger.info(f"✅ GPT fallback triggered for {request.interaction_id}: "
                   f"reason={request.trigger_condition.trigger_reason}")
        
        # Convert to base request and analyze
        base_request = GPTFallbackRequest(
            interaction_id=request.interaction_id,
            original_transcript=request.original_transcript,
            threshold=request.threshold,
            user_id=request.user_id,
            custom_intent_ids=request.custom_intent_ids
        )
        
        return await analyze_original_transcript_intent(base_request)
        
    except Exception as e:
        logger.error(f"Conditional GPT fallback failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def _evaluate_trigger_conditions(request: ConditionalGPTFallbackRequest) -> bool:
    """Evaluate whether GPT fallback should be triggered"""
    trigger = request.trigger_condition
    
    if trigger.trigger_reason == "manual":
        return True
    
    elif trigger.trigger_reason == "vocabnotfound_threshold":
        if trigger.vocabnotfound_count is None:
            return False
        return trigger.vocabnotfound_count >= request.auto_trigger_vocabnotfound_threshold
    
    elif trigger.trigger_reason == "no_answer_match":
        if trigger.matching_score is None:
            return True  # No matching score means no match found
        return trigger.matching_score < request.auto_trigger_no_match_threshold
    
    else:
        logger.warning(f"Unknown trigger reason: {trigger.trigger_reason}")
        return False

# -------------------------
# Batch GPT Fallback Endpoint
# -------------------------
@router.post("/batch-analyze-intents", response_model=BatchGPTFallbackResponse)
async def batch_analyze_intents(request: BatchGPTFallbackRequest):
    """
    Batch GPT intent analysis for cost optimization
    Use sparingly due to GPT API costs
    """
    start_time = time.time()
    
    try:
        # Create connection pool for batch processing
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
        
        try:
            results = []
            intents_matched = 0
            errors_count = 0
            total_cost = 0.0
            
            for single_request in request.requests:
                try:
                    result = await gpt_fallback_service.analyze_intent(
                        interaction_id=single_request.interaction_id,
                        original_transcript=single_request.original_transcript,
                        threshold=single_request.threshold,
                        custom_intent_ids=single_request.custom_intent_ids,
                        pool=pool  # Reuse connection pool
                    )
                    
                    response = GPTFallbackResponse(**result)
                    results.append(response)
                    
                    if response.intent_matched:
                        intents_matched += 1
                    
                    if response.cost_estimate_usd:
                        total_cost += response.cost_estimate_usd
                        
                except Exception as e:
                    error_response = GPTFallbackResponse(
                        interaction_id=single_request.interaction_id,
                        original_transcription=single_request.original_transcript,
                        intent_matched=False,
                        threshold=single_request.threshold,
                        candidates_analyzed=0,
                        processing_time_ms=0,
                        error=str(e),
                        timestamp=datetime.now().isoformat()
                    )
                    results.append(error_response)
                    errors_count += 1
            
            total_time = time.time() - start_time
            
            return BatchGPTFallbackResponse(
                results=results,
                total_processed=len(results),
                intents_matched=intents_matched,
                errors_count=errors_count,
                total_processing_time_ms=round(total_time * 1000, 2),
                total_cost_estimate_usd=round(total_cost, 6)
            )
            
        finally:
            await pool.close()
            
    except Exception as e:
        logger.error(f"Batch GPT fallback failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# -------------------------
# Integration Helper Endpoints
# -------------------------
@router.post("/auto-trigger-from-adjustment")
async def auto_trigger_from_adjustment_results(
    interaction_id: str,
    original_transcript: str,
    adjustment_vocabulary_found: list,
    vocabnotfound_threshold: int = 3,
    threshold: int = 70
):
    """
    Helper endpoint for automatic triggering after adjustment process
    Call this from your adjustment workflow when many vocabnotfound detected
    """
    try:
        # Count vocabnotfound entries
        vocabnotfound_count = sum(
            1 for vocab in adjustment_vocabulary_found 
            if vocab.get('transcription_adjusted') == 'vocabnotfound'
        )
        
        logger.info(f"📊 Adjustment results analysis: {vocabnotfound_count} vocabnotfound found")
        
        # Create conditional request
        request = ConditionalGPTFallbackRequest(
            interaction_id=interaction_id,
            original_transcript=original_transcript,
            threshold=threshold,
            trigger_condition=TriggerCondition(
                trigger_reason="vocabnotfound_threshold",
                vocabnotfound_count=vocabnotfound_count
            ),
            auto_trigger_vocabnotfound_threshold=vocabnotfound_threshold
        )
        
        return await conditional_gpt_fallback(request)
        
    except Exception as e:
        logger.error(f"Auto-trigger from adjustment failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/auto-trigger-from-matching")
async def auto_trigger_from_matching_results(
    interaction_id: str,
    original_transcript: str,
    best_matching_score: float = None,
    no_match_threshold: int = 50,
    threshold: int = 70
):
    """
    Helper endpoint for automatic triggering after answer matching process
    Call this from your matching workflow when no good matches found
    """
    try:
        logger.info(f"📊 Matching results analysis: best_score={best_matching_score}")
        
        # Create conditional request
        request = ConditionalGPTFallbackRequest(
            interaction_id=interaction_id,
            original_transcript=original_transcript,
            threshold=threshold,
            trigger_condition=TriggerCondition(
                trigger_reason="no_answer_match",
                matching_score=best_matching_score
            ),
            auto_trigger_no_match_threshold=no_match_threshold
        )
        
        return await conditional_gpt_fallback(request)
        
    except Exception as e:
        logger.error(f"Auto-trigger from matching failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# -------------------------
# Service Management Endpoints
# -------------------------
@router.get("/gpt-fallback-stats", response_model=GPTFallbackServiceStats)
async def get_gpt_fallback_service_stats():
    """Get service statistics for monitoring and cost tracking"""
    try:
        stats = await gpt_fallback_service.get_service_stats()
        return GPTFallbackServiceStats(**stats)
    except Exception as e:
        logger.error(f"Failed to get GPT fallback service stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/test-gpt-workflow")
async def test_gpt_fallback_workflow(
    interaction_id: str,
    original_transcript: str,
    threshold: int = 70,
    custom_intent_ids: list = None
):
    """
    Test the complete GPT fallback workflow with debugging information
    Useful for development and cost estimation
    """
    try:
        # Test the GPT analysis workflow
        request = GPTFallbackRequest(
            interaction_id=interaction_id,
            original_transcript=original_transcript,
            threshold=threshold,
            custom_intent_ids=custom_intent_ids,
            user_id="test_user"
        )
        
        result = await analyze_original_transcript_intent(request)
        
        # Return enhanced debugging info
        return {
            "test_input": {
                "interaction_id": interaction_id,
                "original_transcript": original_transcript,
                "threshold": threshold,
                "custom_intent_ids": custom_intent_ids
            },
            "gpt_analysis_result": result.dict(),
            "performance_summary": {
                "processing_time_ms": result.processing_time_ms,
                "intent_matched": result.intent_matched,
                "confidence_score": result.similarity_score,
                "cost_estimate_usd": result.cost_estimate_usd,
                "candidates_analyzed": result.candidates_analyzed
            },
            "recommendations": {
                "cost_optimization": f"Estimated cost: ${result.cost_estimate_usd:.6f} per call",
                "accuracy_tips": [
                    "Use specific interaction intents for better context",
                    "Consider lowering threshold if no intents matched",
                    "Original transcripts work better than adjusted ones for intent detection"
                ],
                "integration_patterns": [
                    "Call after adjustment when 3+ vocabnotfound found",
                    "Call after matching when best score < 50%",
                    "Use conditional endpoints for automatic triggering"
                ]
            }
        }
        
    except Exception as e:
        logger.error(f"Test GPT workflow failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# -------------------------
# Intent Management Endpoints
# -------------------------
@router.get("/interaction-intents/{interaction_id}")
async def get_interaction_available_intents(interaction_id: str):
    """
    Get all available intents for a specific interaction
    Useful for debugging and manual intent selection
    """
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        
        try:
            # Get intents from interaction
            async with pool.acquire() as conn:
                interaction_row = await conn.fetchrow("""
                    SELECT intents
                    FROM brain_interaction
                    WHERE id = $1 AND live = TRUE
                """, interaction_id)
                
                if not interaction_row or not interaction_row['intents']:
                    return {
                        "interaction_id": interaction_id,
                        "intents_available": 0,
                        "intents": [],
                        "warning": "No intents configured for this interaction"
                    }
                
                intent_ids = interaction_row['intents']
                
                # Get full intent details
                intent_rows = await conn.fetch("""
                    SELECT id, name, description, live
                    FROM brain_intent
                    WHERE id = ANY($1)
                    ORDER BY name ASC
                """, intent_ids)
                
                intents = []
                live_count = 0
                for row in intent_rows:
                    intent_data = {
                        "id": row['id'],
                        "name": row['name'],
                        "description": row['description'],
                        "live": row['live']
                    }
                    intents.append(intent_data)
                    if row['live']:
                        live_count += 1
                
                return {
                    "interaction_id": interaction_id,
                    "intents_configured": len(intent_ids),
                    "intents_found": len(intents),
                    "intents_live": live_count,
                    "intents": intents,
                    "ready_for_gpt": live_count > 0
                }
        
        finally:
            await pool.close()
            
    except Exception as e:
        logger.error(f"Failed to get interaction intents: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# -------------------------
# Health Check
# -------------------------
@router.get("/gpt-fallback-health")
async def gpt_fallback_service_health():
    """Health check for the GPT fallback service"""
    try:
        # Test database connection
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        try:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            
            # Test OpenAI API key availability
            openai_configured = bool(os.getenv("OPENAI_API_KEY"))
            
            return {
                "status": "healthy",
                "service": "gpt_fallback_service",
                "database": "connected",
                "openai_api": "configured" if openai_configured else "not_configured",
                "gpt_model": gpt_fallback_service.gpt_model,
                "default_threshold": gpt_fallback_service.default_threshold,
                "endpoints": {
                    "single_analysis": "/analyze-intent",
                    "conditional_analysis": "/conditional-analyze-intent",
                    "batch_analysis": "/batch-analyze-intents",
                    "auto_trigger_adjustment": "/auto-trigger-from-adjustment",
                    "auto_trigger_matching": "/auto-trigger-from-matching",
                    "test": "/test-gpt-workflow",
                    "stats": "/gpt-fallback-stats",
                    "interaction_intents": "/interaction-intents/{interaction_id}"
                },
                "cost_warning": "GPT calls incur API costs - use conditionally"
            }
        finally:
            await pool.close()
            
    except Exception as e:
        logger.error(f"GPT fallback health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }
