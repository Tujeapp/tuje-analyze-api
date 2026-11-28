# ============================================================================
# intent_vocab/repository.py - user_vocab_progress reads/writes
# ============================================================================
# All functions take ONE asyncpg connection; the caller owns the transaction.
# asyncpg is not imported here so the pure modules stay importable without it.
# ============================================================================

from typing import Dict, Iterable, Optional, Set, Tuple

from .rules import WordScore

# vocab_id -> (score, downgraded, passive_count, active_count)
WordRow = Tuple[WordScore, bool, int, int]


async def load_word_rows(conn, user_id: str, vocab_ids: Iterable[str]) -> Dict[str, WordRow]:
    """Existing progress rows for these words, locked FOR UPDATE (call inside
    a transaction). Missing words are simply absent."""
    ids = sorted(set(vocab_ids))
    if not ids:
        return {}
    rows = await conn.fetch("""
        SELECT vocab_id, passive_score, active_score, downgraded,
               passive_count, active_count
        FROM user_vocab_progress
        WHERE user_id = $1 AND vocab_id = ANY($2::text[])
        FOR UPDATE
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
