# bubble_models.py

from pydantic import BaseModel, validator
from typing import Optional, List, Dict, Any
from datetime import datetime

class BubbleSessionRequest(BaseModel):
    """Start a new learning session"""
    user_auth_id: str
    auth_provider: str = "bubble"
    subtopic_id: str
    session_type: str = "practice"
    difficulty_level: str = "adaptive"
    app_version: Optional[str] = "1.0.0"
    device_type: Optional[str] = "mobile"

class BubbleAudioProcessRequest(BaseModel):
    """Enhanced audio processing with AI training consent"""
    session_id: str
    interaction_id: str
    original_transcript: str
    audio_duration_ms: Optional[int] = None
    speech_confidence: Optional[float] = None
    
    # GDPR Compliance
    transcription_consent: bool = True
    ai_training_consent: bool = False
    consent_timestamp: str
    consent_version: str = "1.0"
    
    # Processing Configuration
    threshold: int = 85
    user_level: Optional[str] = "beginner"

class BubbleAudioProcessResponse(BaseModel):
    """Comprehensive response with AI training tracking"""
    success: bool
    processing_time_ms: float
    timestamp: str
    
    # Session tracking
    session_id: str
    session_interaction_id: str
    answer_id: str
    attempt_number: int
    
    # Processing results
    adjustment_successful: bool
    match_found: bool
    intent_found: bool = False
    
    # AI Training tracking
    ai_training_data_stored: bool = False
    ai_training_record_id: Optional[str] = None
    training_data_retention_days: Optional[int] = None
    training_data_deletion_date: Optional[str] = None
    
    # GDPR compliance
    gdpr_compliant: bool = True
    legal_basis_transcription: str = "consent"
    legal_basis_ai_training: Optional[str] = None
    user_rights_available: List[str] = ["access", "rectification", "erasure", "objection", "portability"]
    
    # Error handling
    error: Optional[str] = None

class AITrainingConsentRequest(BaseModel):
    """AI training consent management"""
    user_auth_id: str
    consent_action: str  # "grant", "withdraw", "check_status"

class AITrainingConsentResponse(BaseModel):
    """AI training consent response"""
    success: bool
    user_id: str
    consent_active: bool
    granted_at: Optional[str] = None
    withdrawn_at: Optional[str] = None
    active_training_records: int = 0
    next_deletion_date: Optional[str] = None
    processing_time_ms: float
    timestamp: str
