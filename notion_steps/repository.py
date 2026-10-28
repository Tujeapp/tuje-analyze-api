# ============================================================================
# notion_steps/repository.py - DB access for notion steps
# ============================================================================
# Every function takes ONE asyncpg connection (not a pool) so a caller can run
# a whole notion-cycle build on a single connection / transaction.
# Id arrays are cast with ::text[] because brain columns mix varchar[]/text[].
# ============================================================================

import logging
from typing import Dict, Iterable, List, Set, Tuple

import asyncpg

from .rules import Evidence, Step, normalize_purpose

logger = logging.getLogger(__name__)


async def load_steps(conn: asyncpg.Connection, notion_id: str) -> Tuple[List[Step], List[str]]:
    """
    Live steps belonging to exactly this notion (cardinality(notion_ids) = 1).
    Rows with an unknown purpose or NULL rank are skipped with a warning; live
    steps shared with other notions are skipped with a warning too.
    """
    rows = await conn.fetch("""
        SELECT id::text AS id, notion_ids::text[] AS notion_ids, rank, purpose
        FROM brain_notion_step
        WHERE live = TRUE
          AND $1::text = ANY(notion_ids::text[])
        ORDER BY rank NULLS LAST, id
    """, notion_id)

    steps: List[Step] = []
    warnings: List[str] = []
    for r in rows:
        notion_ids = r["notion_ids"] or []
        if len(notion_ids) != 1:
            warnings.append(f"step {r['id']} skipped: linked to {len(notion_ids)} notions {notion_ids}")
            continue
        purpose = normalize_purpose(r["purpose"])
        if purpose is None:
            warnings.append(f"step {r['id']} skipped: unknown purpose {r['purpose']!r}")
            continue
        if r["rank"] is None:
            warnings.append(f"step {r['id']} skipped: NULL rank")
            continue
        steps.append(Step(id=r["id"], purpose=purpose, rank=int(r["rank"])))
    return steps, warnings


async def pick_notion_ids(conn: asyncpg.Connection, user_id: str, cycle_level: int,
                          limit: int = 3) -> List[str]:
    """
    Priority: (a) the user's in-progress notions, most recently touched first;
    (b) live notions at or below cycle_level, not discovered/owned by the user,
    with at least one live single-notion step — easiest first.
    """
    if limit <= 0:
        return []

    in_progress = await conn.fetch("""
        SELECT unp.notion_id::text AS notion_id
        FROM user_notion_progress unp
        JOIN brain_notion bn ON bn.id = unp.notion_id AND bn.live
        WHERE unp.user_id = $1 AND unp.state = 'in_progress'
        ORDER BY unp.updated_at DESC NULLS LAST
    """, user_id)

    fresh = await conn.fetch("""
        SELECT bn.id::text AS notion_id
        FROM brain_notion bn
        WHERE bn.live = TRUE
          AND bn.level_from <= $2
          AND NOT EXISTS (
              SELECT 1 FROM user_notion_progress unp
              WHERE unp.user_id = $1
                AND unp.notion_id = bn.id
                AND unp.state IN ('discovered', 'owned')
          )
          AND EXISTS (
              SELECT 1 FROM brain_notion_step st
              WHERE st.live = TRUE
                AND cardinality(st.notion_ids) = 1
                AND (st.notion_ids::text[])[1] = bn.id::text
          )
        ORDER BY bn.level_from ASC, bn.rank ASC NULLS LAST, bn.id
        LIMIT $3
    """, user_id, cycle_level, limit + len(in_progress))

    picked: List[str] = []
    for r in list(in_progress) + list(fresh):
        nid = r["notion_id"]
        if nid not in picked:
            picked.append(nid)
        if len(picked) >= limit:
            break
    return picked


async def load_candidates(conn: asyncpg.Connection, steps: Iterable[Step],
                          cycle_level: int) -> Dict[str, List[str]]:
    """
    brain_interaction_id -> this notion's step ids it is tagged with.
    Deliberately NOT filtered on subtopic live or on the session-mood type list.
    """
    step_ids = [s.id for s in steps]
    if not step_ids:
        return {}

    rows = await conn.fetch("""
        SELECT i.id::text AS id, i.notion_step_ids::text[] AS notion_step_ids
        FROM brain_interaction i
        WHERE i.live = TRUE
          AND i.notion_step_ids::text[] && $1::text[]
          AND i.level_from BETWEEN GREATEST(0, $2::int - 50) AND $2::int + 50
          AND EXISTS (
              SELECT 1 FROM brain_interaction_answer bia
              WHERE bia.interaction_id = i.id
          )
        ORDER BY i.id
    """, step_ids, cycle_level)

    wanted = set(step_ids)
    return {
        r["id"]: [sid for sid in (r["notion_step_ids"] or []) if sid in wanted]
        for r in rows
    }


async def load_evidence(conn: asyncpg.Connection, user_id: str, notion_id: str) -> Evidence:
    """step_id -> {brain_interaction_id: best_verdict} (perfect/good only)."""
    rows = await conn.fetch("""
        SELECT step_id::text AS step_id,
               brain_interaction_id::text AS brain_interaction_id,
               best_verdict
        FROM user_notion_step_evidence
        WHERE user_id = $1 AND notion_id = $2
          AND best_verdict IN ('perfect', 'good')
    """, user_id, notion_id)

    evidence: Evidence = {}
    for r in rows:
        evidence.setdefault(r["step_id"], {})[r["brain_interaction_id"]] = r["best_verdict"]
    return evidence


async def load_seen(conn: asyncpg.Connection, user_id: str, brain_ids: Iterable[str]) -> Set[str]:
    """Which of brain_ids the user has ever been served (any time, any status)."""
    brain_ids = list(brain_ids)
    if not brain_ids:
        return set()

    rows = await conn.fetch("""
        SELECT DISTINCT si.brain_interaction_id::text AS brain_interaction_id
        FROM session_interaction si
        JOIN session s ON s.id = si.session_id
        WHERE s.user_id = $1
          AND si.brain_interaction_id = ANY($2::text[])
    """, user_id, brain_ids)
    return {r["brain_interaction_id"] for r in rows}


async def upsert_in_progress(conn: asyncpg.Connection, user_id: str, notion_id: str,
                             current_step_id: str) -> None:
    """Create/refresh the in-progress row; never downgrades discovered/owned."""
    await conn.execute("""
        INSERT INTO user_notion_progress AS unp (
            user_id, notion_id, state, current_step_id, started_at, updated_at
        ) VALUES ($1, $2, 'in_progress', $3, NOW(), NOW())
        ON CONFLICT (user_id, notion_id) DO UPDATE
        SET current_step_id = EXCLUDED.current_step_id,
            updated_at = NOW()
        WHERE unp.state IS NULL OR unp.state NOT IN ('discovered', 'owned')
    """, user_id, notion_id, current_step_id)
