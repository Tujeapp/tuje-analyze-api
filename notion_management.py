# ============================================================================
# notion_management.py - Notion Rate Management for Session Start
# ============================================================================
# This module handles notion rate updates at session start
# Based on "Logic of a Session" documentation - Steps G, H, I, J
# ============================================================================

import asyncpg
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


# ============================================================================
# G. UPDATE NOTION RATES ON SESSION START (Decay Formula)
# ============================================================================

async def update_notion_rates_on_session_start(
    user_id: str,
    streak7: float,
    streak30: float,
    session_mood: str,
    db_pool: asyncpg.Pool
) -> int:
    """
    Carry forward notion rates at session start (NULL-marker model).

    Reads the previous session's carryable rows (0 < rate < 1), applies the decay
    formula, and INSERTs NEW session_notion rows for the about-to-start session with
    session_id = NULL (backfilled at cycle 1). Old rows are left untouched (history).
    Carries notion_id + notion_introduction_date forward; resets per-session mentioned
    counts to 0. "Previous session" = the user's completed session with the highest
    session_rank. First regular session (no previous completed session) returns 0.

    Formula: new_rate = last_rate - (last_rate × (coefficient_A + coefficient_B))

    Args:
        user_id: User ID
        streak7: 7-day streak rate
        streak30: 30-day streak rate
        session_mood: Selected session mood
        db_pool: Database connection pool

    Returns:
        Number of carry-forward rows created
    """
    async with db_pool.acquire() as conn:
        # Find the previous session = highest session_rank, completed.
        # Select its id (to match its rows) + the data Coefficient A needs.
        last_session = await conn.fetchrow("""
            SELECT
                id,
                session_level_direction,
                session_score,
                session_nbr_cycle,
                completed_at
            FROM session
            WHERE user_id = $1
            AND status = 'completed'
            ORDER BY session_rank DESC
            LIMIT 1
        """, user_id)

        if not last_session:
            logger.info(f"No completed session for user {user_id}; skipping notion carry-forward (first regular session).")
            return 0

        # Read the PREVIOUS session's carryable rows (0 < rate < 1).
        notions = await conn.fetch("""
            SELECT
                sn.notion_id,
                sn.notion_rate,
                sn.notion_introduction_date,
                sn.notion_passive_rate,
                sn.notion_active_rate,
                bn.weightiness
            FROM session_notion sn
            JOIN brain_notion bn ON sn.notion_id = bn.id
            WHERE sn.user_id = $1
            AND sn.session_id = $2
            AND sn.notion_rate > 0
            AND sn.notion_rate < 1
        """, user_id, last_session['id'])

        if not notions:
            logger.info(f"No carryable notions (0<rate<1) in previous session for user {user_id}; nothing to carry forward.")
            return 0

        # Coefficient A (same for all notions this session).
        coef_a = _calculate_coefficient_a(
            streak30=streak30,
            streak7=streak7,
            session_mood=session_mood,
            last_level_direction=last_session['session_level_direction'],
            last_session_rate=last_session['session_score'] / (last_session['session_nbr_cycle'] * 700) if last_session['session_nbr_cycle'] else 0,
            last_session_date=last_session['completed_at']
        )

        created_count = 0
        now = datetime.now()

        for notion in notions:
            coef_b = _calculate_coefficient_b(
                notion_introduction_date=notion['notion_introduction_date'],
                notion_passive_rate=float(notion['notion_passive_rate'] or 0),
                notion_active_rate=float(notion['notion_active_rate'] or 0),
                notion_weightiness=float(notion['weightiness'] or 0.5),
                current_time=now
            )

            last_rate = float(notion['notion_rate'])
            decay_factor = last_rate * (coef_a + coef_b)
            new_rate = round(max(0.01, min(0.99, last_rate - decay_factor)), 2)

            # INSERT a NEW row for the about-to-start session (session_id NULL,
            # backfilled at cycle 1). Carry forward notion_id + introduction_date;
            # reset the per-session mentioned counts to 0.
            await conn.execute("""
                INSERT INTO session_notion (
                    user_id, notion_id, session_id, notion_rate,
                    notion_introduction_date,
                    notion_passive_mentioned, notion_active_mentioned,
                    created_at, updated_at
                )
                VALUES ($1, $2, NULL, $3, $4, 0, 0, NOW(), NOW())
            """, user_id, notion['notion_id'], new_rate, notion['notion_introduction_date'])

            created_count += 1
            logger.debug(f"Carry-forward notion {notion['notion_id']}: {last_rate:.2f} -> {new_rate:.2f} (new NULL-session row)")

        logger.info(f"Carried forward {created_count} notions as new rows (session_id NULL) for user {user_id}.")
        return created_count


