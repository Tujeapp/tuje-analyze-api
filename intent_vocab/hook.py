# ============================================================================
# intent_vocab/hook.py - Credit words after every committed interaction
# ============================================================================
# on_commit_credit_words: runs after complete_interaction /
# mark_interaction_incomplete, any cycle goal. Reads one joined row, applies
# intent_vocab.rules, writes user_vocab_progress and
# session_interaction.vocab_credited in ONE transaction. The caller wraps it
# in try/except: it never fails a commit.
#
# downgrade_not_understood: called by POST /record-not-understood-vocab for
# the newly added ids only (see newly_added_ids).
# ============================================================================

import json
import logging
from typing import Dict, Iterable, List, Optional, Set, Tuple

from . import rules
from .repository import load_level_own, load_word_rows, upsert_word_rows

logger = logging.getLogger(__name__)

CREDIT_VERDICTS = ("perfect", "good")

# session_level NULL → level ownership can never apply.
_NO_LEVEL = -1


def _clean(ids: Optional[Iterable[Optional[str]]]) -> Set[str]:
    return {i for i in (ids or []) if i}


def vocab_ids_from_found(raw) -> Set[str]:
    """session_answer.vocabulary_found: jsonb list of VocabularyMatch dicts
    ({"id", "transcription_fr", ...}). asyncpg hands jsonb back as text."""
    if raw is None:
        return set()
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw)
        except ValueError:
            return set()
    if not isinstance(raw, list):
        return set()
    return {v["id"] for v in raw if isinstance(v, dict) and v.get("id")}


def evidence_ids(
    verdict: Optional[str],
    mode: Optional[str],
    interaction_vocab_ids,
    expected_vocab_ids,
    vocabulary_found,
    selected_vocab_id: Optional[str],
    answer_vocab_ids,
) -> Tuple[Set[str], Set[str]]:
    """Pure: (passive_ids, active_ids) for positive credit. Empty unless the
    verdict is perfect/good and the mode is known."""
    if verdict not in CREDIT_VERDICTS or mode not in rules.MODES:
        return set(), set()
    passive = _clean(interaction_vocab_ids) | _clean(expected_vocab_ids)
    if mode == "voice":
        active = vocab_ids_from_found(vocabulary_found)
    elif mode == "multipleButtons":
        active = _clean([selected_vocab_id]) | _clean(answer_vocab_ids)
    else:  # singleButton
        active = set()
    return passive, active


async def on_commit_credit_words(conn, session_interaction_id: str, answer_id: str) -> None:
    async with conn.transaction():
        # FOR UPDATE OF si: a concurrent re-commit waits here, then sees
        # vocab_credited = true and returns.
        row = await conn.fetchrow("""
            SELECT s.user_id, s.session_level, si.vocab_credited,
                   bi.interaction_vocab_id::text[]     AS interaction_vocab_id,
                   bi.expected_vocab_id::text[]        AS expected_vocab_id,
                   sa.verdict, sa.answer_mode_used, sa.vocabulary_found,
                   sa.selected_vocab_id,
                   ba.vocab_ids::text[]                AS answer_vocab_ids
            FROM session_interaction si
            JOIN session s             ON s.id = si.session_id
            JOIN brain_interaction bi  ON bi.id = si.brain_interaction_id
            LEFT JOIN session_answer sa ON sa.id = $2
            LEFT JOIN brain_answer ba   ON ba.id = sa.selected_answer_id
            WHERE si.id = $1
            FOR UPDATE OF si
        """, session_interaction_id, answer_id)
        if row is None:
            logger.warning(f"intent-vocab credit: interaction {session_interaction_id} not found")
            return
        if row["vocab_credited"]:
            logger.info(f"intent-vocab credit: {session_interaction_id} already credited — skipping")
            return

        user_id = row["user_id"]
        verdict = row["verdict"]
        mode = row["answer_mode_used"]
        session_level = row["session_level"] if row["session_level"] is not None else _NO_LEVEL

        passive_ids, active_ids = evidence_ids(
            verdict, mode, row["interaction_vocab_id"], row["expected_vocab_id"],
            row["vocabulary_found"], row["selected_vocab_id"], row["answer_vocab_ids"])
        all_ids = passive_ids | active_ids

        existing = await load_word_rows(conn, user_id, all_ids)
        level_own = await load_level_own(conn, all_ids)

        scores = {}
        downgraded = {}
        p_count = {}
        a_count = {}
        for v in all_ids:
            s, d, pc, ac = existing.get(v, (rules.WordScore(), False, 0, 0))
            scores[v] = rules.WordScore(s.passive, s.active)
            downgraded[v], p_count[v], a_count[v] = d, pc, ac

        # 1) Owned words get no positive credit. `downgraded` is the stored flag
        #    (set by POST /record-not-understood-vocab, not here).
        owned = {
            v for v in all_ids
            if rules.is_owned(scores[v], level_own.get(v), session_level, downgraded[v])
        }

        # 2) Positive credit.
        deltas = {}
        if passive_ids or active_ids:
            deltas = rules.apply_evidence(scores, passive_ids, active_ids, mode, owned_ids=owned)
            for v in passive_ids - owned:
                p_count[v] += 1
            for v in active_ids - owned:
                a_count[v] += 1

        # 3) Write only rows that changed.
        changed = {}
        for v in all_ids:
            new = (scores[v], downgraded[v], p_count[v], a_count[v])
            old = existing.get(v)
            if old is None or (old[0].passive, old[0].active, old[1], old[2], old[3]) != (
                    new[0].passive, new[0].active, new[1], new[2], new[3]):
                changed[v] = new
        written = await upsert_word_rows(conn, user_id, changed)

        await conn.execute(
            "UPDATE session_interaction SET vocab_credited = true WHERE id = $1",
            session_interaction_id)

    passive_credited = {v: d[0] for v, d in deltas.items() if d[0]}
    active_credited = {v: d[1] for v, d in deltas.items() if d[1]}
    logger.info(
        f"intent-vocab credit: si={session_interaction_id} user={user_id} "
        f"verdict={verdict} mode={mode} passive={passive_credited} "
        f"active={active_credited} skipped_owned={sorted(owned)} "
        f"rows_written={written}"
    )


def newly_added_ids(old_ids, new_ids) -> List[str]:
    """Pure: ids in `new_ids` not in `old_ids`, in `new_ids` order, each once;
    None/empty ids and None arrays are ignored."""
    old = _clean(old_ids)
    out: List[str] = []
    for v in new_ids or []:
        if v and v not in old and v not in out:
            out.append(v)
    return out


async def downgrade_not_understood(conn, user_id: str, vocab_ids: Iterable[str]) -> Dict[str, int]:
    """Lower passive for the given words and mark them downgraded (owned ones
    included). Call inside a transaction. Returns the applied deltas."""
    ids = _clean(vocab_ids)
    if not ids:
        return {}
    existing = await load_word_rows(conn, user_id, ids)
    empty = (rules.WordScore(), False, 0, 0)
    scores = {v: rules.WordScore(existing.get(v, empty)[0].passive,
                                 existing.get(v, empty)[0].active) for v in ids}
    deltas = rules.apply_downgrade(scores, ids)
    rows = {v: (scores[v], True, existing.get(v, empty)[2], existing.get(v, empty)[3])
            for v in ids}
    await upsert_word_rows(conn, user_id, rows)
    return deltas
