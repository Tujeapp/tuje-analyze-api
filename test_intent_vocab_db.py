#!/usr/bin/env python3
# ============================================================================
# test_intent_vocab_db.py - Read-only DB probe for the intent-cycle engine
# ============================================================================
# Needs DATABASE_URL (env, or .env fallback — same as test_notion_steps_db.py).
# Runs everything on ONE connection inside a READ-ONLY transaction that is
# rolled back, and calls build_intent_cycle(dry_run=True): writes NOTHING.
#
# RUN: cd ~/Desktop/tuje-analyze-api ; source venv/bin/activate ;
#      python test_intent_vocab_db.py <user_id> [session_level=0]
# ============================================================================

import asyncio
import json
import logging
import os
import sys

import asyncpg

from intent_vocab import rules
from intent_vocab.engine import (
    build_candidates,
    build_intent_cycle,
    describe_candidates,
    load_pack,
    resolve_candidate_mode,
)
from intent_vocab.planner import PlannerError, plan_slots
from intent_vocab.repository import (
    load_intent_candidates,
    load_intent_meta,
    load_intent_state,
    load_plan_tier,
    load_seen,
    load_word_rows,
    pick_intent_ids,
)

DRY_RUN = True


def _db_url() -> str:
    """Same source the app uses (os.getenv DATABASE_URL); fall back to .env for
    local runs where the var isn't exported into the shell."""
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    for line in open(".env"):
        line = line.strip()
        if line.startswith("DATABASE_URL"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("DATABASE_URL not found in env or .env")


def show(label, value):
    print(f"\n--- {label} ---")
    print(json.dumps(value, indent=2, default=str))


async def probe_intent(conn, user_id, intent_id, level, plan_tier):
    print("\n" + "=" * 60); print(f"INTENT {intent_id}"); print("=" * 60)
    show("meta", await load_intent_meta(conn, intent_id))

    meta, words = await load_pack(conn, user_id, intent_id, level)
    word_rows = await load_word_rows(conn, user_id, meta.keys(), lock=False)
    show(f"words ({len(words)})", [
        {"id": vid, "weight": w.weight, "passive": w.passive, "active": w.active,
         "level_own": meta[vid]["level_own"],
         "downgraded": word_rows[vid][1] if vid in word_rows else False,
         "owned": w.owned}
        for vid, w in sorted(words.items())
    ])

    rows = await load_intent_candidates(conn, intent_id, level)
    for r in rows.values():
        r["mode"] = resolve_candidate_mode(plan_tier, r["authored_mode"])
    candidates = build_candidates(rows, meta.keys())
    table = describe_candidates(candidates, words)
    for t in table:
        t["authored_mode"] = rows[t["id"]]["authored_mode"]
    show(f"candidates ({len(candidates)}) — sorted by current value", table)

    ratios = rules.pack_ratios(list(words.values()))
    previous = await load_intent_state(conn, user_id, intent_id)
    show("ratios now", ratios)
    show("state", {
        "stored": previous,
        "build would write": "in_progress (never lowers a stored state)",
        "a commit would write": rules.pack_state(
            ratios, (await load_intent_meta(conn, intent_id) or {}).get("mastery_ratio"), previous),
    })

    if candidates and words:
        seen = await load_seen(conn, user_id, rows.keys())
        show("seen ever", sorted(seen))
        try:
            plan = plan_slots(words, candidates, [], seen, 7)
            show("plan (7 ids) + warnings", {"ids": plan.ids, "warnings": plan.warnings})
        except PlannerError as e:
            show("plan", f"PlannerError: {e}")


async def main():
    if len(sys.argv) < 2:
        print("usage: python test_intent_vocab_db.py <user_id> [session_level=0]")
        sys.exit(1)
    user_id = sys.argv[1]
    level = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    assert DRY_RUN, "this probe must never write"

    conn = await asyncpg.connect(_db_url())
    tr = conn.transaction(readonly=True)
    await tr.start()
    try:
        print("=" * 60); print(f"INTENT VOCAB PROBE — user={user_id} session_level={level}"); print("=" * 60)

        intent_ids = await pick_intent_ids(conn, user_id, level)
        show("pick_intent_ids (up to 3)", intent_ids)
        plan_tier = await load_plan_tier(conn, user_id)
        show("plan tier", plan_tier)

        for intent_id in intent_ids:
            await probe_intent(conn, user_id, intent_id, level, plan_tier)

        result = await build_intent_cycle(conn, user_id, level, dry_run=DRY_RUN)
        print("\n" + "=" * 60); print("build_intent_cycle(dry_run=True)"); print("=" * 60)
        if result is None:
            show("result", None)
        else:
            ids, pool = result
            show("ordered_ids", ids)
            show("intent_pool snapshot", pool)
    finally:
        await tr.rollback()
        await conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
