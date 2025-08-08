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
# Get Interactions Live and grouped by Subtopics
# -----------------
from pydantic import BaseModel
from typing import List, Optional

class InteractionOut(BaseModel):
    id: str
    transcriptionFr: str
    transcriptionEn: str

class SubtopicGroup(BaseModel):
    subtopic_id: str
    subtopic_name: Optional[str]
    interactions: List[InteractionOut]

@router.get("/interactions-by-subtopic", response_model=List[SubtopicGroup])
async def get_interactions_by_subtopic():
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        rows = await conn.fetch("""
            SELECT
                bi.id,
                bi.transcription_fr,
                bi.transcription_en,
                bi.subtopic_id,
                bs.name AS subtopic_name
            FROM brain_interaction bi
            LEFT JOIN brain_subtopic bs ON bi.subtopic_id = bs.id
            WHERE bi.live = TRUE
            ORDER BY bs.name NULLS LAST, bi.created_at
        """)
        
        await conn.close()

        # Group by subtopic_id
        grouped = {}
        for row in rows:
            key = row["subtopic_id"] or "no_subtopic"
            if key not in grouped:
                grouped[key] = {
                    "subtopic_id": row["subtopic_id"],
                    "subtopic_name": row["subtopic_name"],
                    "interactions": []
                }
            grouped[key]["interactions"].append({
                "id": row["id"],
                "transcriptionFr": row["transcription_fr"],
                "transcriptionEn": row["transcription_en"]
            })

        return list(grouped.values())

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

