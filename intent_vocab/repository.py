# ============================================================================
# intent_vocab/repository.py - DB access for intent vocab
# ============================================================================
# user_vocab_progress (word credit) + the intent-cycle reads/writes (B4a).
# All functions take ONE asyncpg connection; the caller owns the transaction.
# asyncpg is not imported here so the pure modules stay importable without it.
# ============================================================================

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .rules import WordScore

# vocab_id -> (score, downgraded, passive_count, active_count)
WordRow = Tuple[WordScore, bool, int, int]


async def load_word_rows(conn, user_id: str, vocab_ids: Iterable[str],
                         lock: bool = True) -> Dict[str, WordRow]:
    """Existing progress rows for these words. lock=True takes FOR UPDATE (call
    inside a transaction); lock=False for read-only paths (cycle build, probe —
    FOR UPDATE is rejected in a READ ONLY transaction). Missing words are absent."""
    ids = sorted(set(vocab_ids))
    if not ids:
        return {}
    rows = await conn.fetch(f"""
        SELECT vocab_id, passive_score, active_score, downgraded,
               passive_count, active_count
        FROM user_vocab_progress
        WHERE user_id = $1 AND vocab_id = ANY($2::text[])
        {"FOR UPDATE" if lock else ""}
    """, user_id, ids)
    return {
        r["vocab_id"]: (
            WordScore(int(r["passive_score"] or 0), int(r["active_score"] or 0)),
            bool(r["downgraded"]),
            int(r["passive_count"] or 0),
            int(r["active_count"] or 0),
        )
        for r in rows
    }


async def load_level_own(conn, vocab_ids: Iterable[str]) -> Dict[str, Optional[int]]:
    ids = sorted(set(vocab_ids))
    if not ids:
        return {}
    rows = await conn.fetch(
        "SELECT id, level_own FROM brain_vocab WHERE id = ANY($1::text[])", ids)
    return {r["id"]: r["level_own"] for r in rows}


async def load_slot_vocab_ids(conn, vocab_ids: Iterable[str], entity_tokens: Iterable[str]) -> Set[str]:
    """Of these vocab ids, the ones that can fill a template slot: their
    entity is the live brain_entity named by one of the template's tokens
    (same token → entity mapping as button_realization)."""
    ids = sorted(set(vocab_ids))
    tokens = sorted(set(entity_tokens))
    if not ids or not tokens:
        return set()
    rows = await conn.fetch("""
        SELECT v.id
        FROM brain_vocab v
        JOIN brain_entity e ON e.id = v.entity_type_id
        WHERE v.id = ANY($1::text[]) AND e.name = ANY($2::text[]) AND e.live = true
    """, ids, tokens)
    return {r["id"] for r in rows}


async def upsert_word_rows(conn, user_id: str, rows: Dict[str, WordRow]) -> int:
    """ONE statement: write absolute scores/counts/downgraded for each word.
    first_seen_at is set on insert and kept on conflict. Returns rows written."""
    if not rows:
        return 0
    ids = sorted(rows)
    await conn.execute("""
        INSERT INTO user_vocab_progress (
            user_id, vocab_id, passive_score, active_score,
            passive_count, active_count, downgraded, first_seen_at, updated_at)
        SELECT $1, t.vocab_id, t.passive_score, t.active_score,
               t.passive_count, t.active_count, t.downgraded, now(), now()
        FROM unnest($2::text[], $3::int[], $4::int[], $5::int[], $6::int[], $7::bool[])
             AS t(vocab_id, passive_score, active_score, passive_count, active_count, downgraded)
        ON CONFLICT (user_id, vocab_id) DO UPDATE SET
            passive_score = EXCLUDED.passive_score,
            active_score  = EXCLUDED.active_score,
            passive_count = EXCLUDED.passive_count,
            active_count  = EXCLUDED.active_count,
            downgraded    = EXCLUDED.downgraded,
            updated_at    = now()
    """,
        user_id, ids,
        [rows[v][0].passive for v in ids],
        [rows[v][0].active for v in ids],
        [rows[v][2] for v in ids],
        [rows[v][3] for v in ids],
        [rows[v][1] for v in ids],
    )
    return len(ids)


