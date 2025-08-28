# bubble_integration_router.py
"""
Bubble.io-optimized endpoints for the TuJe French learning API
Designed for easy integration with Bubble workflows
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, validator
from typing import Optional, List, Dict, Any
import logging
import time
from datetime import datetime

# Import your existing services
from adjustement_models import adjust_transcription_endpoint
from matching_answer_router import combined_adjust_and_match
from gpt_fallback_router import analyze_original_transcript_intent

# Import types
from adjustement_types import TranscriptionAdjustRequest
from matching_answer_types import CombinedAdjustmentAndMatchRequest
from gpt_fallback_types import GPTFallbackRequest

logger = logging.getLogger(__name__)
router = APIRouter()

# -------------------------
# Bubble-Optimized Models
# -------------------------
class BubbleProcessTranscriptRequest(BaseModel):
    """Simplified request model for Bubble workflows"""
    interaction_id: str
    user_transcript: str  # Raw user speech transcript
    user_id: Optional[str] = None
    threshold: int = 85  # For answer matching
    gpt_threshold: int = 70  # For intent detection
    
    # Processing controls
    enable_adjustment: bool = True
    enable_matching: bool = True  
    enable_gpt_fallback: bool = True
    
    # Auto-trigger settings for GPT
    auto_gpt_vocabnotfound_threshold: int = 3
    auto_gpt_no_match_threshold: int = 50
    
    @validator('user_transcript')
    def validate_transcript(cls, v):
        if not v or not v.strip():
            raise ValueError("User transcript cannot be empty")
        if len(v) > 1000:
            raise ValueError("Transcript too long (max 1000 characters)")
        return v.strip()

class BubbleProcessResponse(BaseModel):
    """Unified response for Bubble workflows"""
    # Overall status
    success: bool
    processing_time_ms: float
    timestamp: str
    
    # Input echo
    interaction_id: str
    original_transcript: str
    
    # Adjustment results
    adjustment_applied: bool = False
    adjusted_transcript: Optional[str] = None
    completed_transcript: Optional[str] = None
    vocabulary_found: List[Dict] = []
    entities_found: List[Dict] = []
    vocabnotfound_count: int = 0
    
    # Matching results
    answer_match_found: bool = False
    matched_answer_id: Optional[str] = None
    similarity_score: Optional[float] = None
    expected_answer: Optional[str] = None
    
    # GPT results
    gpt_triggered: bool = False
    gpt_intent_found: bool = False
    detected_intent_id: Optional[str] = None
    detected_intent_name: Optional[str] = None
    gpt_confidence: Optional[int] = None
    gpt_reasoning: Optional[str] = None
    
    # Error handling
    errors: List[str] = []
    warnings: List[str] = []
    
    # Next steps for Bubble
    recommended_action: str = "continue"  # "continue" | "retry" | "escalate"
    call_gpt_manually: bool = False

# -------------------------
# Main Bubble Endpoint
# -------------------------
@router.post("/bubble-process-transcript", response_model=BubbleProcessResponse)
async def bubble_process_complete_transcript(request: BubbleProcessTranscriptRequest):
    """
    🎯 MAIN ENDPOINT FOR BUBBLE INTEGRATION
    
    Complete transcript processing pipeline:
    1. Transcription Adjustment (if enabled)
    2. Answer Matching (if enabled)
    3. GPT Intent Detection (if conditions met and enabled)
    
    Returns unified response perfect for Bubble workflows
    """
    start_time = time.time()
    
    response = BubbleProcessResponse(
        success=False,
        processing_time_ms=0,
        timestamp=datetime.now().isoformat(),
        interaction_id=request.interaction_id,
        original_transcript=request.user_transcript
    )
    
    try:
        logger.info(f"🎯 Bubble processing: {request.interaction_id} - '{request.user_transcript}'")
        
        # STEP 1: Transcription Adjustment
        completed_transcript = request.user_transcript
        if request.enable_adjustment:
            try:
                logger.info("🔧 Running transcription adjustment...")
                
                adj_request = TranscriptionAdjustRequest(
                    original_transcript=request.user_transcript,
                    user_id=request.user_id,
                    interaction_id=request.interaction_id
                )
                
                adj_result = await adjust_transcription_endpoint(adj_request)
                
                response.adjustment_applied = True
                response.adjusted_transcript = adj_result.adjusted_transcript
                response.completed_transcript = adj_result.completed_transcript
                response.vocabulary_found = [v.dict() for v in adj_result.list_of_vocabulary]
                response.entities_found = [e.dict() for e in adj_result.list_of_entities]
                
                # Count vocabnotfound for GPT triggering
                response.vocabnotfound_count = sum(
                    1 for vocab in response.vocabulary_found 
                    if vocab.get('transcription_adjusted') == 'vocabnotfound'
                )
                
                completed_transcript = adj_result.completed_transcript
                logger.info(f"✅ Adjustment complete: '{request.user_transcript}' → '{completed_transcript}'")
                
            except Exception as e:
                logger.warning(f"⚠️ Adjustment failed: {e}")
                response.errors.append(f"Adjustment failed: {str(e)}")
                response.warnings.append("Continuing with original transcript")
        
        # STEP 2: Answer Matching
        best_match_score = 0
        if request.enable_matching:
            try:
                logger.info(f"🔍 Running answer matching for: '{completed_transcript}'")
                
                # Use the combined endpoint internally but extract just matching results
                combined_request = CombinedAdjustmentAndMatchRequest(
                    interaction_id=request.interaction_id,
                    original_transcript=completed_transcript,  # Use processed transcript
                    threshold=request.threshold,
                    user_id=request.user_id,
                    auto_adjust=False  # We already adjusted
                )
                
                combined_result = await combined_adjust_and_match(combined_request)
                
                response.answer_match_found = combined_result.match_found
                if combined_result.match_found:
                    response.matched_answer_id = combined_result.answer_id
                    response.similarity_score = combined_result.similarity_score
                    response.expected_answer = combined_result.expected_transcript
                    best_match_score = combined_result.similarity_score or 0
                
                logger.info(f"🎯 Matching result: found={response.answer_match_found}, score={best_match_score}")
                
            except Exception as e:
                logger.warning(f"⚠️ Answer matching failed: {e}")
                response.errors.append(f"Answer matching failed: {str(e)}")
        
        # STEP 3: GPT Intent Detection (Auto-trigger logic)
        should_trigger_gpt = False
        gpt_trigger_reason = None
        
        if request.enable_gpt_fallback:
            # Auto-trigger condition 1: Too many vocabnotfound
            if response.vocabnotfound_count >= request.auto_gpt_vocabnotfound_threshold:
                should_trigger_gpt = True
                gpt_trigger_reason = f"vocabnotfound_count ({response.vocabnotfound_count}) >= threshold ({request.auto_gpt_vocabnotfound_threshold})"
            
            # Auto-trigger condition 2: No good answer match
            elif not response.answer_match_found or best_match_score < request.auto_gpt_no_match_threshold:
                should_trigger_gpt = True
                gpt_trigger_reason = f"no_good_match (best_score={best_match_score} < threshold={request.auto_gpt_no_match_threshold})"
            
            if should_trigger_gpt:
                try:
                    logger.info(f"🧠 Triggering GPT fallback: {gpt_trigger_reason}")
                    
                    gpt_request = GPTFallbackRequest(
                        interaction_id=request.interaction_id,
                        original_transcript=request.user_transcript,  # Use original for intent detection
                        threshold=request.gpt_threshold,
                        user_id=request.user_id
                    )
                    
                    gpt_result = await analyze_original_transcript_intent(gpt_request)
                    
                    response.gpt_triggered = True
                    response.gpt_intent_found = gpt_result.intent_matched
                    response.detected_intent_id = gpt_result.intent_id
                    response.detected_intent_name = gpt_result.intent_name
                    response.gpt_confidence = gpt_result.similarity_score
                    response.gpt_reasoning = gpt_result.gpt_reasoning
                    
                    logger.info(f"🧠 GPT result: intent_found={response.gpt_intent_found}, intent={response.detected_intent_name}")
                    
                except Exception as e:
                    logger.warning(f"⚠️ GPT fallback failed: {e}")
                    response.errors.append(f"GPT fallback failed: {str(e)}")
                    response.call_gpt_manually = True
            else:
                logger.info("🧠 GPT fallback not triggered - conditions not met")
        
        # STEP 4: Determine recommended action for Bubble
        if response.answer_match_found:
            response.recommended_action = "continue"
            response.success = True
        elif response.gpt_intent_found:
            response.recommended_action = "continue"  # Bubble can handle intent
            response.success = True
        elif response.errors:
            response.recommended_action = "retry"
            response.success = False
        else:
            response.recommended_action = "escalate"  # Need human intervention
            response.success = len(response.errors) == 0  # Success if no hard errors
            response.call_gpt_manually = not response.gpt_triggered  # Suggest manual GPT
        
        response.processing_time_ms = round((time.time() - start_time) * 1000, 2)
        
        logger.info(f"🎯 Bubble processing complete: success={response.success}, "
                   f"action={response.recommended_action}, time={response.processing_time_ms}ms")
        
        return response
        
    except Exception as e:
        response.processing_time_ms = round((time.time() - start_time) * 1000, 2)
        response.errors.append(f"Critical error: {str(e)}")
        response.recommended_action = "retry"
        response.success = False
        
        logger.error(f"❌ Bubble processing failed: {e}")
        return response

# -------------------------
# Individual Service Endpoints (for debugging)
# -------------------------
@router.post("/bubble-adjust-only")
async def bubble_transcription_adjustment_only(
    interaction_id: str,
    user_transcript: str,
    user_id: Optional[str] = None
):
    """Bubble endpoint for adjustment only"""
    try:
        request = TranscriptionAdjustRequest(
            original_transcript=user_transcript,
            user_id=user_id,
            interaction_id=interaction_id
        )
        
        result = await adjust_transcription_endpoint(request)
        
        return {
            "success": True,
            "original_transcript": user_transcript,
            "adjusted_transcript": result.adjusted_transcript,
            "completed_transcript": result.completed_transcript,
            "vocabulary_found": [v.dict() for v in result.list_of_vocabulary],
            "entities_found": [e.dict() for e in result.list_of_entities],
            "processing_time_ms": result.processing_time_ms,
            "vocabnotfound_count": sum(
                1 for v in result.list_of_vocabulary 
                if v.transcription_adjusted == 'vocabnotfound'
            )
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/bubble-match-only")
async def bubble_answer_matching_only(
    interaction_id: str,
    completed_transcript: str,
    threshold: int = 85
):
    """Bubble endpoint for answer matching only"""
    try:
        from matching_answer_types import MatchAnswerRequest
        from matching_answer_router import match_completed_transcript
        
        request = MatchAnswerRequest(
            interaction_id=interaction_id,
            completed_transcript=completed_transcript,
            threshold=threshold
        )
        
        result = await match_completed_transcript(request)
        
        return {
            "success": result.match_found,
            "match_found": result.match_found,
            "matched_answer_id": result.answer_id,
            "similarity_score": result.similarity_score,
            "expected_answer": result.expected_transcript,
            "processing_time_ms": result.processing_time_ms,
            "reason": result.reason
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/bubble-gpt-only")
async def bubble_gpt_intent_only(
    interaction_id: str,
    original_transcript: str,
    threshold: int = 70
):
    """Bubble endpoint for GPT intent detection only"""
    try:
        request = GPTFallbackRequest(
            interaction_id=interaction_id,
            original_transcript=original_transcript,
            threshold=threshold
        )
        
        result = await analyze_original_transcript_intent(request)
        
        return {
            "success": result.intent_matched,
            "intent_found": result.intent_matched,
            "intent_id": result.intent_id,
            "intent_name": result.intent_name,
            "confidence": result.similarity_score,
            "reasoning": result.gpt_reasoning,
            "processing_time_ms": result.processing_time_ms,
            "cost_estimate": result.cost_estimate_usd
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -------------------------
# Bubble Configuration Endpoint
# -------------------------
@router.get("/bubble-config")
async def get_bubble_integration_config():
    """Configuration info for Bubble setup"""
    return {
        "main_endpoint": {
            "url": "/api/bubble/bubble-process-transcript",
            "method": "POST",
            "description": "Complete transcript processing pipeline",
            "recommended": True
        },
        "individual_endpoints": {
            "adjustment_only": "/api/bubble/bubble-adjust-only",
            "matching_only": "/api/bubble/bubble-match-only", 
            "gpt_only": "/api/bubble/bubble-gpt-only"
        },
        "request_format": {
            "required_fields": ["interaction_id", "user_transcript"],
            "optional_fields": ["user_id", "threshold", "gpt_threshold"],
            "control_flags": ["enable_adjustment", "enable_matching", "enable_gpt_fallback"]
        },
        "response_format": {
            "status_fields": ["success", "recommended_action"],
            "adjustment_fields": ["adjustment_applied", "completed_transcript", "vocabnotfound_count"],
            "matching_fields": ["answer_match_found", "matched_answer_id", "similarity_score"],
            "gpt_fields": ["gpt_triggered", "detected_intent_id", "gpt_confidence"]
        },
        "bubble_workflow_tips": [
            "Use recommended_action to determine next steps",
            "Check errors array for any processing issues",
            "call_gpt_manually flag indicates manual GPT trigger needed",
            "vocabnotfound_count helps evaluate transcript quality"
        ]
    }

# -------------------------
# Health Check
# -------------------------
@router.get("/bubble-health")
async def bubble_integration_health():
    """Health check for Bubble integration"""
    return {
        "status": "healthy",
        "service": "bubble_integration",
        "endpoints_available": 5,
        "main_endpoint": "/api/bubble/bubble-process-transcript",
        "processing_pipeline": [
            "transcription_adjustment",
            "answer_matching", 
            "gpt_intent_detection"
        ],
        "auto_trigger_logic": "✅ Enabled",
        "error_handling": "✅ Comprehensive"
    }