def _calculate_coefficient_a(
    streak30: float,
    streak7: float,
    session_mood: str,
    last_level_direction: str,
    last_session_rate: float,
    last_session_date: datetime
) -> float:
    """
    Calculate Coefficient A (same for all notions)
    
    Documentation: SUM of all sub-coefficients:
    - Data 1: streak30 impact
    - Data 2: streak7 impact
    - Data 3: session mood impact
    - Data 4: last session level direction
    - Data 5: last session rate
    - Data 6: days since last session
    """
    total = 0.0
    
    # Data 1: streak30
    # Formula: ((streak30 - 0.4) / 0.1) * 0.05
    if streak30 > 0.4:
        data1 = ((streak30 - 0.4) / 0.1) * 0.05
        total += round(data1, 2)
    
    # Data 2: streak7
    # Formula: ((streak7 - 0.2) / 0.1) * 0.05
    if streak7 > 0.2:
        data2 = ((streak7 - 0.2) / 0.1) * 0.05
        total += round(data2, 2)
    
    # Data 3: session mood
    mood_values = {
        "effective": -0.1,  # Negative = less decay
        "cultural": 0.1,
        "listening": 0.1,
        "relax": 0.0,
        "playful": 0.0
    }
    total += mood_values.get(session_mood.lower(), 0.0)
    
    # Data 4: last session level direction
    direction_values = {"up": 0.0, "stable": 0.05, "down": 0.1}
    total += direction_values.get((last_level_direction or "stable").lower(), 0.05)
    
    # Data 5: last session rate
    if last_session_rate <= 0.6:
        total += 0.1
    elif last_session_rate > 0.8:
        total += 0.0
    else:
        total += 0.05
    
    # Data 6: days since last session
    if last_session_date:
        days_since = (datetime.now() - last_session_date).total_seconds() / 86400
        if days_since <= 1:
            total += 0.0
        elif days_since > 3:
            total += 0.1
        else:
            total += 0.05
    
    return round(total, 2)


def _calculate_coefficient_b(
    notion_introduction_date: datetime,
    notion_passive_rate: float,
    notion_active_rate: float,
    notion_weightiness: float,
    current_time: datetime
) -> float:
    """
    Calculate Coefficient B (specific to each notion)
    
    Documentation: SUM of all sub-coefficients:
    - Data 1: notion introduction date age
    - Data 2: notion passive rate
    - Data 3: notion active rate
    - Data 4: notion weightiness
    """
    total = 0.0
    
    # Data 1: notion introduction date
    # Days since introduction impacts decay
    if notion_introduction_date:
        days_since = (current_time - notion_introduction_date).total_seconds() / 86400
        if days_since <= 7:  # ≤ 604800 seconds
            total += 0.0
        elif days_since > 30:  # > 2592000 seconds
            total += 0.2
        else:
            total += 0.1
    
    # Data 2: notion passive rate
    if notion_passive_rate < 0.05:
        total += 0.0
    elif notion_passive_rate < 0.1:
        total += 0.1
    elif notion_passive_rate < 0.15:
        total += 0.15
    else:
        total += 0.2
    
    # Data 3: notion active rate
    if notion_active_rate < 0.05:
        total += 0.0
    elif notion_active_rate < 0.1:
        total += 0.1
    elif notion_active_rate < 0.15:
        total += 0.15
    else:
        total += 0.2
    
    # Data 4: notion weightiness
    if notion_weightiness <= 0.5:
        total += 0.0
    elif notion_weightiness <= 0.7:
        total += 0.1
    elif notion_weightiness <= 0.9:
        total += 0.15
    else:
        total += 0.2
    
    return round(total, 2)


