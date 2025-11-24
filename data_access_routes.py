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
# NEW ENDPOINTS: Subtopic
# ========================================

@router.get("/subtopics-detailed")
async def get_subtopics_detailed():
    """Get all subtopics with descriptions and boredom scores"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        rows = await conn.fetch("""
            SELECT 
                id, 
                name_fr, 
                name_en, 
                description_fr, 
                description_en, 
                boredom
            FROM brain_subtopic
            WHERE live = TRUE
            ORDER BY boredom ASC, name_fr ASC
        """)
        
        await conn.close()
        
        return {
            "count": len(rows),
            "subtopics": [
                {
                    "id": row["id"],
                    "name_fr": row["name_fr"],
                    "name_en": row["name_en"],
                    "description_fr": row["description_fr"],
                    "description_en": row["description_en"],
                    "boredom": float(row["boredom"])
                }
                for row in rows
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/subtopics-low-boredom")
async def get_low_boredom_subtopics(max_boredom: float = 0.5):
    """Get subtopics with low boredom score"""
    try:
        if max_boredom < 0 or max_boredom > 1:
            raise HTTPException(
                status_code=400,
                detail="max_boredom must be between 0 and 1"
            )
        
        conn = await asyncpg.connect(DATABASE_URL)
        
        rows = await conn.fetch("""
            SELECT 
                id, 
                name_fr, 
                name_en, 
                description_fr, 
                description_en, 
                boredom
            FROM brain_subtopic
            WHERE live = TRUE 
              AND boredom <= $1
            ORDER BY boredom ASC
        """, max_boredom)
        
        await conn.close()
        
        return {
            "max_boredom": max_boredom,
            "count": len(rows),
            "subtopics": [
                {
                    "id": row["id"],
                    "name_fr": row["name_fr"],
                    "name_en": row["name_en"],
                    "description_fr": row["description_fr"],
                    "description_en": row["description_en"],
                    "boredom": float(row["boredom"])
                }
                for row in rows
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/subtopic-statistics")
async def get_subtopic_statistics():
    """Get statistics about subtopic boredom scores"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) as total_subtopics,
                ROUND(AVG(boredom)::numeric, 2) as avg_boredom,
                MIN(boredom) as min_boredom,
                MAX(boredom) as max_boredom,
                COUNT(*) FILTER (WHERE boredom <= 0.3) as low_boredom_count,
                COUNT(*) FILTER (WHERE boredom > 0.3 AND boredom <= 0.7) as medium_boredom_count,
                COUNT(*) FILTER (WHERE boredom > 0.7) as high_boredom_count
            FROM brain_subtopic
            WHERE live = TRUE
        """)
        
        await conn.close()
        
        return {
            "total_subtopics": stats["total_subtopics"],
            "boredom_statistics": {
                "average": float(stats["avg_boredom"]) if stats["avg_boredom"] else 0,
                "min": float(stats["min_boredom"]) if stats["min_boredom"] else 0,
                "max": float(stats["max_boredom"]) if stats["max_boredom"] else 0
            },
            "boredom_distribution": {
                "low": stats["low_boredom_count"],       # 0.0 - 0.3
                "medium": stats["medium_boredom_count"],  # 0.3 - 0.7
                "high": stats["high_boredom_count"]       # 0.7 - 1.0
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ========================================
# NEW ENDPOINTS: Interests
# ========================================

@router.get("/interests")
async def get_interests():
    """Get all interests with their linked subtopics"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        rows = await conn.fetch("""
            SELECT 
                i.id,
                i.name,
                i.subtopic_ids,
                array_agg(s.name_fr) FILTER (WHERE s.id IS NOT NULL) as subtopic_names_fr,
                array_agg(s.name_en) FILTER (WHERE s.id IS NOT NULL) as subtopic_names_en
            FROM brain_interest i
            LEFT JOIN brain_subtopic s ON s.id = ANY(i.subtopic_ids) AND s.live = TRUE
            WHERE i.live = TRUE
            GROUP BY i.id, i.name, i.subtopic_ids
            ORDER BY i.name ASC
        """)
        
        await conn.close()
        
        return {
            "count": len(rows),
            "interests": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "subtopic_ids": row["subtopic_ids"],
                    "subtopic_count": len(row["subtopic_ids"]) if row["subtopic_ids"] else 0,
                    "subtopics": {
                        "names_fr": row["subtopic_names_fr"] if row["subtopic_names_fr"] else [],
                        "names_en": row["subtopic_names_en"] if row["subtopic_names_en"] else []
                    }
                }
                for row in rows
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/interest/{interest_id}")
async def get_interest_by_id(interest_id: str):
    """Get a specific interest with detailed subtopic information"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Get interest
        interest = await conn.fetchrow("""
            SELECT id, name, subtopic_ids
            FROM brain_interest
            WHERE id = $1 AND live = TRUE
        """, interest_id)
        
        if not interest:
            await conn.close()
            raise HTTPException(
                status_code=404,
                detail=f"Interest '{interest_id}' not found"
            )
        
        # Get detailed subtopic info
        subtopics = await conn.fetch("""
            SELECT 
                id,
                name_fr,
                name_en,
                description_fr,
                description_en,
                boredom
            FROM brain_subtopic
            WHERE id = ANY($1) AND live = TRUE
            ORDER BY name_fr ASC
        """, interest["subtopic_ids"])
        
        await conn.close()
        
        return {
            "id": interest["id"],
            "name": interest["name"],
            "subtopic_count": len(subtopics),
            "subtopics": [
                {
                    "id": row["id"],
                    "name_fr": row["name_fr"],
                    "name_en": row["name_en"],
                    "description_fr": row["description_fr"],
                    "description_en": row["description_en"],
                    "boredom": float(row["boredom"])
                }
                for row in subtopics
            ]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/interests-by-subtopic/{subtopic_id}")
async def get_interests_by_subtopic(subtopic_id: str):
    """Get all interests that include a specific subtopic"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        rows = await conn.fetch("""
            SELECT id, name, subtopic_ids
            FROM brain_interest
            WHERE live = TRUE 
              AND $1 = ANY(subtopic_ids)
            ORDER BY name ASC
        """, subtopic_id)
        
        await conn.close()
        
        return {
            "subtopic_id": subtopic_id,
            "count": len(rows),
            "interests": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "total_subtopics": len(row["subtopic_ids"]) if row["subtopic_ids"] else 0
                }
                for row in rows
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/interest-statistics")
async def get_interest_statistics():
    """Get statistics about interests and their subtopic coverage"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) as total_interests,
                ROUND(AVG(array_length(subtopic_ids, 1))::numeric, 1) as avg_subtopics_per_interest,
                MIN(array_length(subtopic_ids, 1)) as min_subtopics,
                MAX(array_length(subtopic_ids, 1)) as max_subtopics
            FROM brain_interest
            WHERE live = TRUE
        """)
        
        # Top interests by subtopic count
        top_interests = await conn.fetch("""
            SELECT 
                id,
                name,
                array_length(subtopic_ids, 1) as subtopic_count
            FROM brain_interest
            WHERE live = TRUE
            ORDER BY subtopic_count DESC
            LIMIT 10
        """)
        
        await conn.close()
        
        return {
            "total_interests": stats["total_interests"],
            "subtopic_coverage": {
                "average_per_interest": float(stats["avg_subtopics_per_interest"]) if stats["avg_subtopics_per_interest"] else 0,
                "min": stats["min_subtopics"],
                "max": stats["max_subtopics"]
            },
            "top_interests_by_coverage": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "subtopic_count": row["subtopic_count"]
                }
                for row in top_interests
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ========================================
# UPDATED: Interaction Endpoints with New Fields
# ========================================

@router.get("/interactions-detailed/{interaction_id}")
async def get_interaction_detailed(interaction_id: str):
    """Get detailed interaction with all relationships"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Get interaction
        interaction = await conn.fetchrow("""
            SELECT 
                i.id,
                i.transcription_fr,
                i.transcription_en,
                i.subtopic_id,
                i.interaction_optimum_level,
                i.boredom,
                i.intents,
                i.expected_entities_id,
                i.expected_vocab_id,
                i.expected_notion_id,
                i.interaction_vocab_id,
                i.hint_ids,
                i.interaction_type_id,
                s.name_fr as subtopic_name,
                it.name as interaction_type_name
            FROM brain_interaction i
            LEFT JOIN brain_subtopic s ON i.subtopic_id = s.id
            LEFT JOIN brain_interaction_type it ON i.interaction_type_id = it.id
            WHERE i.id = $1 AND i.live = TRUE
        """, interaction_id)
        
        if not interaction:
            await conn.close()
            raise HTTPException(
                status_code=404,
                detail=f"Interaction '{interaction_id}' not found"
            )
        
        # Get hints
        hints = []
        if interaction["hint_ids"]:
            hints = await conn.fetch("""
                SELECT id, name, value, description
                FROM brain_hint
                WHERE id = ANY($1) AND live = TRUE
            """, interaction["hint_ids"])
        
        await conn.close()
        
        return {
            "id": interaction["id"],
            "transcription": {
                "fr": interaction["transcription_fr"],
                "en": interaction["transcription_en"]
            },
            "subtopic": {
                "id": interaction["subtopic_id"],
                "name": interaction["subtopic_name"]
            } if interaction["subtopic_id"] else None,
            "interaction_type": {
                "id": interaction["interaction_type_id"],
                "name": interaction["interaction_type_name"]
            } if interaction["interaction_type_id"] else None,
            "metrics": {
                "optimum_level": float(interaction["interaction_optimum_level"]) if interaction["interaction_optimum_level"] else None,
                "boredom": float(interaction["boredom"]) if interaction["boredom"] else None
            },
            "hints": [
                {
                    "id": h["id"],
                    "name": h["name"],
                    "value": h["value"],
                    "description": h["description"]
                }
                for h in hints
            ],
            "relationships": {
                "intent_count": len(interaction["intents"]) if interaction["intents"] else 0,
                "expected_entities_count": len(interaction["expected_entities_id"]) if interaction["expected_entities_id"] else 0,
                "expected_vocab_count": len(interaction["expected_vocab_id"]) if interaction["expected_vocab_id"] else 0,
                "expected_notion_count": len(interaction["expected_notion_id"]) if interaction["expected_notion_id"] else 0,
                "interaction_vocab_count": len(interaction["interaction_vocab_id"]) if interaction["interaction_vocab_id"] else 0,
                "hint_count": len(hints)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/interactions-by-type/{type_id}")
async def get_interactions_by_type(type_id: str):
    """Get all interactions of a specific type"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        rows = await conn.fetch("""
            SELECT 
                i.id,
                i.transcription_fr,
                i.boredom,
                i.interaction_optimum_level,
                s.name_fr as subtopic_name
            FROM brain_interaction i
            LEFT JOIN brain_subtopic s ON i.subtopic_id = s.id
            WHERE i.interaction_type_id = $1 AND i.live = TRUE
            ORDER BY i.boredom ASC
        """, type_id)
        
        await conn.close()
        
        return {
            "type_id": type_id,
            "count": len(rows),
            "interactions": [
                {
                    "id": row["id"],
                    "transcription_fr": row["transcription_fr"],
                    "subtopic": row["subtopic_name"],
                    "boredom": float(row["boredom"]) if row["boredom"] else None,
                    "optimum_level": float(row["interaction_optimum_level"]) if row["interaction_optimum_level"] else None
                }
                for row in rows
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/interactions-by-hint/{hint_id}")
async def get_interactions_by_hint(hint_id: str):
    """Get all interactions that use a specific hint"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        rows = await conn.fetch("""
            SELECT 
                id,
                transcription_fr,
                boredom,
                interaction_optimum_level
            FROM brain_interaction
            WHERE live = TRUE 
              AND $1 = ANY(hint_ids)
            ORDER BY boredom ASC
        """, hint_id)
        
        await conn.close()
        
        return {
            "hint_id": hint_id,
            "count": len(rows),
            "interactions": [
                {
                    "id": row["id"],
                    "transcription_fr": row["transcription_fr"],
                    "boredom": float(row["boredom"]) if row["boredom"] else None,
                    "optimum_level": float(row["interaction_optimum_level"]) if row["interaction_optimum_level"] else None
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

@router.get("/answers-by-interaction/{interaction_id}")
async def get_answers_by_interaction(interaction_id: str):
    """
    Get all answers linked to a specific interaction
    
    This endpoint fetches answers from brain_interaction_answer table
    and joins with brain_answer to get the answer details.
    
    Returns 2-4 answers for multiple choice interactions.
    """
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Get answers linked to this interaction through brain_interaction_answer
        rows = await conn.fetch("""
            SELECT 
                a.id,
                a.transcription_fr,
                a.transcription_en,
                a.transcription_adjusted,
                a.answer_optimum_level,
                ia.interaction_id
            FROM brain_interaction_answer ia
            JOIN brain_answer a ON ia.answer_id = a.id
            WHERE ia.interaction_id = $1 
              AND a.live = TRUE
            ORDER BY a.created_at ASC
            LIMIT 4
        """, interaction_id)
        
        await conn.close()
        
        if not rows:
            return {
                "interaction_id": interaction_id,
                "count": 0,
                "answers": []
            }
        
        answers = [
            {
                "id": row["id"],
                "transcription_fr": row["transcription_fr"],
                "transcription_en": row["transcription_en"],
                "transcription_adjusted": row["transcription_adjusted"],
                "answer_optimum_level": float(row["answer_optimum_level"]) if row["answer_optimum_level"] else None
            }
            for row in rows
        ]
        
        return {
            "interaction_id": interaction_id,
            "count": len(answers),
            "answers": answers
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