# ============================================================================
# Intent cycle (B4a): pack pick, words, candidates, progress
# ============================================================================
# Id arrays are cast with ::text[] because brain columns mix varchar[]/text[].

STATE_RANK_SQL = "array_position(ARRAY['in_progress','discovered','owned']::text[], {})"


async def pick_intent_ids(conn, user_id: str, session_level: int, limit: int = 3) -> List[str]:
    """
    Priority (spec §6.1): (a) the user's in-progress intents, most recently
    updated first; (b) live intents with level_from <= session_level (NULL = 0),
    not discovered/owned by the user, with at least one live word — ordered by
    level_from ASC, weightiness DESC NULLS LAST, id.
    """
    if limit <= 0:
        return []
    in_progress = await conn.fetch("""
        SELECT uip.intent_id::text AS intent_id
        FROM user_intent_progress uip
        JOIN brain_intent bi ON bi.id::text = uip.intent_id::text AND bi.live = TRUE
        WHERE uip.user_id = $1 AND uip.state = 'in_progress'
        ORDER BY uip.updated_at DESC NULLS LAST
    """, user_id)
    fresh = await conn.fetch("""
        SELECT bi.id::text AS intent_id
        FROM brain_intent bi
        WHERE bi.live = TRUE
          AND COALESCE(bi.level_from, 0) <= $2::int
          AND NOT EXISTS (
              SELECT 1 FROM user_intent_progress uip
              WHERE uip.user_id = $1
                AND uip.intent_id::text = bi.id::text
                AND uip.state IN ('discovered', 'owned')
          )
          AND EXISTS (
              SELECT 1 FROM brain_vocab v
              WHERE v.live = TRUE
                AND v.expected_intent_id::text[] @> ARRAY[bi.id::text]
          )
        ORDER BY COALESCE(bi.level_from, 0) ASC, bi.weightiness DESC NULLS LAST, bi.id
        LIMIT $3
    """, user_id, session_level, limit + len(in_progress))

    picked: List[str] = []
    for r in list(in_progress) + list(fresh):
        if r["intent_id"] not in picked:
            picked.append(r["intent_id"])
        if len(picked) >= limit:
            break
    return picked


async def load_intent_meta(conn, intent_id: str) -> Optional[Dict[str, Any]]:
    row = await conn.fetchrow(
        "SELECT id::text AS id, name, mastery_ratio FROM brain_intent WHERE id::text = $1",
        intent_id)
    if row is None:
        return None
    m = row["mastery_ratio"]
    return {"id": row["id"], "name": row["name"],
            "mastery_ratio": float(m) if m is not None else None}


async def load_pack_words(conn, intent_id: str) -> Dict[str, Tuple[Any, Optional[int]]]:
    """Live words of the pack: vocab_id -> (commonness, level_own)."""
    rows = await conn.fetch("""
        SELECT id::text AS id, commonness, level_own
        FROM brain_vocab
        WHERE live = TRUE
          AND expected_intent_id::text[] @> ARRAY[$1::text]
        ORDER BY id
    """, intent_id)
    return {r["id"]: (r["commonness"], r["level_own"]) for r in rows}


