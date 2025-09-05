# bubble_ai_training_router.py

from fastapi import APIRouter, HTTPException
import time
from models.bubble_models import AITrainingConsentRequest, AITrainingConsentResponse
from services.ai_training_service import AITrainingService
import os

router = APIRouter()
ai_training_service = AITrainingService(os.getenv("DATABASE_URL"))

@router.post("/bubble-manage-ai-consent", response_model=AITrainingConsentResponse)
async def bubble_manage_ai_training_consent(request: AITrainingConsentRequest):
    """Manage AI training consent"""
    start_time = time.time()
    
    try:
        if request.consent_action == "grant":
            result = await ai_training_service.grant_consent(request.user_auth_id)
        elif request.consent_action == "withdraw":
            result = await ai_training_service.withdraw_consent(request.user_auth_id)
        else:  # check_status
            result = await ai_training_service.get_user_inventory(request.user_auth_id)
        
        processing_time = round((time.time() - start_time) * 1000, 2)
        
        return AITrainingConsentResponse(
            success=True,
            user_id=request.user_auth_id,
            consent_active=result.get("consent_active", False),
            granted_at=result.get("granted_at"),
            withdrawn_at=result.get("withdrawn_at"),
            active_training_records=result.get("active_records", 0),
            processing_time_ms=processing_time,
            timestamp=datetime.now().isoformat()
        )
        
    except Exception as e:
        processing_time = round((time.time() - start_time) * 1000, 2)
        return AITrainingConsentResponse(
            success=False,
            user_id=request.user_auth_id,
            consent_active=False,
            processing_time_ms=processing_time,
            timestamp=datetime.now().isoformat()
        )
