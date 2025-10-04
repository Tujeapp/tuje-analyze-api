import asyncpg
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
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


# ========================================
# NEW ENDPOINTS: Bonus/Malus
# ========================================

@router.get("/bonus-malus-for-level/{user_level}")
async def get_bonus_malus_for_level(user_level: int):
    """Get applicable bonus/malus entries for a user's level"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch("""
            SELECT id, name_fr, name_en, description, level_from, level_to
            FROM brain_bonus_malus
            WHERE live = TRUE 
              AND level_from <= $1 
              AND level_to >= $1
            ORDER BY name_fr ASC
        """, user_level)
        await conn.close()

        return {
            "user_level": user_level,
            "applicable_bonuses": [
                {
                    "id": row["id"],
                    "name_fr": row["name_fr"],
                    "name_en": row["name_en"],
                    "description": row["description"],
                    "level_range": f"{row['level_from']}-{row['level_to']}"
                }
                for row in rows
            ]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bonus-malus-validation-check")
async def bonus_malus_validation_check():
    """Check for any invalid level ranges in bonus_malus table"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Check for invalid ranges
        invalid_ranges = await conn.fetch("""
            SELECT id, name_fr, level_from, level_to
            FROM brain_bonus_malus
            WHERE level_to < level_from
        """)
        
        # Check for overlapping ranges (optional)
        overlaps = await conn.fetch("""
            SELECT b1.id as id1, b1.name_fr as name1, 
                   b2.id as id2, b2.name_fr as name2,
                   b1.level_from, b1.level_to,
                   b2.level_from, b2.level_to
            FROM brain_bonus_malus b1
            JOIN brain_bonus_malus b2 ON b1.id < b2.id
            WHERE b1.live = TRUE AND b2.live = TRUE
              AND (
                (b1.level_from BETWEEN b2.level_from AND b2.level_to)
                OR (b1.level_to BETWEEN b2.level_from AND b2.level_to)
                OR (b2.level_from BETWEEN b1.level_from AND b1.level_to)
                OR (b2.level_to BETWEEN b1.level_from AND b1.level_to)
              )
        """)
        
        await conn.close()

        return {
            "status": "ok" if len(invalid_ranges) == 0 else "issues_found",
            "invalid_ranges": [
                {
                    "id": row["id"],
                    "name": row["name_fr"],
                    "level_from": row["level_from"],
                    "level_to": row["level_to"]
                }
                for row in invalid_ranges
            ],
            "overlapping_ranges": [
                {
                    "bonus1": {"id": row["id1"], "name": row["name1"]},
                    "bonus2": {"id": row["id2"], "name": row["name2"]}
                }
                for row in overlaps
            ]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========================================
# NEW ENDPOINTS: Hints
# ========================================

@router.get("/hints-for-level/{user_level}")
async def get_hints_for_level(user_level: int):
    """Get applicable hints for a user's level"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch("""
            SELECT id, name, value, description, level_from, level_to
            FROM brain_hint
            WHERE live = TRUE 
              AND level_from <= $1 
              AND level_to >= $1
            ORDER BY name ASC
        """, user_level)
        await conn.close()

        return {
            "user_level": user_level,
            "hints": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "value": row["value"],
                    "description": row["description"],
                    "level_range": f"{row['level_from']}-{row['level_to']}"
                }
                for row in rows
            ]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hints-search")
async def search_hints(keyword: str, user_level: Optional[int] = None):
    """Search hints by keyword in name, value, or description"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        if user_level:
            rows = await conn.fetch("""
                SELECT id, name, value, description, level_from, level_to
                FROM brain_hint
                WHERE live = TRUE 
                  AND level_from <= $2 
                  AND level_to >= $2
                  AND (
                    LOWER(name) LIKE LOWER($1)
                    OR LOWER(CAST(value AS TEXT)) LIKE LOWER($1)
                    OR LOWER(description) LIKE LOWER($1)
                  )
                ORDER BY name ASC
            """, f"%{keyword}%", user_level)
        else:
            rows = await conn.fetch("""
                SELECT id, name, value, description, level_from, level_to
                FROM brain_hint
                WHERE live = TRUE 
                  AND (
                    LOWER(name) LIKE LOWER($1)
                    OR LOWER(CAST(value AS TEXT)) LIKE LOWER($1)
                    OR LOWER(description) LIKE LOWER($1)
                  )
                ORDER BY name ASC
            """, f"%{keyword}%")
        
        await conn.close()

        return {
            "keyword": keyword,
            "user_level": user_level,
            "results_count": len(rows),
            "hints": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "value": row["value"],
                    "description": row["description"],
                    "level_range": f"{row['level_from']}-{row['level_to']}"
                }
                for row in rows
            ]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========================================
