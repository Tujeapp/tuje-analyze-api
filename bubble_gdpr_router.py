# bubble_gdpr_router.py

from fastapi import APIRouter, HTTPException
from services.gdpr_rights_service import GDPRRightsService
import os

router = APIRouter()
gdpr_service = GDPRRightsService(os.getenv("DATABASE_URL"))

@router.get("/bubble-user-data-inventory/{user_auth_id}")
async def bubble_get_user_data_inventory(user_auth_id: str):
    """Get comprehensive user data inventory"""
    try:
        inventory = await gdpr_service.get_user_data_inventory(user_auth_id)
        
        return {
            "user_id": user_auth_id,
            "data_inventory": {
                "user_profile": {
                    "member_since": inventory.get('user_since'),
                    "total_learning_sessions": inventory.get('total_sessions'),
                    "current_learning_streak": inventory.get('current_streak_days')
                },
                "ai_training_data": {
                    "consent_active": inventory.get('ai_consent_active', False),
                    "total_recordings_contributed": inventory.get('total_recordings_contributed', 0),
                    "current_active_recordings": inventory.get('current_active_recordings', 0),
                    "next_deletion_date": inventory.get('next_ai_deletion'),
                    "retention_policy": "Maximum 30 days, then automatic secure deletion"
                }
            },
            "user_rights": {
                "available_actions": [
                    "download_learning_progress",
                    "delete_all_data", 
                    "withdraw_ai_consent",
                    "export_session_history"
                ],
                "gdpr_compliant": True,
                "response_time_guarantee": "Within 30 days"
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/bubble-exercise-user-rights")
async def bubble_exercise_user_rights(
    user_auth_id: str,
    right_type: str,  # "access", "portability", "erasure", "objection"
    specific_request: str = None
):
    """Exercise GDPR rights"""
    try:
        if right_type == "erasure":
            result = await gdpr_service.exercise_right_to_erasure(user_auth_id)
        elif right_type == "portability":
            result = await gdpr_service.exercise_right_to_portability(user_auth_id)
        elif right_type == "objection":
            # Specifically for AI training
            result = await ai_training_service.withdraw_consent(user_auth_id)
        else:
            result = {
                "request_type": right_type,
                "status": "not_implemented",
                "available_rights": ["access", "portability", "erasure", "objection"]
            }
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