# ============================================================================
# H. NOTION PRIORITY RATE
# ============================================================================

async def calculate_notion_priority_rates(
    user_id: str,
    db_pool: asyncpg.Pool
) -> int:
    """
    Calculate priority rate for all active notions
    
    Documentation formula: (1 - notion_rate) × notion_weightiness = priority_rate
    
    Higher priority = more important to practice
    
    Args:
        user_id: User ID
        db_pool: Database connection pool
    
    Returns:
        Number of notions updated
    """
    async with db_pool.acquire() as conn:
        # Update all notions with rate between 0 and 1
        result = await conn.execute("""
            UPDATE session_notion sn
            SET notion_priority_rate = ROUND(
                ((1 - sn.notion_rate) * COALESCE(bn.weightiness, 0.5))::numeric,
                2
            ),
            updated_at = NOW()
            FROM brain_notion bn
            WHERE sn.notion_id = bn.id
            AND sn.user_id = $1
            AND sn.session_id IS NULL
            AND sn.notion_rate > 0
            AND sn.notion_rate < 1
        """, user_id)
        
        # Get count of updated rows
        updated_count = int(result.split()[-1]) if result else 0
        logger.info(f"Updated {updated_count} notion priority rates for user {user_id}")
        return updated_count


# ============================================================================
# I. NOTION COMPLEXITY RATE
# ============================================================================

async def calculate_notion_complexity_rates(
    user_id: str,
    db_pool: asyncpg.Pool
) -> int:
    """
    Calculate complexity rate for all active notions
    
    Documentation formula: Average of 5 factors:
    - Data 1: ((current_timestamp - introduction_date) / 86400) × 0.05
    - Data 2: 1 - notion_rate (reversed)
    - Data 3: (passive_rate / 0.1) × 0.05
    - Data 4: (active_rate / 0.1) × 0.05
    
    Higher complexity = harder to learn for this user
    
    Args:
        user_id: User ID
        db_pool: Database connection pool
    
    Returns:
        Number of notions updated
    """
    async with db_pool.acquire() as conn:
        # Get all notions needing complexity calculation
        notions = await conn.fetch("""
            SELECT 
                notion_id,
                notion_rate,
                notion_introduction_date,
                notion_passive_rate,
                notion_active_rate
            FROM session_notion
            WHERE user_id = $1
            AND session_id IS NULL
            AND notion_rate > 0
            AND notion_rate < 1
        """, user_id)
        
        updated_count = 0
        now = datetime.now()
        
        for notion in notions:
            # Data 1: Days since introduction
            if notion['notion_introduction_date']:
                days_since = (now - notion['notion_introduction_date']).total_seconds() / 86400
                data1 = min(days_since * 0.05, 1.0)  # Cap at 1.0
                if data1 < 0.05:
                    data1 = 0
            else:
                data1 = 0
            
            # Data 2: Reversed notion rate
            data2 = 1 - float(notion['notion_rate'])
            
            # Data 3: Passive rate impact
            passive_rate = float(notion['notion_passive_rate'] or 0)
            data3 = (passive_rate / 0.1) * 0.05 if passive_rate >= 0.1 else 0
            
            # Data 4: Active rate impact
            active_rate = float(notion['notion_active_rate'] or 0)
            data4 = (active_rate / 0.1) * 0.05 if active_rate >= 0.1 else 0
            
            # Calculate average (4 data points per documentation)
            # Note: Doc says 5 but only lists 4 unique factors
            complexity = (data1 + data2 + data3 + data4) / 4
            complexity = round(max(0.0, min(1.0, complexity)), 2)
            
            # Update in database
            await conn.execute("""
                UPDATE session_notion
                SET notion_complexity_rate = $1, updated_at = NOW()
                WHERE user_id = $2 AND notion_id = $3 AND session_id IS NULL
            """, complexity, user_id, notion['notion_id'])
            
            updated_count += 1
        
        logger.info(f"Updated {updated_count} notion complexity rates for user {user_id}")
        return updated_count


