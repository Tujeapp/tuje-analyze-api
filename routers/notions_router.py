from fastapi import APIRouter, HTTPException
import asyncpg
import os

router = APIRouter()
DATABASE_URL = os.getenv("DATABASE_URL")

@router.get("/notions")
async def get_notions():
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, name_fr, name_en, description
                FROM brain_notion
                WHERE live = TRUE
                ORDER BY rank ASC NULLS LAST
            """)
            return {
                "success": True,
                "notions": [dict(row) for row in rows]
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await pool.close()
