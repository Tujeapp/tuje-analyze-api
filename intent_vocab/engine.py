# ============================================================================
# intent_vocab/engine.py - Build an intent cycle from an intent pack
# ============================================================================
# Ties repository (DB reads/writes on ONE connection) to rules + planner.
# Mirrors notion_steps/engine.py. Not wired into cycle creation or
# commit_answer yet (B4b).
#
# Spec: TuJe_Intent_Vocab_Engine_Spec.md §6 (+ §10–12 for credit sources).
# Candidate words mirror the commit-time credit (intent_vocab/hook.py):
#   passive = (interaction_vocab_id ∪ expected_vocab_id) ∩ pack
#   active  = (vocab_ids of perfect/good answers ∪ expected_vocab_id) ∩ pack,
#             only when the candidate's mode can give active evidence.
# ============================================================================

import json
import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

from notion_steps.planner import splice_tail

from . import rules
from .planner import Candidate, PlannerError, candidate_value, plan_slots, touches_unowned
from .repository import (
    load_intent_candidates,
    load_intent_meta,
    load_intent_state,
    load_pack_words,
    load_plan_tier,
    load_seen,
    load_word_rows,
    pick_intent_ids,
    update_cycle_tail,
    write_intent_progress,
)

logger = logging.getLogger(__name__)

CYCLE_SIZE = 7
ACTIVE_MODES = ("voice", "multipleButtons")


# ---------------------------------------------------------------------------
# Pure
# ---------------------------------------------------------------------------

def _ids(values: Optional[Iterable[Optional[str]]]) -> set:
    return {v for v in (values or []) if v}


def build_candidates(rows: Dict[str, Dict[str, Any]], pack_ids: Iterable[str]) -> List[Candidate]:
    """
    Pure. rows: brain_interaction_id -> {interaction_vocab_id, expected_vocab_id,
    answer_vocab_ids, mode} (mode already resolved). Only pack words are kept;
    active words only when the mode can give active evidence.
    """
    pack = set(pack_ids)
    out: List[Candidate] = []
    for bid in sorted(rows):
        r = rows[bid]
        mode = r.get("mode") or "voice"
        expected = _ids(r.get("expected_vocab_id"))
        passive = (_ids(r.get("interaction_vocab_id")) | expected) & pack
        active = set()
        if mode in ACTIVE_MODES:
            active = (_ids(r.get("answer_vocab_ids")) | expected) & pack
        out.append(Candidate(id=bid, passive_ids=passive, active_ids=active, mode=mode))
    return out


def has_unowned_target(candidates: List[Candidate], words: Dict[str, rules.PackWord]) -> bool:
    """Pure: at least one candidate touches a not-owned pack word (passive or
    active). False → the intent has nothing left to teach with these candidates."""
    return any(touches_unowned(c, words) for c in candidates)


def pack_words_from(meta: Dict[str, Dict[str, Any]], word_rows: Dict[str, Any],
                    session_level: int) -> Dict[str, rules.PackWord]:
    """
    Pure. meta: vocab_id -> {"weight", "level_own"} (the snapshot shape);
    word_rows: load_word_rows() output. ALL pack words are returned; owned ones
    carry owned=True (planner value 0, counted in owned_ratio).
    """
    out: Dict[str, rules.PackWord] = {}
    for vid, m in meta.items():
        score, downgraded, _pc, _ac = word_rows.get(vid, (rules.WordScore(), False, 0, 0))
        owned = rules.is_owned(score, m.get("level_own"), session_level, downgraded)
        out[vid] = rules.PackWord(vid, float(m["weight"]), score.passive, score.active, owned)
    return out


def candidates_to_pool(candidates: List[Candidate]) -> Dict[str, Dict[str, Any]]:
    return {c.id: {"passive": sorted(c.passive_ids), "active": sorted(c.active_ids), "mode": c.mode}
            for c in candidates}


def candidates_from_pool(pool_candidates: Dict[str, Dict[str, Any]]) -> List[Candidate]:
    return [Candidate(id=bid, passive_ids=set(c.get("passive") or []),
                      active_ids=set(c.get("active") or []), mode=c.get("mode") or "voice")
            for bid, c in sorted(pool_candidates.items())]


