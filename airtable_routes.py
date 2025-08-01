import os
import httpx
from fastapi import APIRouter, HTTPException
import asyncpg
from pydantic import BaseModel

# Load env vars
DATABASE_URL = os.getenv("DATABASE_URL")
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")

# Safety checks
if not DATABASE_URL:
    raise RuntimeError("Missing required environment variable: DATABASE_URL")
if not AIRTABLE_API_KEY:
    raise RuntimeError("Missing required environment variable: AIRTABLE_API_KEY")
if not AIRTABLE_BASE_ID:
    raise RuntimeError("Missing required environment variable: AIRTABLE_BASE_ID")

# Setup router
router = APIRouter()

# Airtable config
AIRTABLE_BASE_URL = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}"
HEADERS = {
    "Authorization": f"Bearer {AIRTABLE_API_KEY}",
    "Content-Type": "application/json"
}

# Function to update Airtable
async def update_airtable_status(record_id: str, fields: dict, table_name: str):
    url = f"{AIRTABLE_BASE_URL}/{table_name}/{record_id}"
    payload = { "fields": fields }

    async with httpx.AsyncClient() as client:
        response = await client.patch(url, json=payload, headers=HEADERS)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=response.status_code, detail=response.text)


# ----------------------
# Sync Answer
# ----------------------
class AnswerEntry(BaseModel):
    id: str
    transcriptionFr: str
    transcriptionEn: str
    transcriptionAdjusted: str
    airtableRecordId: str
    lastModifiedTimeRef: int

@router.post("/webhook-sync-answer")
async def webhook_sync_answer(entry: AnswerEntry):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("""
            INSERT INTO brain_answer (id, transcription_fr, transcription_en, transcription_adjusted, airtable_record_id, last_modified_time_ref)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (id) DO UPDATE SET
        transcription_fr = EXCLUDED.transcription_fr,
        transcription_en = EXCLUDED.transcription_en,
        transcription_adjusted = EXCLUDED.transcription_adjusted,
        airtable_record_id = EXCLUDED.airtable_record_id,
        last_modified_time_ref = EXCLUDED.last_modified_time_ref;
        """, entry.id, entry.transcriptionFr, entry.transcriptionEn, entry.transcriptionAdjusted, entry.airtableRecordId, entry.lastModifiedTimeRef)
        await conn.close()

        await update_airtable_status(
            record_id=entry.airtableRecordId,
            fields={"LastModifiedSaved": entry.lastModifiedTimeRef},
            table_name="Answers"
        )

        return {
    "message": "Answer synced and inserted",
    "entry_id": entry.id,
    "airtable_record_id": entry.airtableRecordId,
    "last_modified_time_ref": entry.lastModifiedTimeRef
}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



# ----------------------
# Sync Interaction
# ----------------------
class InteractionEntry(BaseModel):
    id: str
    transcriptionFr: str
    transcriptionEn: str
    airtableRecordId: str
    lastModifiedTimeRef: int

@router.post("/webhook-sync-interaction")
async def webhook_sync_interaction(entry: InteractionEntry):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("""
            INSERT INTO brain_interaction (
                id, transcription_fr, transcription_en, airtable_record_id, last_modified_time_ref
            )
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (id) DO UPDATE SET
                transcription_fr = EXCLUDED.transcription_fr,
                transcription_en = EXCLUDED.transcription_en,
                airtable_record_id = EXCLUDED.airtable_record_id,
                last_modified_time_ref = EXCLUDED.last_modified_time_ref;
        """, entry.id, entry.transcriptionFr, entry.transcriptionEn, entry.airtableRecordId, entry.lastModifiedTimeRef)
        await conn.close()

        await update_airtable_status(
            record_id=entry.airtableRecordId,
            fields={"LastModifiedSaved": entry.lastModifiedTimeRef},
            table_name="Interaction"
        )

        return {
            "message": "Interaction synced and inserted",
            "entry_id": entry.id,
            "airtable_record_id": entry.airtableRecordId,
            "last_modified_time_ref": entry.lastModifiedTimeRef
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



# ----------------------
# Sync Interaction-Answer
# ----------------------
class InteractionAnswerEntry(BaseModel):
    id: str
    interactionId: str
    answerId: str
    airtableRecordId: str
    lastModifiedTimeRef: int

@router.post("/webhook-sync-interaction-answer")
async def webhook_sync_interaction_answer(entry: InteractionAnswerEntry):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("""
            INSERT INTO brain_interaction_answer (
                id, interaction_id, answer_id, airtable_record_id, last_modified_time_ref
            )
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (id) DO UPDATE SET
                interaction_id = EXCLUDED.interaction_id,
                answer_id = EXCLUDED.answer_id,
                airtable_record_id = EXCLUDED.airtable_record_id,
                last_modified_time_ref = EXCLUDED.last_modified_time_ref;
        """, entry.id, entry.interactionId, entry.answerId, entry.airtableRecordId, entry.lastModifiedTimeRef)
        await conn.close()

        await update_airtable_status(
            record_id=entry.airtableRecordId,
            fields={"LastModifiedSaved": entry.lastModifiedTimeRef},
            table_name="Interaction-Answer"
        )

        return {
            "message": "Interaction-Answer link synced",
            "entry_id": entry.id,
            "airtable_record_id": entry.airtableRecordId,
            "last_modified_time_ref": entry.lastModifiedTimeRef
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



# ----------------------
# Sync Vocab 
# ----------------------
# Define the data model for vocab entry
class VocabEntry(BaseModel):
    id: str
    transcriptionFr: str
    transcriptionEn: str
    transcriptionAdjusted: str
    airtableRecordId: str
    lastModifiedTimeRef: int


@router.post("/webhook-sync-vocab")
async def webhook_sync_vocab(entry: VocabEntry):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("""
            INSERT INTO brain_vocab (id, transcription_fr, transcription_en, transcription_adjusted, airtable_record_id, last_modified_time_ref)
            VALUES ($1, $2, $3, $4, $5, $6)
    ON CONFLICT (id) DO UPDATE SET
        transcription_fr = EXCLUDED.transcription_fr,
        transcription_en = EXCLUDED.transcription_en,
        transcription_adjusted = EXCLUDED.transcription_adjusted,
        airtable_record_id = EXCLUDED.airtable_record_id,
        last_modified_time_ref = EXCLUDED.last_modified_time_ref;
        """, entry.id, entry.transcriptionFr, entry.transcriptionEn, entry.transcriptionAdjusted, entry.airtableRecordId, entry.lastModifiedTimeRef)
        await conn.close()

        await update_airtable_status(
            record_id=entry.airtableRecordId,
            fields={"LastModifiedSaved": entry.lastModifiedTimeRef},
            table_name="Vocab"
        )

        return {
    "message": "Vocab synced and inserted",
    "entry_id": entry.id,
    "airtable_record_id": entry.airtableRecordId,
    "last_modified_time_ref": entry.lastModifiedTimeRef
}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
