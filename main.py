from fastapi import FastAPI, Request, Header, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict
from rapidfuzz import fuzz
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import difflib
import re
import json
import openai
import asyncpg
import aiohttp
import os

# --------------------------------------
# Centralized environment configuration
# --------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not DATABASE_URL:
    raise RuntimeError("Missing required environment variable: DATABASE_URL")
if not OPENAI_API_KEY:
    raise RuntimeError("Missing required environment variable: OPENAI_API_KEY")

openai.api_key = OPENAI_API_KEY

# ---------------
# FastAPI app
# ---------------
app = FastAPI()
API_KEY = "tuje-secure-key"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------
# Update Airtable
# ----------------------
AIRTABLE_TOKEN = os.getenv("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
AIRTABLE_TABLE_NAME = os.getenv("AIRTABLE_TABLE_NAME")

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



# ----------------------
# Data models
# ----------------------
class VocabularyEntry(BaseModel):
    phrase: str

class SavedAnswer(BaseModel):
    text: str
    is_correct: bool

class MatchResponse(BaseModel):
    matched_vocab: List[str]
    matched_entities: Dict[str, str]
    matches: List[Dict]
    call_gpt: bool

class GPTFallbackRequest(BaseModel):
    transcription: str
    intent_options: List[str]
    matched_vocab: Optional[List[str]] = []
    candidate_answers: Optional[List[SavedAnswer]] = []

class ScanVocabRequest(BaseModel):
    transcription: str
    vocabulary_phrases: List[str]

class ExtractOrderedRequest(BaseModel):
    transcription: str

class VocabEntry(BaseModel):
    id: str
    transcriptionFr: str
    transcriptionEn: str
    transcriptionAdjusted: str
    airtableRecordId: str
    lastModifiedTimeRef: int




# ----------------------
# Routes
# ----------------------
from match_routes import router as match_router
from airtable_routes import router as airtable_router  # if you create one

app.include_router(match_router)
app.include_router(airtable_router)  # optional, if you have Airtable routes


# ----------------------
# Local testing
# ----------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=10000)