def resolve_candidate_mode(plan_tier: Optional[str], authored_mode: Optional[str]) -> str:
    """Same mode decision as the dispatcher (authored button mode wins, else
    plan default). Intent cycles present buttons on the 'default' (authored)
    purpose — the purpose doesn't change the mode. Imported lazily: the
    cycle_manager package pulls the whole cycle stack."""
    from cycle_manager.interaction_dispatcher import decide_interaction_mode_and_purpose
    mode, _purpose = decide_interaction_mode_and_purpose(plan_tier, "intent", 0.0, authored_mode)
    return mode


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

async def load_pack(conn, user_id: str, intent_id: str, session_level: int
                    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, rules.PackWord]]:
    """(snapshot meta, PackWords with the user's current scores), no locks."""
    raw = await load_pack_words(conn, intent_id)
    meta = {vid: {"weight": rules.weight_of(c), "level_own": lo} for vid, (c, lo) in raw.items()}
    word_rows = await load_word_rows(conn, user_id, meta.keys(), lock=False)
    return meta, pack_words_from(meta, word_rows, session_level)


async def build_intent_cycle(
    conn,
    user_id: str,
    session_level: Optional[int],
    slots: int = CYCLE_SIZE,
    dry_run: bool = False,
) -> Optional[Tuple[List[str], Dict[str, Any]]]:
    """
    Try up to 3 picked intents; the first that yields a full plan wins.
    Unless dry_run, marks that intent in_progress (never downgrades).

    Returns (ordered_ids, intent_pool) or None. intent_pool is the snapshot
    for session_cycle.intent_pool: {intent_id, intent_name, mastery_ratio,
    words: {vid: {weight, level_own}}, candidates: {bid: {passive, active, mode}}}.
    """
    level = int(session_level or 0)
    intent_ids = await pick_intent_ids(conn, user_id, level)
    plan_tier = await load_plan_tier(conn, user_id) if intent_ids else None
    reasons: Dict[str, str] = {}

    for intent_id in intent_ids:
        meta, words = await load_pack(conn, user_id, intent_id, level)
        if not meta:
            reasons[intent_id] = "no live words"
            continue

        rows = await load_intent_candidates(conn, intent_id, level)
        if not rows:
            reasons[intent_id] = f"no candidate interactions at level {level}"
            continue
        for r in rows.values():
            r["mode"] = resolve_candidate_mode(plan_tier, r["authored_mode"])
        candidates = build_candidates(rows, meta.keys())
        if not has_unowned_target(candidates, words):
            reasons[intent_id] = (f"no candidate touches a not-owned pack word "
                                  f"({len(candidates)} candidates, "
                                  f"{sum(not w.owned for w in words.values())}/{len(words)} words not owned)")
            logger.info(f"build_intent_cycle: skipping intent {intent_id} — {reasons[intent_id]}")
            continue

        seen = await load_seen(conn, user_id, rows.keys())
        try:
            plan = plan_slots(words, candidates, played_in_cycle=[], seen_ever=seen,
                              slots_needed=slots)
        except PlannerError as e:
            reasons[intent_id] = f"planner error: {e}"
            continue
        if len(plan.ids) != slots:
            reasons[intent_id] = f"plan returned {len(plan.ids)}/{slots} ids"
            continue

        intent = await load_intent_meta(conn, intent_id) or {}
        ratios = rules.pack_ratios(list(words.values()))
        if not dry_run:
            await write_intent_progress(conn, user_id, intent_id, "in_progress", ratios)

        pool = {
            "intent_id": intent_id,
            "intent_name": intent.get("name"),
            "mastery_ratio": intent.get("mastery_ratio"),
            "words": meta,
            "candidates": candidates_to_pool(candidates),
        }
        logger.info(
            f"build_intent_cycle: user={user_id} intent={intent_id} level={level} "
            f"words={len(meta)} owned={sum(w.owned for w in words.values())} "
            f"candidates={len(candidates)} plan={plan.ids} warnings={plan.warnings}"
            f"{' (dry_run)' if dry_run else ''}"
        )
        return plan.ids, pool

    logger.warning(
        f"build_intent_cycle: no intent could be built for user={user_id} "
        f"level={level}; tried {intent_ids or 'none'}; reasons={reasons}"
    )
    return None


