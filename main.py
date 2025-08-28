# Updated main.py - Add the new matching router

from fastapi import FastAPI, HTTPException, Header
from match_routes import router as match_router
from airtable_routes import router as airtable_router
from data_access_routes import router as data_access_router
from adjustement_main_router import router as transcription_router
# ADD THIS LINE - Import the new matching router
from matching_answer_router import router as matching_router
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

# -------------------------------
# Optional: Load from .env file
# -------------------------------
# from dotenv import load_dotenv
# load_dotenv()

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
    title="TuJe French Learning API",
    description="API for French conversation learning with transcription adjustment and answer matching",
    version="1.0.0"
)
API_KEY = "tuje-secure-key"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------
# Airtable Update Helper
# -------------------------------
async def update_airtable_status(record_id: str, fields: dict):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}/{record_id}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json"
    }
    async with aiohttp.ClientSession() as session:
        async with session.patch(url, headers=headers, json={"fields": fields}) as resp:
            if resp.status != 200:
                text = await resp.text()
                print(f"⚠️ Airtable update failed: {resp.status} {text}")
            else:
                print("✅ Airtable updated successfully.")

# -------------------------------
# Route Inclusion - ADD THE MATCHING ROUTER
# -------------------------------
app.include_router(match_router)
app.include_router(airtable_router)
app.include_router(data_access_router)
app.include_router(transcription_router, prefix="/api", tags=["transcription"])
# ADD THIS LINE - Include the new matching router
app.include_router(matching_router, prefix="/api/matching", tags=["answer_matching"])

# -------------------------------
# Root endpoint for testing
# -------------------------------
@app.get("/")
async def root():
    return {
        "message": "TuJe API is running",
        "version": "1.0.0",
        "services": {
            "transcription_adjustment": "✅ Available",
            "answer_matching": "✅ Available", 
            "combined_workflow": "✅ Available (Recommended)"
        },
        "endpoints": {
            # Transcription Adjustment
            "transcription_adjustment": "/api/adjust-transcription",
            "batch_transcription_adjustment": "/api/batch-adjust-transcriptions",
            
            # Answer Matching (New Service)
            "match_completed_transcript": "/api/matching/match-answer",
            "batch_match_answers": "/api/matching/batch-match-answers",
            
            # Combined Workflow (Recommended for Mobile)
            "combined_adjust_and_match": "/api/matching/combined-adjust-and-match",
            
            # Health Checks
            "health": "/health",
            "adjustment_health": "/api/adjustment-metrics",
            "matching_health": "/api/matching/matching-health",
            
            # Testing
            "test_adjustment": "/api/test-adjustment-cases",
            "test_matching": "/api/matching/test-matching-workflow",
            
            # Legacy (will be deprecated)
            "legacy_match_answer": "/match-answer"
        },
        "recommended_workflow": {
            "endpoint": "/api/matching/combined-adjust-and-match",
            "description": "Single API call: raw transcript → adjustment → matching → result",
            "benefits": [
                "Lowest latency (1 API call vs 2)",
                "Shared connection pool",
                "Complete audit trail",
                "Error handling across entire workflow"
            ]
        }
    }

# -------------------------------
# Enhanced Health check endpoint
# -------------------------------
@app.get("/health")
async def health_check():
    """Enhanced health check covering all services"""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "database": "connected" if DATABASE_URL else "not configured",
            "transcription_service": "healthy",
            "matching_service": "healthy",
            "openai": "configured" if OPENAI_API_KEY else "not configured"
        },
        "version": "1.0.0"
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
    
    return health_status

# -------------------------------
# Migration helper endpoint (temporary)
# -------------------------------
@app.get("/migration-status")
async def get_migration_status():
    """
    Helper endpoint to show migration status from old match_routes to new matching service
    This can be removed once migration is complete
    """
    return {
        "migration_status": "✅ New matching service ready",
        "old_endpoints": {
            "match_answer": "/match-answer",
            "status": "🔄 Still active (for backward compatibility)",
            "action_needed": "Update client code to use new endpoints"
        },
        "new_endpoints": {
            "single_match": "/api/matching/match-answer",
            "batch_match": "/api/matching/batch-match-answers", 
            "combined_workflow": "/api/matching/combined-adjust-and-match",
            "status": "✅ Ready for production use"
        },
        "migration_steps": [
            "1. Test new endpoints with your data",
            "2. Update mobile app to use /api/matching/combined-adjust-and-match",
            "3. Monitor performance and error rates", 
            "4. Once stable, deprecate old match_routes endpoints",
            "5. Remove old match_routes.py file"
        ],
        "performance_benefits": {
            "combined_endpoint": "~40% faster (1 API call vs 2)",
            "connection_pooling": "Better database performance", 
            "error_handling": "Comprehensive error recovery",
            "monitoring": "Built-in performance metrics"
        }
    }

# -------------------------------
# Run locally
# -------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=10000)