async def load_intent_candidates(conn, intent_id: str, session_level: int) -> Dict[str, Dict[str, Any]]:
    """
    brain_interaction_id -> {interaction_vocab_id, expected_vocab_id,
    answer_vocab_ids (union over its live perfect/good answers), authored_mode}.
    Live, tagged with the intent, >= 1 linked answer, level_from <= level + 50
    (no lower bound). Deliberately NOT filtered on subtopic live or mood.
    """
    rows = await conn.fetch("""
        SELECT i.id::text AS id,
               i.interaction_vocab_id::text[] AS interaction_vocab_id,
               i.expected_vocab_id::text[]    AS expected_vocab_id,
               bit.answer_mode                AS authored_mode,
               ARRAY(
                   SELECT DISTINCT x
                   FROM brain_interaction_answer bia
                   JOIN brain_answer ba ON ba.id = bia.answer_id
                   CROSS JOIN LATERAL unnest(ba.vocab_ids::text[]) AS x
                   WHERE bia.interaction_id = i.id
                     AND bia.answer_type IN ('perfect', 'good')
                     AND bia.live = TRUE AND ba.live = TRUE
               ) AS answer_vocab_ids
        FROM brain_interaction i
        LEFT JOIN brain_interaction_type bit ON bit.id = i.interaction_type_id
        WHERE i.live = TRUE
          AND i.intents::text[] @> ARRAY[$1::text]
          AND i.level_from <= $2::int + 50
          AND EXISTS (
              SELECT 1 FROM brain_interaction_answer bia
              WHERE bia.interaction_id = i.id
          )
        ORDER BY i.id
    """, intent_id, session_level)
    return {
        r["id"]: {
            "interaction_vocab_id": list(r["interaction_vocab_id"] or []),
            "expected_vocab_id": list(r["expected_vocab_id"] or []),
            "answer_vocab_ids": list(r["answer_vocab_ids"] or []),
            "authored_mode": r["authored_mode"],
        }
        for r in rows
    }


async def load_plan_tier(conn, user_id: str) -> Optional[str]:
    return await conn.fetchval("SELECT subscription_tier FROM brain_user WHERE id = $1", user_id)


async def load_intent_state(conn, user_id: str, intent_id: str) -> Optional[str]:
    return await conn.fetchval(
        "SELECT state FROM user_intent_progress WHERE user_id = $1 AND intent_id = $2",
        user_id, intent_id)


async def write_intent_progress(conn, user_id: str, intent_id: str, state: str,
                                ratios: Dict[str, float]) -> bool:
    """Upsert the pack row. State never goes down (in_progress < discovered <
    owned); ratios/averages are the current values; discovered_at / owned_at
    keep the earliest. Returns True if a row was inserted or updated."""
    status = await conn.execute(f"""
        INSERT INTO user_intent_progress AS uip (
            user_id, intent_id, state, understood_ratio, owned_ratio,
            avg_passive, avg_active, discovered_at, owned_at, updated_at
        ) VALUES (
            $1, $2, $3::text, $4::float8, $5::float8, $6::float8, $7::float8,
            CASE WHEN $3::text IN ('discovered', 'owned') THEN NOW() END,
            CASE WHEN $3::text = 'owned' THEN NOW() END,
            NOW())
        ON CONFLICT (user_id, intent_id) DO UPDATE SET
            state = CASE
                WHEN {STATE_RANK_SQL.format("EXCLUDED.state")}
                     > COALESCE({STATE_RANK_SQL.format("uip.state")}, 0)
                THEN EXCLUDED.state ELSE uip.state END,
            understood_ratio = EXCLUDED.understood_ratio,
            owned_ratio      = EXCLUDED.owned_ratio,
            avg_passive      = EXCLUDED.avg_passive,
            avg_active       = EXCLUDED.avg_active,
            discovered_at    = COALESCE(uip.discovered_at, EXCLUDED.discovered_at),
            owned_at         = COALESCE(uip.owned_at, EXCLUDED.owned_at),
            updated_at       = NOW()
    """, user_id, intent_id, state,
        float(ratios.get("understood_ratio", 0.0)), float(ratios.get("owned_ratio", 0.0)),
        float(ratios.get("avg_passive", 0.0)), float(ratios.get("avg_active", 0.0)))
    return status in ("INSERT 0 1", "UPDATE 1")


async def load_seen(conn, user_id: str, brain_ids: Iterable[str]) -> Set[str]:
    """Reuses the notion-step query (imported lazily: it imports asyncpg)."""
    from notion_steps.repository import load_seen as _load_seen
    return await _load_seen(conn, user_id, brain_ids)


async def update_cycle_tail(conn, cycle_id: str, played_count: int, new_pool: List[str]) -> bool:
    """Reuses the notion-step tail write (no write once a later position exists)."""
    from notion_steps.repository import update_cycle_tail as _update_cycle_tail
    return await _update_cycle_tail(conn, cycle_id, played_count, new_pool)