# NEW ENDPOINTS: Interaction Types
# ========================================

@router.get("/interaction-types-by-mood/{mood}")
async def get_interaction_types_by_mood(mood: str):
    """Get interaction types that are compatible with a specific session mood"""
    try:
        # Validate mood
        allowed_moods = ['effective', 'playful', 'cultural', 'relax', 'listening']
        if mood.lower() not in allowed_moods:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid mood. Must be one of: {', '.join(allowed_moods)}"
            )
        
        conn = await asyncpg.connect(DATABASE_URL)
        
        # ✅ Query using array containment operator
        rows = await conn.fetch("""
            SELECT 
                it.id, 
                it.name, 
                it.boredom, 
                it.description,
                it.session_mood_ids,
                array_agg(sm.name) as mood_names
            FROM brain_interaction_type it
            JOIN brain_session_mood sm ON sm.id = ANY(it.session_mood_ids)
            WHERE it.live = TRUE 
              AND sm.live = TRUE
              AND EXISTS (
                  SELECT 1 FROM brain_session_mood sm2
                  WHERE sm2.id = ANY(it.session_mood_ids)
                  AND LOWER(sm2.name) = LOWER($1)
              )
            GROUP BY it.id, it.name, it.boredom, it.description, it.session_mood_ids
            ORDER BY it.boredom ASC
        """, mood.lower())
        await conn.close()

        return {
            "mood": mood,
            "count": len(rows),
            "types": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "boredom": float(row["boredom"]),
                    "description": row["description"],
                    "compatible_moods": row["mood_names"]  # Shows all moods this type works with
                }
                for row in rows
            ]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/interaction-types-low-boredom")
async def get_low_boredom_types(max_boredom: float = 0.5, session_mood: str = None):
    """Get interaction types with low boredom, optionally filtered by session mood"""
    try:
        if max_boredom < 0 or max_boredom > 1:
            raise HTTPException(
                status_code=400,
                detail="max_boredom must be between 0 and 1"
            )
        
        conn = await asyncpg.connect(DATABASE_URL)
        
        if session_mood:
            # Filter by specific mood
            rows = await conn.fetch("""
                SELECT 
                    it.id, 
                    it.name, 
                    it.boredom, 
                    it.description,
                    array_agg(sm.name) as mood_names
                FROM brain_interaction_type it
                JOIN brain_session_mood sm ON sm.id = ANY(it.session_mood_ids)
                WHERE it.live = TRUE 
                  AND sm.live = TRUE
                  AND it.boredom <= $1
                  AND EXISTS (
                      SELECT 1 FROM brain_session_mood sm2
                      WHERE sm2.id = ANY(it.session_mood_ids)
                      AND LOWER(sm2.name) = LOWER($2)
                  )
                GROUP BY it.id, it.name, it.boredom, it.description
                ORDER BY it.boredom ASC
            """, max_boredom, session_mood.lower())
        else:
            # No mood filter
            rows = await conn.fetch("""
                SELECT 
                    it.id, 
                    it.name, 
                    it.boredom, 
                    it.description,
                    array_agg(sm.name) as mood_names
                FROM brain_interaction_type it
                JOIN brain_session_mood sm ON sm.id = ANY(it.session_mood_ids)
                WHERE it.live = TRUE 
                  AND sm.live = TRUE
                  AND it.boredom <= $1
                GROUP BY it.id, it.name, it.boredom, it.description
                ORDER BY it.boredom ASC
            """, max_boredom)
        
        await conn.close()

        return {
            "max_boredom": max_boredom,
            "session_mood_filter": session_mood,
            "count": len(rows),
            "types": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "boredom": float(row["boredom"]),
                    "description": row["description"],
                    "compatible_moods": row["mood_names"]
                }
                for row in rows
            ]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/interaction-type-stats")
