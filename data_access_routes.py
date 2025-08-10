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
# Simple endpoint for bottom sheet
# -----------------

from pydantic import BaseModel
from typing import List

# Simple models for bottom sheet
class SimpleInteraction(BaseModel):
    id: str
    transcriptionFr: str

class SimpleSubtopic(BaseModel):
    id: str
    nameFr: str
    interactions: List[SimpleInteraction]

@router.get("/subtopics-simple", response_model=List[SimpleSubtopic])
async def get_subtopics_simple():
    """
    Get live subtopics with their live interactions (IDs only)
    Minimal data for bottom sheet accordion
    """
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Get all live subtopics
        subtopics_query = """
            SELECT id, name_fr
            FROM brain_subtopic
            WHERE live = TRUE
            ORDER BY name_fr ASC
        """
        
        subtopic_rows = await conn.fetch(subtopics_query)
        result = []
        
        for subtopic_row in subtopic_rows:
            # Get live interactions for this subtopic
            interactions_query = """
                SELECT id, transcription_fr
                FROM brain_interaction
                WHERE subtopic_id = $1 AND live = TRUE
                ORDER BY created_at ASC
            """
            
            interaction_rows = await conn.fetch(interactions_query, subtopic_row["id"])
            
            # Convert to simple format
            interactions = [
                SimpleInteraction(
                    id=interaction_row["id"],
                    transcriptionFr=interaction_row["transcription_fr"]
                )
                for interaction_row in interaction_rows
            ]
            
            # Only include subtopics that have interactions
            if interactions:
                result.append(SimpleSubtopic(
                    id=subtopic_row["id"],
                    nameFr=subtopic_row["name_fr"],
                    interactions=interactions
                ))
        
        await conn.close()
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
