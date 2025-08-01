from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict

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
app = FastAPI()
API_KEY = "tuje-secure-key"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust if needed for production
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
# Pydantic Models
# (consider moving later to `models.py`)
# -------------------------------
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

# -------------------------------
# Route Inclusion
# -------------------------------
from match_routes import router as match_router
# from airtable_routes import router as airtable_router  # Uncomment if needed

app.include_router(match_router)
# app.include_router(airtable_router)

# -------------------------------
# Run locally
# -------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=10000)
