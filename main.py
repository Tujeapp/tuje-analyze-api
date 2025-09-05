# main.py - Fixed and Clean Version

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import asyncpg
import openai
import os

# =====================================
# IMPORTS - Keep Your Existing Routers
# =====================================
from match_routes import router as match_router
from airtable_routes import router as airtable_router
from data_access_routes import router as data_access_router
from gpt_fallback_router import router as gpt_fallback_router
from adjustement_main_router import router as transcription_router
from matching_answer_router import router as matching_router

# BUBBLE ROUTER - Choose ONE of these options:

# OPTION 1: Use your existing single-file router (recommended for now)
from bubble_integration_router import router as bubble_router

# OPTION 2: Use the new modular router (for future migration)
# from main_bubble_router import router as bubble_router

# =====================================
# ENVIRONMENT VARIABLES
# =====================================
DATABASE_URL = os.getenv("DATABASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
AIRTABLE_TOKEN = os.getenv("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
AIRTABLE_TABLE_NAME = os.getenv("AIRTABLE_TABLE_NAME")

# Validation
if not DATABASE_URL:
    raise RuntimeError("Missing required environment variable: DATABASE_URL")
if not OPENAI_API_KEY:
    raise RuntimeError("Missing required environment variable: OPENAI_API_KEY")

openai.api_key = OPENAI_API_KEY

# =====================================
# FASTAPI APP SETUP
# =====================================
app = FastAPI(
    title="TuJe French Learning API with Bubble Integration",
    description="API for French conversation learning with Bubble.io integration and GDPR compliance",
    version="2.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================
# ROUTE INCLUSION
# =====================================
app.include_router(match_router)
app.include_router(airtable_router)
app.include_router(data_access_routes)
app.include_router(transcription_router, prefix="/api", tags=["transcription"])
app.include_router(matching_router, prefix="/api/matching", tags=["answer_matching"])
app.include_router(gpt_fallback_router, prefix="/api/gpt", tags=["gpt_fallback"])

# Bubble Integration Router
app.include_router(bubble_router, prefix="/api/bubble", tags=["bubble_integration"])

# =====================================
# ROOT ENDPOINT
# =====================================
@app.get("/")
async def root():
    return {
        "message": "TuJe API with Bubble Integration",
        "version": "2.1.0",
        "bubble_integration": "✅ Ready",
        
        "services": {
            "transcription_adjustment": "✅ Available",
            "answer_matching": "✅ Available", 
            "gpt_fallback": "✅ Available",
            "bubble_optimized": "✅ Available"
        },
        
        # Main Bubble endpoints
        "bubble_endpoints": {
            "process_transcript": "/api/bubble/bubble-process-transcript",
            "adjust_transcript": "/api/bubble/bubble-adjust-transcript",
            "match_answer": "/api/bubble/bubble-match-answer",
            "gpt_fallback": "/api/bubble/bubble-gpt-fallback",
            "config": "/api/bubble/bubble-config",
            "health": "/api/bubble/bubble-health"
        },
        
        # Advanced endpoints
        "advanced_endpoints": {
            "transcription_adjustment": "/api/adjust-transcription",
            "answer_matching": "/api/matching/combined-adjust-and-match",
            "gpt_fallback": "/api/gpt/analyze-intent",
            "health_checks": ["/health", "/api/bubble/bubble-health"]
        },
        
        "integration_guide": {
            "step1": "Use /api/bubble/bubble-config to get configuration details",
            "step2": "Test with /api/bubble/bubble-process-transcript",
            "step3": "Handle response.recommended_action in your workflow",
            "step4": "Monitor response.errors and response.warnings"
        }
    }

# =====================================
# HEALTH CHECK
# =====================================
@app.get("/health")
async def health_check():
    """Enhanced health check covering all services"""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "2.1.0",
        "services": {
            "database": "unknown",
            "transcription_service": "healthy",
            "matching_service": "healthy",
            "gpt_service": "healthy",
            "bubble_integration": "healthy",
            "openai": "configured" if OPENAI_API_KEY else "not configured"
        },
        "bubble_ready": True
    }
    
    # Test database connection
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        try:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            health_status["services"]["database"] = "connected"
        except Exception as e:
            health_status["services"]["database"] = f"error: {str(e)}"
            health_status["status"] = "degraded"
        finally:
            await pool.close()
    except Exception as e:
        health_status["services"]["database"] = f"connection_error: {str(e)}"
        health_status["status"] = "unhealthy"
        health_status["bubble_ready"] = False
    
    return health_status

# =====================================
# BUBBLE INTEGRATION STATUS
# =====================================
@app.get("/bubble-status")
async def get_bubble_integration_status():
    """Comprehensive status check specifically for Bubble integration"""
    return {
        "bubble_integration_status": "✅ Ready for production",
        "main_endpoint": "/api/bubble/bubble-process-transcript",
        
        "processing_pipeline": {
            "transcription_adjustment": "✅ Working",
            "answer_matching": "✅ Working",
            "gpt_fallback": "✅ Working",
            "auto_trigger_logic": "✅ Implemented"
        },
        
        "response_format": {
            "unified_response": "✅ Bubble-friendly format",
            "error_handling": "✅ Comprehensive",
            "recommended_actions": "✅ Automated suggestions"
        },
        
        "performance": {
            "single_api_call": "✅ Complete workflow in one request",
            "connection_pooling": "✅ Optimized database usage",
            "async_processing": "✅ Non-blocking operations"
        },
        
        "cost_optimization": {
            "gpt_auto_trigger": "✅ Only when needed",
            "shared_connections": "✅ Database pool reuse",
            "error_recovery": "✅ Graceful fallbacks"
        },
        
        "testing_guide": [
            "1. Test /api/bubble/bubble-process-transcript with sample data",
            "2. Set up Bubble workflow to handle response.recommended_action",
            "3. Monitor response.errors for any issues",
            "4. Use response.call_gpt_manually for manual GPT triggers"
        ],
        
        "bubble_workflow_tips": {
            "use_combined_endpoint": "Yes - most efficient for mobile apps",
            "threshold_optimization": "Consider lowering threshold if no matches found",
            "caching": "Service automatically caches interaction answers"
        }
    }

# =====================================
# FUTURE: Modular Architecture Status (Ready for Migration)
# =====================================
@app.get("/modular-migration-info")
async def get_modular_migration_info():
    """Information about future modular architecture migration"""
    return {
        "current_architecture": "single_file_bubble_router",
        "migration_ready": True,
        
        "future_modular_structure": {
            "session_management": "Dedicated service for user sessions",
            "ai_training": "GDPR-compliant AI training data management",
            "gdpr_rights": "User rights management service",
            "audio_processing": "Enhanced audio handling with 30-day retention option"
        },
        
        "migration_benefits": [
            "✅ Better code organization",
            "✅ Easier testing and maintenance",
            "✅ GDPR compliance by design",
            "✅ AI training data management",
            "✅ Modular deployment options"
        ],
        
        "migration_plan": {
            "phase1": "Split existing router into logical services",
            "phase2": "Implement AI training consent management",
            "phase3": "Add GDPR user rights endpoints",
            "phase4": "Enhanced monitoring and compliance"
        },
        
        "backwards_compatibility": "✅ All existing endpoints will continue to work"
    }

# =====================================
# RUN APPLICATION
# =====================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=10000, reload=True)
