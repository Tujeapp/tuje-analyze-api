from fastapi import APIRouter, HTTPException
import asyncpg
from typing import List
from models import IntentEntry, VocabEntry  # adjust to match your structure
from config import DATABASE_URL

router = APIRouter()


# ----------------------
# Get Intent data 
# ----------------------
@router.get("/intents", response_model=List[IntentEntry])
async def get_all_intents():
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch("SELECT * FROM brain_intent WHERE live = TRUE ORDER BY name")
        await conn.close()
        return [
            IntentEntry(**dict(row)) for row in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ----------------------
# Get Vocab data 
# ----------------------
@router.get("/vocab", response_model=List[VocabEntry])
async def get_all_vocab():
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch("SELECT * FROM brain_vocab WHERE live = TRUE ORDER BY transcription_fr")
        await conn.close()
        return [
            VocabEntry(**dict(row)) for row in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
