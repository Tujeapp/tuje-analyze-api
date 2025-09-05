# main_bubble_router.py

from fastapi import APIRouter
from routers import (
    bubble_session_router,
    bubble_ai_training_router, 
    bubble_gdpr_router
)

# Create main router
router = APIRouter(prefix="/api/bubble", tags=["bubble_integration"])

# Include sub-routers
router.include_router(
    bubble_session_router.router,
    prefix="/session",
    tags=["session_management"]
)

router.include_router(
    bubble_ai_training_router.router, 
    prefix="/ai-training",
    tags=["ai_training"]
)

router.include_router(
    bubble_gdpr_router.router,
    prefix="/gdpr", 
    tags=["user_rights"]
)

@router.get("/health")
async def bubble_integration_health():
    """Health check for Bubble integration"""
    return {
        "status": "healthy",
        "service": "bubble_integration_modular",
        "modules": {
            "session_management": "✅ Ready",
            "ai_training": "✅ Ready", 
            "gdpr_rights": "✅ Ready"
        },
        "endpoints": {
            "session": "/api/bubble/session/",
            "ai_training": "/api/bubble/ai-training/",
            "gdpr": "/api/bubble/gdpr/"
        }
    }

@router.get("/config")
async def get_bubble_integration_config():
    """Configuration info for Bubble setup"""
    return {
        "integration_type": "modular_microservices",
        "main_endpoints": {
            "start_session": "/api/bubble/session/bubble-start-session",
            "process_audio": "/api/bubble/session/bubble-process-audio",
            "manage_ai_consent": "/api/bubble/ai-training/bubble-manage-ai-consent",
            "user_data_inventory": "/api/bubble/gdpr/bubble-user-data-inventory/{user_id}",
            "exercise_rights": "/api/bubble/gdpr/bubble-exercise-user-rights"
        },
        "workflow_patterns": {
            "basic_learning": [
                "1. POST /session/bubble-start-session",
                "2. POST /session/bubble-process-audio (with consent choices)",
                "3. Handle response.ai_training_data_stored"
            ],
            "ai_training_management": [
                "1. POST /ai-training/bubble-manage-ai-consent",
                "2. User can withdraw consent anytime",
                "3. All training data auto-deleted in 30 days"
            ],
            "gdpr_compliance": [
                "1. GET /gdpr/bubble-user-data-inventory/{user_id}",
                "2. POST /gdpr/bubble-exercise-user-rights",
                "3. Full transparency and control"
            ]
        }
    }
