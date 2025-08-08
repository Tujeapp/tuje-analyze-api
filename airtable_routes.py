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
    createdAt: int
    live: bool = True

from datetime import datetime

@router.post("/webhook-sync-answer")
async def webhook_sync_answer(entry: AnswerEntry):
    try:
        # Convert milliseconds to datetime
        created_at_dt = datetime.utcfromtimestamp(entry.createdAt / 1000)
        updated_at_dt = datetime.utcfromtimestamp(entry.lastModifiedTimeRef / 1000)
        
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("""
            INSERT INTO brain_answer (id, transcription_fr, transcription_en, transcription_adjusted, airtable_record_id, last_modified_time_ref, created_at, update_at, live)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (id) DO UPDATE SET
        transcription_fr = EXCLUDED.transcription_fr,
        transcription_en = EXCLUDED.transcription_en,
        transcription_adjusted = EXCLUDED.transcription_adjusted,
        airtable_record_id = EXCLUDED.airtable_record_id,
        last_modified_time_ref = EXCLUDED.last_modified_time_ref,
        created_at = EXCLUDED.created_at,
        update_at = EXCLUDED.update_at,
        live = EXCLUDED.live;
        """, entry.id, entry.transcriptionFr, entry.transcriptionEn, entry.transcriptionAdjusted, entry.airtableRecordId, entry.lastModifiedTimeRef, created_at_dt, updated_at_dt, entry.live)
        await conn.close()

        await update_airtable_status(
            record_id=entry.airtableRecordId,
            fields={"LastModifiedSaved": entry.lastModifiedTimeRef},
            table_name="Answer"
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
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel

class InteractionEntry(BaseModel):
    id: str
    transcriptionFr: str
    transcriptionEn: str
    airtableRecordId: str
    lastModifiedTimeRef: int  # timestamp in ms
    createdAt: int            # timestamp in ms
    live: bool = True
    intents: List[str] = []
    subtopicId: Optional[str] = None

@router.post("/webhook-sync-interaction")
async def webhook_sync_interaction(entry: InteractionEntry):
    try:
        # Convert timestamps to datetime
        created_at_dt = datetime.utcfromtimestamp(entry.createdAt / 1000)
        updated_at_dt = datetime.utcfromtimestamp(entry.lastModifiedTimeRef / 1000)

        conn = await asyncpg.connect(DATABASE_URL)

        await conn.execute("""
            INSERT INTO brain_interaction (
                id, transcription_fr, transcription_en, airtable_record_id,
                last_modified_time_ref, created_at, update_at, live, intents, subtopic_id
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9::text[], $10
            )
            ON CONFLICT (id) DO UPDATE SET
                transcription_fr = EXCLUDED.transcription_fr,
                transcription_en = EXCLUDED.transcription_en,
                airtable_record_id = EXCLUDED.airtable_record_id,
                last_modified_time_ref = EXCLUDED.last_modified_time_ref,
                created_at = EXCLUDED.created_at,
                update_at = EXCLUDED.update_at,
                live = EXCLUDED.live,
                intents = EXCLUDED.intents,
                subtopic_id = EXCLUDED.subtopic_id;
        """, entry.id, entry.transcriptionFr, entry.transcriptionEn,
             entry.airtableRecordId, entry.lastModifiedTimeRef,
             created_at_dt, updated_at_dt, entry.live, entry.intents, entry.subtopicId)

        await conn.close()

        # Update Airtable to confirm sync
        await update_airtable_status(
            record_id=entry.airtableRecordId,
            fields={"LastModifiedSaved": entry.lastModifiedTimeRef},
            table_name="Interaction"
        )

        return {
            "message": "Interaction synced successfully",
            "entry_id": entry.id,
            "airtable_record_id": entry.airtableRecordId,
            "last_modified_time_ref": entry.lastModifiedTimeRef
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync error: {str(e)}")



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
    createdAt: int
    live: bool = True

from datetime import datetime

@router.post("/webhook-sync-vocab")
async def webhook_sync_vocab(entry: VocabEntry):
    try:
        # Convert milliseconds to datetime
        created_at_dt = datetime.utcfromtimestamp(entry.createdAt / 1000)
        updated_at_dt = datetime.utcfromtimestamp(entry.lastModifiedTimeRef / 1000)
        
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("""
            INSERT INTO brain_vocab (id, transcription_fr, transcription_en, transcription_adjusted, airtable_record_id, last_modified_time_ref, created_at, update_at, live)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
    ON CONFLICT (id) DO UPDATE SET
        transcription_fr = EXCLUDED.transcription_fr,
        transcription_en = EXCLUDED.transcription_en,
        transcription_adjusted = EXCLUDED.transcription_adjusted,
        airtable_record_id = EXCLUDED.airtable_record_id,
        last_modified_time_ref = EXCLUDED.last_modified_time_ref,
        created_at = EXCLUDED.created_at,
        update_at = EXCLUDED.update_at,
        live = EXCLUDED.live;
        """, entry.id, entry.transcriptionFr, entry.transcriptionEn, entry.transcriptionAdjusted, entry.airtableRecordId, entry.lastModifiedTimeRef, created_at_dt, updated_at_dt, entry.live)
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



# ----------------------
# Sync Intent 
# ----------------------
# Define the data model for intent entry
class IntentEntry(BaseModel):
    id: str
    name: str
    description: str
    airtableRecordId: str
    lastModifiedTimeRef: int
    createdAt: int
    live: bool = True


from datetime import datetime

@router.post("/webhook-sync-intent")
async def webhook_sync_intent(entry: IntentEntry):
    try:
        # Convert milliseconds to datetime
        created_at_dt = datetime.utcfromtimestamp(entry.createdAt / 1000)
        updated_at_dt = datetime.utcfromtimestamp(entry.lastModifiedTimeRef / 1000)

        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("""
            INSERT INTO brain_intent (id, name, description, airtable_record_id, last_modified_time_ref, created_at, update_at, live)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                airtable_record_id = EXCLUDED.airtable_record_id,
                last_modified_time_ref = EXCLUDED.last_modified_time_ref,
                created_at = EXCLUDED.created_at,
                update_at = EXCLUDED.update_at,
                live = EXCLUDED.live;
        """, entry.id, entry.name, entry.description, entry.airtableRecordId, entry.lastModifiedTimeRef, created_at_dt, updated_at_dt, entry.live)
        await conn.close()

        await update_airtable_status(
            record_id=entry.airtableRecordId,
            fields={"LastModifiedSaved": entry.lastModifiedTimeRef},
            table_name="Intent"
        )

        return {
            "message": "Intent synced and inserted",
            "entry_id": entry.id,
            "airtable_record_id": entry.airtableRecordId,
            "last_modified_time_ref": entry.lastModifiedTimeRef
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



# ----------------------
# Sync Subtopic 
# ----------------------

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime
import asyncpg

router = APIRouter()

# Pydantic model
class SubtopicEntry(BaseModel):
    id: str
    nameFr: str
    nameEn: str
    airtableRecordId: str
    lastModifiedTimeRef: int  # in ms
    createdAt: int            # in ms
    live: bool = True


@router.post("/webhook-sync-subtopic")
async def webhook_sync_subtopic(entry: SubtopicEntry):
    try:
        # Convert from milliseconds to UTC datetime
        created_at_dt = datetime.utcfromtimestamp(entry.createdAt / 1000)
        updated_at_dt = datetime.utcfromtimestamp(entry.lastModifiedTimeRef / 1000)

        # Connect to DB
        conn = await asyncpg.connect(DATABASE_URL)

        # Insert or update
        await conn.execute("""
            INSERT INTO brain_subtopic (
                id, name_fr, name_en, airtable_record_id, 
                last_modified_time_ref, created_at, update_at, live
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (id) DO UPDATE SET
                name_fr = EXCLUDED.name_fr,
                name_en = EXCLUDED.name_en,
                airtable_record_id = EXCLUDED.airtable_record_id,
                last_modified_time_ref = EXCLUDED.last_modified_time_ref,
                created_at = EXCLUDED.created_at,
                update_at = EXCLUDED.update_at,
                live = EXCLUDED.live;
        """, entry.id, entry.nameFr, entry.nameEn, entry.airtableRecordId,
             entry.lastModifiedTimeRef, created_at_dt, updated_at_dt, entry.live)

        await conn.close()

        # Update Airtable to mark as saved
        await update_airtable_status(
            record_id=entry.airtableRecordId,
            fields={"LastModifiedSaved": entry.lastModifiedTimeRef},
            table_name="Subtopic"
        )

        return {
            "message": "Subtopic synced successfully",
            "entry_id": entry.id,
            "airtable_record_id": entry.airtableRecordId,
            "last_modified_time_ref": entry.lastModifiedTimeRef
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error syncing subtopic: {e}")
