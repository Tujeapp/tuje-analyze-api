from fastapi import APIRouter, HTTPException
import asyncpg
import os

router = APIRouter()
DATABASE_URL = os.getenv("DATABASE_URL")

@router.get("/subtopics")
async def get_subtopics():
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, name_fr
                FROM brain_subtopic
                WHERE live = TRUE
                ORDER BY name_fr ASC
            """)
            return {
                "success": True,
                "subtopics": [dict(row) for row in rows]
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await pool.close()

@router.get("/subtopics/{subtopic_id}/interactions")
async def get_interactions_by_subtopic(subtopic_id: str):
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, transcription_fr, video_url
                FROM brain_interaction
                WHERE live = TRUE
                AND subtopic_id = $1
                ORDER BY id ASC
            """, subtopic_id)
            return {
                "success": True,
                "interactions": [dict(row) for row in rows]
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await pool.close()