async def on_interaction_committed(conn, session_interaction_id: str, answer_id: str) -> None:
    """
    Intent cycles only (spec §6.6): after every commit (complete or
    incomplete), with the word credit already written by the credit hook,
    refresh the pack's ratios/state on user_intent_progress and re-plan the
    not-yet-played tail of candidate_pool_ids from the cycle's intent_pool
    snapshot (no new search). One transaction. The caller wraps this in
    try/except — it never fails a commit.
    """
    row = await conn.fetchrow("""
        SELECT si.cycle_id, si.interaction_number, s.user_id, s.session_level,
               sc.cycle_goal, sc.intent_pool,
               sc.candidate_pool_ids::text[] AS candidate_pool_ids
        FROM session_interaction si
        JOIN session s        ON s.id = si.session_id
        JOIN session_cycle sc ON sc.id = si.cycle_id
        WHERE si.id = $1
    """, session_interaction_id)
    if row is None or row["cycle_goal"] != "intent" or row["intent_pool"] is None:
        logger.info(f"intent on_interaction_committed: {session_interaction_id} is not a "
                    f"pack-built intent cycle — skipping")
        return

    pool = row["intent_pool"]
    if isinstance(pool, str):  # asyncpg returns jsonb as text by default
        pool = json.loads(pool)
    intent_id = pool["intent_id"]
    user_id = row["user_id"]
    level = int(row["session_level"] or 0)
    played_count = row["interaction_number"]
    pool_ids = list(row["candidate_pool_ids"] or [])
    candidates = candidates_from_pool(pool.get("candidates") or {})

    old_tail = pool_ids[played_count:]
    new_tail = old_tail
    warnings: List[str] = []

    async with conn.transaction():
        meta = pool.get("words") or {}
        word_rows = await load_word_rows(conn, user_id, meta.keys(), lock=False)
        words = pack_words_from(meta, word_rows, level)

        # a) Pack ratios + state (never down).
        ratios = rules.pack_ratios(list(words.values()))
        previous = await load_intent_state(conn, user_id, intent_id)
        state = rules.pack_state(ratios, pool.get("mastery_ratio"), previous)
        await write_intent_progress(conn, user_id, intent_id, state, ratios)

        # b) Re-plan the not-yet-played tail; played positions never change.
        remaining = CYCLE_SIZE - played_count
        if remaining > 0:
            played = pool_ids[:played_count]
            try:
                seen = await load_seen(conn, user_id, [c.id for c in candidates])
                plan = plan_slots(words, candidates, played_in_cycle=played, seen_ever=seen,
                                  slots_needed=remaining,
                                  last_played_id=played[-1] if played else None)
                warnings = plan.warnings
                new_pool = splice_tail(pool_ids, played_count, plan.ids, size=CYCLE_SIZE)
                if new_pool is None:
                    logger.error(
                        f"intent on_interaction_committed: re-plan for {session_interaction_id} "
                        f"would not give {CYCLE_SIZE} ids (played={played_count}, "
                        f"pool={len(pool_ids)}, tail={len(plan.ids)}) — tail kept")
                elif await update_cycle_tail(conn, row["cycle_id"], played_count, new_pool):
                    new_tail = plan.ids
                else:
                    warnings.append("a later position already exists — tail kept")
            except PlannerError as e:
                warnings.append(f"planner error: {e} — tail kept")

    logger.info(
        f"intent step commit: si={session_interaction_id} intent={intent_id} "
        f"state {previous} -> {state} ratios={ {k: round(v, 3) for k, v in ratios.items()} } "
        f"tail {old_tail} -> {new_tail} warnings={warnings}"
    )


def describe_candidates(candidates: List[Candidate], words: Dict[str, rules.PackWord]) -> List[Dict[str, Any]]:
    """Pure, for the probe: one row per candidate with its current value."""
    return [{"id": c.id, "mode": c.mode, "passive": sorted(c.passive_ids),
             "active": sorted(c.active_ids), "value": candidate_value(c, words)}
            for c in sorted(candidates, key=lambda c: (-candidate_value(c, words), c.id))]