async def get_interaction_type_statistics():
    """Get statistics about interaction types and their mood compatibility"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Count types by mood (types can appear in multiple moods)
        mood_stats = await conn.fetch("""
            SELECT 
                sm.name as session_mood_name,
                COUNT(DISTINCT it.id) as type_count,
                ROUND(AVG(it.boredom)::numeric, 2) as avg_boredom,
                MIN(it.boredom) as min_boredom,
                MAX(it.boredom) as max_boredom
            FROM brain_interaction_type it
            JOIN brain_session_mood sm ON sm.id = ANY(it.session_mood_ids)
            WHERE it.live = TRUE AND sm.live = TRUE
            GROUP BY sm.name
            ORDER BY type_count DESC
        """)
        
        # Overall stats
        overall = await conn.fetchrow("""
            SELECT 
                COUNT(*) as total_types,
                ROUND(AVG(boredom)::numeric, 2) as avg_boredom,
                MIN(boredom) as min_boredom,
                MAX(boredom) as max_boredom,
                ROUND(AVG(array_length(session_mood_ids, 1))::numeric, 1) as avg_moods_per_type
            FROM brain_interaction_type
            WHERE live = TRUE
        """)
        
        await conn.close()

        return {
            "overall": {
                "total_types": overall["total_types"],
                "average_boredom": float(overall["avg_boredom"]) if overall["avg_boredom"] else 0,
                "average_moods_per_type": float(overall["avg_moods_per_type"]) if overall["avg_moods_per_type"] else 0,
                "boredom_range": {
                    "min": float(overall["min_boredom"]) if overall["min_boredom"] else 0,
                    "max": float(overall["max_boredom"]) if overall["max_boredom"] else 0
                }
            },
            "by_mood": [
                {
                    "mood": row["session_mood_name"],
                    "compatible_type_count": row["type_count"],
                    "avg_boredom": float(row["avg_boredom"]),
                    "boredom_range": {
                        "min": float(row["min_boredom"]),
                        "max": float(row["max_boredom"])
                    }
                }
                for row in mood_stats
            ]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========================================
# NEW ENDPOINTS: Combinations
# ========================================

@router.get("/combinations-by-status")
async def get_combinations_by_status(
    subtopic: Optional[str] = None,
    transcription: Optional[str] = None,
    intent: Optional[str] = None
):
    """Get combinations filtered by status fields"""
    try:
        # Validate inputs
        allowed_values = ['seen', 'new']
        filters = []
        params = []
        param_count = 0
        
        if subtopic:
            if subtopic.lower() not in allowed_values:
                raise HTTPException(status_code=400, detail=f"Invalid subtopic value")
            param_count += 1
            filters.append(f"subtopic = ${param_count}")
            params.append(subtopic.lower())
        
        if transcription:
            if transcription.lower() not in allowed_values:
                raise HTTPException(status_code=400, detail=f"Invalid transcription value")
            param_count += 1
            filters.append(f"transcription = ${param_count}")
            params.append(transcription.lower())
        
        if intent:
            if intent.lower() not in allowed_values:
                raise HTTPException(status_code=400, detail=f"Invalid intent value")
            param_count += 1
            filters.append(f"intent = ${param_count}")
            params.append(intent.lower())
        
        where_clause = " AND ".join(filters) if filters else "TRUE"
        
        conn = await asyncpg.connect(DATABASE_URL)
        query = f"""
            SELECT id, name, boredom, subtopic, transcription, intent
            FROM brain_combination
            WHERE live = TRUE AND {where_clause}
            ORDER BY name ASC
        """
        rows = await conn.fetch(query, *params)
        await conn.close()

        return {
            "filters": {
                "subtopic": subtopic,
                "transcription": transcription,
                "intent": intent
            },
            "count": len(rows),
            "combinations": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "boredom": float(row["boredom"]),
                    "subtopic": row["subtopic"],
                    "transcription": row["transcription"],
                    "intent": row["intent"]
                }
                for row in rows
            ]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/combination-statistics")
async def get_combination_statistics():
    """Get statistics about combination statuses and boredom"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        stats = await conn.fetch("""
            SELECT 
                subtopic,
                transcription,
                intent,
                COUNT(*) as count,
                ROUND(AVG(boredom)::numeric, 2) as avg_boredom,
                MIN(boredom) as min_boredom,
                MAX(boredom) as max_boredom
            FROM brain_combination
            WHERE live = TRUE
            GROUP BY subtopic, transcription, intent
            ORDER BY count DESC
        """)
        
        # Overall stats
        overall = await conn.fetchrow("""
            SELECT 
                COUNT(*) as total,
                ROUND(AVG(boredom)::numeric, 2) as avg_boredom,
                MIN(boredom) as min_boredom,
                MAX(boredom) as max_boredom,
                COUNT(*) FILTER (WHERE subtopic = 'seen') as subtopic_seen,
                COUNT(*) FILTER (WHERE subtopic = 'new') as subtopic_new,
                COUNT(*) FILTER (WHERE transcription = 'seen') as transcription_seen,
                COUNT(*) FILTER (WHERE transcription = 'new') as transcription_new,
                COUNT(*) FILTER (WHERE intent = 'seen') as intent_seen,
                COUNT(*) FILTER (WHERE intent = 'new') as intent_new
            FROM brain_combination
            WHERE live = TRUE
        """)
        
        await conn.close()

        return {
            "total_combinations": overall["total"],
            "overall_boredom": {
                "average": float(overall["avg_boredom"]) if overall["avg_boredom"] else 0,
                "min": float(overall["min_boredom"]) if overall["min_boredom"] else 0,
                "max": float(overall["max_boredom"]) if overall["max_boredom"] else 0
            },
            "by_field": {
                "subtopic": {
                    "seen": overall["subtopic_seen"],
                    "new": overall["subtopic_new"]
                },
                "transcription": {
                    "seen": overall["transcription_seen"],
                    "new": overall["transcription_new"]
                },
                "intent": {
                    "seen": overall["intent_seen"],
                    "new": overall["intent_new"]
                }
            },
            "combinations": [
                {
                    "status": {
                        "subtopic": row["subtopic"],
                        "transcription": row["transcription"],
                        "intent": row["intent"]
                    },
                    "count": row["count"],
                    "boredom": {
                        "average": float(row["avg_boredom"]),
                        "min": float(row["min_boredom"]),
                        "max": float(row["max_boredom"])
                    }
                }
                for row in stats
            ]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========================================
# NEW ENDPOINTS: Notions (with weightiness)
# ========================================

@router.get("/notions-by-weightiness")
async def get_notions_by_weightiness(
    min_weightiness: float = 0.0,
    max_weightiness: float = 1.0
):
    """Get notions filtered by weightiness range"""
    try:
        if min_weightiness < 0 or min_weightiness > 1:
            raise HTTPException(status_code=400, detail="min_weightiness must be between 0 and 1")
        if max_weightiness < 0 or max_weightiness > 1:
            raise HTTPException(status_code=400, detail="max_weightiness must be between 0 and 1")
        if min_weightiness > max_weightiness:
            raise HTTPException(status_code=400, detail="min_weightiness cannot be greater than max_weightiness")
        
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch("""
            SELECT id, name_fr, name_en, description, weightiness, score, rank
            FROM brain_notion
            WHERE live = TRUE 
              AND weightiness >= $1 
              AND weightiness <= $2
            ORDER BY weightiness DESC, rank ASC
        """, min_weightiness, max_weightiness)
        await conn.close()

        return {
            "weightiness_range": {
                "min": min_weightiness,
                "max": max_weightiness
            },
            "count": len(rows),
            "notions": [
                {
                    "id": row["id"],
                    "name_fr": row["name_fr"],
                    "name_en": row["name_en"],
                    "description": row["description"],
                    "weightiness": float(row["weightiness"]),
                    "score": float(row["score"]),
                    "rank": row["rank"]
                }
                for row in rows
            ]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========================================
# NEW ENDPOINTS: Session Moods
# ========================================

@router.get("/session-moods")
async def get_session_moods():
    """Get all available session moods"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch("""
            SELECT id, name, description
            FROM brain_session_mood
            WHERE live = TRUE
            ORDER BY name ASC
        """)
        await conn.close()

        return {
            "count": len(rows),
            "session_moods": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "description": row["description"]
                }
                for row in rows
            ]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session-mood/{mood_name}")
async def get_session_mood_by_name(mood_name: str):
    """Get a specific session mood by name"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        row = await conn.fetchrow("""
            SELECT id, name, description
            FROM brain_session_mood
            WHERE LOWER(name) = LOWER($1) AND live = TRUE
        """, mood_name)
        await conn.close()

        if not row:
            raise HTTPException(
                status_code=404, 
                detail=f"Session mood '{mood_name}' not found"
            )

        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"]
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
