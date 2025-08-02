import asyncpg
from fastapi import APIRouter, HTTPException
import os

router = APIRouter()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Missing required environment variable: DATABASE_URL")


# -----------------
# Get Intent data
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
        
