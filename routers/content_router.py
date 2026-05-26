from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response
from pydantic import BaseModel
from typing import List
import asyncpg
import os

from user_routes import get_current_user

router = APIRouter()
DATABASE_URL = os.getenv("DATABASE_URL")


# ─────────────────────────────────────────
# Response models
# ─────────────────────────────────────────

class Goal(BaseModel):
    id: str
    label: str


class GoalsResponse(BaseModel):
    success: bool
    goals: List[Goal]

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


@router.get("/goals", response_model=GoalsResponse)
async def get_goals(
    response: Response,
    current_user: dict = Depends(get_current_user),
):
    """Return all live goals for the onboarding goal-picker screen.

    Requires a valid JWT (anonymous or permanent). Called early in onboarding
    before the user has set a goal, so anonymous tokens must be accepted.

    Results are stable-sorted by name then id as a deterministic tiebreaker.
    A sort_order column and locale-aware labels are planned for a later stage.

    Cache-Control: public, max-age=3600 — safe because goals change only via
    Airtable sync, not per-user. Clients and CDN can cache for 1 hour.
    """
    response.headers["Cache-Control"] = "public, max-age=3600"

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, name
                FROM brain_interest
                WHERE live = TRUE
                ORDER BY name ASC, id ASC
            """)
            return GoalsResponse(
                success=True,
                goals=[Goal(id=row["id"], label=row["name"]) for row in rows],
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await pool.close()
