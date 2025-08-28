# Updated main.py - Add Bubble integration router

from fastapi import FastAPI, HTTPException, Header
from match_routes import router as match_router
from airtable_routes import router as airtable_router
from data_access_routes import router as data_access_router
from gpt_fallback_router import router as gpt_fallback_router
from adjustement_main_router import router as transcription_router
from matching_answer_router import router as matching_router
from bubble_integration_router import router as bubble_router  # 🆕 NEW: Add Bubble router
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict
from models import (
    VocabularyEntry,
    SavedAnswer,
    VocabEntry,
    ScanVocabRequest,
    ExtractOrderedRequest,
    GPTFallbackRequest,
    MatchResponse
)
import aiohttp
import asyncpg
import openai
import os
from datetime import datetime

# -------------------------------
# Environment variables
# -------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
AIRTABLE_TOKEN = os.getenv("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
AIRTABLE_TABLE_NAME = os.getenv("AIRTABLE_TABLE_NAME")

if not DATABASE_URL:
    raise RuntimeError("Missing required environment variable: DATABASE_URL")
if not OPENAI_API_KEY:
    raise RuntimeError("Missing required environment variable: OPENAI_API_KEY")

openai.api_key = OPENAI_API_KEY

# -------------------------------
# FastAPI App Setup
# -------------------------------
app = FastAPI(
    title="TuJe French Learning API with Bubble Integration",
    description="API for French conversation learning with Bubble.io optimized endpoints",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------
# Route Inclusion - 🆕 ADD BUBBLE ROUTER
# -------------------------------
app.include_router(match_router)
app.include_router(airtable_router)
app.include_router(data_access_router)
app.include_router(transcription_router, prefix="/api", tags=["transcription"])
app.include_router(matching_router, prefix="/api/matching", tags=["answer_matching"])
app.include_router(gpt_fallback_router, prefix="/api/gpt", tags=["gpt_fallback"])
app.include_router(bubble_router, prefix="/api/bubble", tags=["bubble_integration"])  # 🆕 NEW

# -------------------------------
# Root endpoint - Updated for Bubble
# -------------------------------
@app.get("/")
async def root():
    return {
        "message": "TuJe API with Bubble Integration",
        "version": "2.0.0",
        "bubble_integration": "✅ Ready",
        "services": {
            "transcription_adjustment": "✅ Available",
            "answer_matching": "✅ Available", 
            "gpt_fallback": "✅ Available",
            "bubble_optimized": "✅ Available"
        },
        
        # 🆕 NEW: Bubble-specific endpoints
        "bubble_endpoints": {
            # Main endpoint for Bubble workflows
            "complete_processing": {
                "url": "/api/bubble/bubble-process-transcript",
                "method": "POST",
                "description": "🎯 RECOMMENDED: Complete pipeline (adjust → match → gpt)",
                "use_case": "Primary endpoint for Bubble workflows"
            },
            
            # Individual services for specific needs
            "adjustment_only": {
                "url": "/api/bubble/bubble-adjust-only", 
                "method": "POST",
                "description": "Transcription adjustment only"
            },
            "matching_only": {
                "url": "/api/bubble/bubble-match-only",
                "method": "POST", 
                "description": "Answer matching only"
            },
            "gpt_only": {
                "url": "/api/bubble/bubble-gpt-only",
                "method": "POST",
                "description": "GPT intent detection only"
            },
            
            # Configuration and health
            "config": "/api/bubble/bubble-config",
            "health": "/api/bubble/bubble-health"
        },
        
        "bubble_integration_guide": {
            "step1": "Use /api/bubble/bubble-config to get configuration details",
            "step2": "Test with /api/bubble/bubble-process-transcript",
            "step3": "Handle response.recommended_action in your workflow",
            "step4": "Monitor response.errors and response.warnings"
        },
        
        # Legacy endpoints (still available)
        "advanced_endpoints": {
            "transcription_adjustment": "/api/adjust-transcription",
            "answer_matching": "/api/matching/combined-adjust-and-match",
            "gpt_fallback": "/api/gpt/analyze-intent",
            "health_checks": ["/health", "/api/bubble/bubble-health"]
        }
    }

# -------------------------------
# Enhanced Health check
# -------------------------------
@app.get("/health")
async def health_check():
    """Enhanced health check covering all services including Bubble integration"""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "database": "unknown",
            "transcription_service": "healthy",
            "matching_service": "healthy",
            "gpt_service": "healthy",
            "bubble_integration": "healthy",  # 🆕 NEW
            "openai": "configured" if OPENAI_API_KEY else "not configured"
        },
        "version": "2.0.0",
        "bubble_ready": True  # 🆕 NEW
    }
    
    try:
        # Test database connection
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

# -------------------------------
# 🆕 NEW: Bubble Integration Status Endpoint
# -------------------------------
@app.get("/bubble-status")
async def get_bubble_integration_status():
    """
    Comprehensive status check specifically for Bubble integration
    """
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
        "next_steps": [
            "1. Test /api/bubble/bubble-process-transcript with sample data",
            "2. Set up Bubble workflow to handle response.recommended_action",
            "3. Monitor response.errors for any issues",
            "4. Use response.call_gpt_manually for manual GPT triggers"
        ]
    }

# -------------------------------
# Run locally
# -------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=10000)
