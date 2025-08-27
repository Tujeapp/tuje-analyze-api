# matching_answer_types.py
"""
Pydantic models for the answer matching service
Follows same pattern as adjustement_types.py
"""
from pydantic import BaseModel, validator
from typing import List, Optional, Dict, Any
from datetime import datetime

class MatchAnswerRequest(BaseModel):
    """Request to match a completed transcript against interaction answers"""
    interaction_id: str
    completed_transcript: str
    threshold: int = 85
    user_id: Optional[str] = None
    
    @validator('interaction_id')
    def validate_interaction_id(cls, v):
        if not v or not v.strip():
            raise ValueError("Interaction ID cannot be empty")
        return v.strip()
    
    @validator('completed_transcript')
    def validate_completed_transcript(cls, v):
        if not v or not v.strip():
            raise ValueError("Completed transcript cannot be empty")
        if len(v) > 500:  # Reasonable limit for processed transcript
            raise ValueError("Completed transcript too long (max 500 characters)")
        return v.strip()
    
    @validator('threshold')
    def validate_threshold(cls, v):
        if v < 0 or v > 100:
            raise ValueError("Threshold must be between 0 and 100")
        return v

class AnswerDetails(BaseModel):
    """Details of the matched answer"""
    transcription_fr: str
    transcription_en: str
    transcription_adjusted: str

class MatchAnswerResponse(BaseModel):
    """Response from answer matching service"""
    match_found: bool
    interaction_id: str
    completed_transcription: str  # Keep your naming convention
    interaction_answer_id: Optional[str] = None
    answer_id: Optional[str] = None
    threshold: int
    similarity_score: Optional[float] = None
    expected_transcript: Optional[str] = None
    answer_details: Optional[AnswerDetails] = None
    reason: Optional[str] = None
    error: Optional[str] = None
    processing_time_ms: float
    timestamp: str

class BatchMatchRequest(BaseModel):
    """Batch matching for cost optimization"""
    matches: List[MatchAnswerRequest]
    
    @validator('matches')
    def validate_batch_size(cls, v):
        if len(v) > 20:  # Conservative batch size
            raise ValueError("Batch size too large (max 20)")
        if len(v) == 0:
            raise ValueError("Batch cannot be empty")
        return v

class BatchMatchResponse(BaseModel):
    """Response for batch matching"""
    results: List[MatchAnswerResponse]
    total_processed: int
    matches_found: int
    errors_count: int
    total_processing_time_ms: float

class CombinedAdjustmentAndMatchRequest(BaseModel):
    """
    Combined request for adjustment + matching in one call
    Optimized workflow for the mobile app
    """
    interaction_id: str
    original_transcript: str  # Raw user transcript
    threshold: int = 85
    user_id: Optional[str] = None
    # Adjustment settings
    auto_adjust: bool = True
    expected_entities_ids: Optional[List[str]] = None
    
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

class CombinedAdjustmentAndMatchResponse(BaseModel):
    """
    Combined response with both adjustment and matching results
    Optimized for mobile app single API call
    """
    # Overall results
    adjustment_successful: bool
    match_found: bool
    
    # Adjustment results
    original_transcript: str
    pre_adjusted_transcript: Optional[str] = None
    adjusted_transcript: Optional[str] = None
    completed_transcript: Optional[str] = None
    vocabulary_found: List[Dict] = []
    entities_found: List[Dict] = []
    
    # Matching results  
    interaction_id: str
    interaction_answer_id: Optional[str] = None
    answer_id: Optional[str] = None
    threshold: int
    similarity_score: Optional[float] = None
    expected_transcript: Optional[str] = None
    answer_details: Optional[AnswerDetails] = None
    
    # Performance and debugging
    adjustment_time_ms: Optional[float] = None
    matching_time_ms: Optional[float] = None
    total_time_ms: float
    reason: Optional[str] = None
    error: Optional[str] = None
    timestamp: str

class MatchingServiceStats(BaseModel):
    """Service statistics for monitoring"""
    service_name: str
    cache_status: Dict[str, Any]
    default_threshold: int
    fuzzy_matching_algorithm: str
    uptime_info: Optional[Dict[str, Any]] = None
