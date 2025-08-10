import asyncpg
from fastapi import APIRouter, HTTPException
import os

router = APIRouter()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Missing required environment variable: DATABASE_URL")


# -----------------
# Get All list of Intents data
# -----------------
@router.get("/intents")
async def get_live_intents():
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch("""
            SELECT id, name, description
            FROM brain_intent
            WHERE live = TRUE
            ORDER BY name ASC
        """)
        await conn.close()

        # Convert rows to list of dictionaries
        intents = [
            {
                "id": row["id"],
                "name": row["name"],
                "description": row["description"]
            }
            for row in rows
        ]
        return {"intents": intents}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



# -----------------
# Get the Interaction's list of Intents
# -----------------
@router.get("/interactions/{interaction_id}/intents")
async def get_interaction_intents(interaction_id: str):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        # First, get the list of intent IDs from brain_interaction
        result = await conn.fetchrow("""
            SELECT intents FROM brain_interaction WHERE id = $1
        """, interaction_id)
        
        if not result:
            await conn.close()
            raise HTTPException(status_code=404, detail="Interaction not found")

        intent_ids = result["intents"]

        # Now fetch matching intents
        intents = await conn.fetch("""
            SELECT id, name, description FROM brain_intent
            WHERE id = ANY($1)
        """, intent_ids)

        await conn.close()

        return [
            {
                "id": i["id"],
                "name": i["name"],
                "description": i["description"]
            }
            for i in intents
        ]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))





# -----------------
# Get Interactions Live and Subtopics Live
# Simple endpoint for bottom sheet
# -----------------

from pydantic import BaseModel
from typing import List

# Simple models for separate lists
class SimpleSubtopic(BaseModel):
    id: str
    nameFr: str

class SimpleInteraction(BaseModel):
    id: str
    transcriptionFr: str
    subtopicId: str

# Endpoint 1: Get all live subtopics
@router.get("/subtopics-only", response_model=List[SimpleSubtopic])
async def get_subtopics_only():
    """
    Get all live subtopics (just ID and name)
    """
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        rows = await conn.fetch("""
            SELECT id, name_fr
            FROM brain_subtopic
            WHERE live = TRUE
            ORDER BY name_fr ASC
        """)
        
        await conn.close()
        
        return [
            SimpleSubtopic(
                id=row["id"],
                nameFr=row["name_fr"]
            )
            for row in rows
        ]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Endpoint 2: Get all live interactions with subtopic reference
@router.get("/interactions-only", response_model=List[SimpleInteraction])
async def get_interactions_only():
    """
    Get all live interactions (just ID, transcription, and subtopic ID)
    """
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        rows = await conn.fetch("""
            SELECT id, transcription_fr, subtopic_id
            FROM brain_interaction
            WHERE live = TRUE AND subtopic_id IS NOT NULL
            ORDER BY subtopic_id, created_at ASC
        """)
        
        await conn.close()
        
        return [
            SimpleInteraction(
                id=row["id"],
                transcriptionFr=row["transcription_fr"],
                subtopicId=row["subtopic_id"]
            )
            for row in rows
        ]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