# ============================================================================
# J. LIST OF TOP NOTIONS
# ============================================================================

async def get_top_notions_list(
    user_id: str,
    limit: int = 10,
    db_pool: asyncpg.Pool = None
) -> List[Dict[str, Any]]:
    """
    Get list of top priority notions for the session
    
    Documentation: "Sort notions by priority rate (desc), then by complexity rate (desc)"
    
    Excludes notions with rate = 0 or rate = 1
    
    Args:
        user_id: User ID
        limit: Maximum number of notions to return
        db_pool: Database connection pool
    
    Returns:
        List of notion dicts with id, rate, priority, complexity
    """
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT 
                sn.notion_id,
                sn.notion_rate,
                sn.notion_priority_rate,
                sn.notion_complexity_rate,
                bn.name_fr,
                bn.level_from,
                bn.weightiness
            FROM session_notion sn
            JOIN brain_notion bn ON sn.notion_id = bn.id
            WHERE sn.user_id = $1
            AND sn.session_id IS NULL
            AND sn.notion_rate > 0
            AND sn.notion_rate < 1
            ORDER BY
                sn.notion_priority_rate DESC,
                sn.notion_complexity_rate DESC
            LIMIT $2
        """, user_id, limit)
        
        notions = [
            {
                "notion_id": row['notion_id'],
                "notion_name": row['name_fr'],
                "notion_rate": float(row['notion_rate']),
                "priority_rate": float(row['notion_priority_rate'] or 0),
                "complexity_rate": float(row['notion_complexity_rate'] or 0),
                "level_from": row['level_from'],
                "weightiness": float(row['weightiness'] or 0.5)
            }
            for row in rows
        ]
        
        logger.debug(f"Found {len(notions)} top notions for user {user_id}")
        return notions


# ============================================================================
# HELPER: Initialize Notions for New User
# ============================================================================

async def initialize_notions_for_new_user(
    user_id: str,
    user_level: int,
    db_pool,
) -> int:
    """
    Seed session_notion rows for a user with no regular-session history.

    Per TuJe_Session_RampUp_and_Cycle_Goal_Logic.md §4:
    Pull max 5 notions from brain_notion at the EXACT user_level only,
    ordered by rank ASC, all written at notion_rate = 0 (introduced but
    not yet practiced). This is the seed that gives the second regular
    session its first readable notion history.

    There is no "owned" pre-seeding for notions below user_level — the
    notion-mastery model in the doc has no such concept.

    Returns the count of session_notion rows inserted.
    """
    async with db_pool.acquire() as conn:
        # Idempotent guard — if rows exist, skip (preserves prior seeding
        # without overwriting).
        existing = await conn.fetchval(
            "SELECT COUNT(*) FROM session_notion WHERE user_id = $1",
            user_id,
        )
        if existing > 0:
            logger.info(
                f"User {user_id} already has {existing} session_notion rows; "
                f"skipping initialization."
            )
            return 0

        # Up to 5 notions at exactly user_level, ordered by rank ASC.
        rows = await conn.fetch(
            """
            SELECT id
            FROM brain_notion
            WHERE level_from = $1 AND live = true
            ORDER BY rank ASC
            LIMIT 5
            """,
            user_level,
        )

        inserted = 0
        for row in rows:
            await conn.execute(
                """
                INSERT INTO session_notion (
                    user_id, notion_id, notion_rate,
                    notion_introduction_date, created_at, updated_at
                )
                VALUES ($1, $2, 0.0, NOW(), NOW(), NOW())
                ON CONFLICT (user_id, notion_id) DO NOTHING
                """,
                user_id, row["id"],
            )
            inserted += 1

        logger.info(
            f"Seeded {inserted} session_notion rows for user {user_id} "
            f"at user_level={user_level} (max 5 by rank, score 0)."
        )
        return inserted


async def populate_intents_from_seen(
    user_id: str,
    seen_intent_ids: list,
    db_pool,
) -> int:
    """
    Upsert session_intents rows from the user's recently-seen intents.

    Per TuJe_Session_RampUp_and_Cycle_Goal_Logic.md §7: session_intents rows
    are created/updated as the user encounters intents. We do this at session
    setup (mirroring how all session_notion maintenance happens at setup),
    upserting the last-7-days seen-intent set: new intents get a row, existing
    intents get their updated_at refreshed (which keeps them out of the §7
    30-day prune).

    Scores are PLACEHOLDERS (intent_score = 0, intent_priority_score = 0) per
    Option A — the real formulas are deferred to §8 (vocabulary design). The
    rows function for selection ordering but do not yet prioritise intelligently.

    Returns the number of intents upserted.
    """
    if not seen_intent_ids:
        return 0

    upserted = 0
    async with db_pool.acquire() as conn:
        for intent_id in seen_intent_ids:
            if not intent_id:
                continue
            await conn.execute(
                """
                INSERT INTO session_intents (
                    user_id, intent_id, intent_score, intent_priority_score,
                    intent_introduction_date, created_at, updated_at
                )
                VALUES ($1, $2, 0.0, 0.0, NOW(), NOW(), NOW())
                ON CONFLICT (user_id, intent_id)
                DO UPDATE SET updated_at = NOW()
                """,
                user_id, intent_id,
            )
            upserted += 1

    logger.info(
        f"Upserted {upserted} session_intents rows for user {user_id} "
        f"(placeholder scores, pending §8)."
    )
    return upserted


# ============================================================================
# HELPER: Full Notion Processing Pipeline for Session Start
# ============================================================================

async def process_notions_for_session_start(
    user_id: str,
    streak7: float,
    streak30: float,
    session_mood: str,
    is_new_user: bool,
    user_level: int,
    db_pool: asyncpg.Pool
) -> Dict[str, Any]:
    """
    Run full notion processing pipeline for session start
    
    Steps (for non-new users):
    G. Update notion rates (decay)
    H. Calculate priority rates
    I. Calculate complexity rates
    J. Get top notions list
    
    Args:
        user_id: User ID
        streak7: 7-day streak
        streak30: 30-day streak
        session_mood: Selected mood
        is_new_user: Whether this is user's first session
        user_level: User's current level
        db_pool: Database connection pool
    
    Returns:
        Dict with processing results
    """
    result = {
        "notions_decayed": 0,
        "priorities_updated": 0,
        "complexities_updated": 0,
        "top_notions": [],
        "skipped_reason": None
    }

    # Orphan cleanup (NULL-marker approach): remove any session_notion rows for this
    # user that were left with session_id IS NULL by a failed/abandoned prior session
    # start. Only NULL rows are touched — the NOT-NULL history (previous sessions) is
    # preserved. This guarantees the NULL rows we are about to write reflect THIS start.
    async with db_pool.acquire() as conn:
        deleted = await conn.execute(
            "DELETE FROM session_notion WHERE user_id = $1 AND session_id IS NULL",
            user_id,
        )
    logger.info(f"Orphan-cleanup: removed NULL-session_id session_notion rows for user {user_id} ({deleted})")

    if is_new_user:
        # Initialize notions for brand new user
        initialized = await initialize_notions_for_new_user(
            user_id, user_level, db_pool
        )
        result["notions_initialized"] = initialized
        result["skipped_reason"] = "new_user"
        logger.info(f"New user {user_id}: initialized {initialized} notions, skipping decay")
        return result
    
    # G. Update notion rates (decay)
    result["notions_decayed"] = await update_notion_rates_on_session_start(
        user_id, streak7, streak30, session_mood, db_pool
    )
    
    # H. Calculate priority rates
    result["priorities_updated"] = await calculate_notion_priority_rates(user_id, db_pool)
    
    # I. Calculate complexity rates
    result["complexities_updated"] = await calculate_notion_complexity_rates(user_id, db_pool)
    
    # J. Get top notions list
    result["top_notions"] = await get_top_notions_list(user_id, limit=10, db_pool=db_pool)
    
    return result
