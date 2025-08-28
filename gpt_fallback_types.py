# gpt_fallback_types.py
"""
Pydantic models for the GPT fallback intent detection service
Following same architecture pattern as matching_answer_types.py and adjustement_types.py
"""
from pydantic import BaseModel, validator
from typing import List, Optional, Dict, Any
from datetime import datetime

class GPTFallbackRequest(BaseModel):
    """Request to analyze original transcript for intent detection"""
    interaction_id: str
    original_transcript: str
    threshold: int = 70  # Lower threshold for intent detection vs exact matching
    user_id: Optional[str] = None
    # Optional: Allow manual intent list override
    custom_intent_ids: Optional[List[str]] = None
    
    @validator('interaction_id')
    def validate_interaction_id(cls, v):
        if not v or not v.strip():
            raise ValueError("Interaction ID cannot be empty")
        return v.strip()
    
    @validator('original_transcript')
    def validate_original_transcript(cls, v):
        if not v or not v.strip():
            raise ValueError("Original transcript cannot be empty")
        if len(v) > 1000:
            raise ValueError("Original transcript too long (max 1000 characters)")
        return v.strip()
    
    @validator('threshold')
    def validate_threshold(cls, v):
        if v < 0 or v > 100:
            raise ValueError("Threshold must be between 0 and 100")
        return v

class IntentCandidate(BaseModel):
    """Represents an intent candidate for GPT analysis"""
    id: str
    name: str
    description: Optional[str] = None

class GPTFallbackResponse(BaseModel):
    """Response from GPT fallback intent detection"""
    interaction_id: str
    original_transcription: str
    intent_matched: bool
    intent_id: Optional[str] = None
    intent_name: Optional[str] = None
    similarity_score: Optional[int] = None
    threshold: int
    candidates_analyzed: int
    gpt_reasoning: Optional[str] = None
    gpt_alternative_interpretation: Optional[str] = None
    processing_time_ms: float
    cost_estimate_usd: Optional[float] = None
    error: Optional[str] = None
    timestamp: str

class BatchGPTFallbackRequest(BaseModel):
    """Batch processing for cost optimization"""
    requests: List[GPTFallbackRequest]
    
    @validator('requests')
    def validate_batch_size(cls, v):
        if len(v) > 10:  # Conservative for GPT calls
            raise ValueError("Batch size too large (max 10)")
        if len(v) == 0:
            raise ValueError("Batch cannot be empty")
        return v

class BatchGPTFallbackResponse(BaseModel):
    """Response for batch GPT fallback processing"""
    results: List[GPTFallbackResponse]
    total_processed: int
    intents_matched: int
    errors_count: int
    total_processing_time_ms: float
    total_cost_estimate_usd: float

class GPTFallbackServiceStats(BaseModel):
    """Service statistics for monitoring"""
    service_name: str
    gpt_model: str
    default_threshold: int
    cache_status: Dict[str, Any]
    cost_optimization_tips: List[str]
    uptime_info: Optional[Dict[str, Any]] = None

class TriggerCondition(BaseModel):
    """Represents when GPT fallback should be triggered"""
    trigger_reason: str  # "vocabnotfound_threshold" | "no_answer_match" | "manual"
    vocabnotfound_count: Optional[int] = None
    matching_score: Optional[float] = None
    additional_context: Optional[str] = None

class ConditionalGPTFallbackRequest(GPTFallbackRequest):
    """Extended request with trigger conditions for automatic activation"""
    trigger_condition: TriggerCondition
    auto_trigger_vocabnotfound_threshold: int = 3  # Trigger if 3+ vocabnotfound
    auto_trigger_no_match_threshold: int = 50      # Trigger if best match < 50%
