# bubble_session_router.py

from fastapi import APIRouter, HTTPException
import time
from datetime import datetime
from models.bubble_models import BubbleSessionRequest, BubbleAudioProcessRequest, BubbleAudioProcessResponse
from services.session_management_service import SessionService

router = APIRouter()
session_service = SessionService()

@router.post("/bubble-start-session")
async def bubble_start_session(request: BubbleSessionRequest):
    """Start a new learning session"""
    start_time = time.time()
    
    try:
        # Get or create user
        user_id = await session_service.get_or_create_user(
            auth_provider=request.auth_provider,
            auth_id=request.user_auth_id,
            app_version=request.app_version,
            device_type=request.device_type
        )
        
        # Start session
        session_id = await session_service.start_session(
            user_id=user_id,
            subtopic_id=request.subtopic_id,
            session_type=request.session_type,
            difficulty_level=request.difficulty_level
        )
        
        # Start first cycle
        cycle_id = await session_service.start_cycle(
            session_id=session_id,
            cycle_number=1,
            cycle_type="practice"
        )
        
        processing_time = round((time.time() - start_time) * 1000, 2)
        
        return {
            "success": True,
            "session_id": session_id,
            "user_id": user_id,
            "cycle_id": cycle_id,
            "processing_time_ms": processing_time,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        processing_time = round((time.time() - start_time) * 1000, 2)
        return {
            "success": False,
            "session_id": "",
            "user_id": "",
            "processing_time_ms": processing_time,
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }

@router.post("/bubble-process-audio", response_model=BubbleAudioProcessResponse)
async def bubble_process_audio_enhanced(request: BubbleAudioProcessRequest):
    """Complete audio processing with AI training option"""
    start_time = time.time()
    
    try:
        # Process through complete pipeline
        processing_result = await session_service.process_user_answer_enhanced(
            session_id=request.session_id,
            interaction_id=request.interaction_id,
            raw_transcript=request.original_transcript,
            audio_duration_ms=request.audio_duration_ms,
            speech_confidence=request.speech_confidence,
            ai_training_consent=request.ai_training_consent,
            user_level=request.user_level,
            consent_metadata={
                'timestamp': request.consent_timestamp,
                'version': request.consent_version
            }
        )
        
        processing_time = round((time.time() - start_time) * 1000, 2)
        
        return BubbleAudioProcessResponse(
            success=True,
            processing_time_ms=processing_time,
            timestamp=datetime.now().isoformat(),
            session_id=request.session_id,
            session_interaction_id=processing_result["session_interaction_id"],
            answer_id=processing_result["answer_id"],
            attempt_number=processing_result["attempt_number"],
            adjustment_successful=processing_result["adjustment_successful"],
            match_found=processing_result["match_found"],
            intent_found=processing_result.get("intent_found", False),
            ai_training_data_stored=processing_result["ai_training"]["stored"],
            ai_training_record_id=processing_result["ai_training"].get("record_id"),
            training_data_retention_days=30 if processing_result["ai_training"]["stored"] else None
        )
        
    except Exception as e:
        processing_time = round((time.time() - start_time) * 1000, 2)
        return BubbleAudioProcessResponse(
            success=False,
            processing_time_ms=processing_time,
            timestamp=datetime.now().isoformat(),
            session_id=request.session_id,
            session_interaction_id="",
            answer_id="",
            attempt_number=0,
            adjustment_successful=False,
            match_found=False,
            error=str(e)
        )
