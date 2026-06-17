#!/usr/bin/env python3
# ============================================================================
# test_selection.py - Selection Trace Harness (READ-ONLY)
# ============================================================================
# Loads a REAL SessionContext for a user from the live DB, then runs the REAL
# search + selection functions, printing the full trace that the curl/start-cycle
# loop hides: seen-sets, candidate pool, each candidate's combination + WHY,
# the sorted order, the final 7, and which fallback phase fired.
#
# READ-ONLY: SessionContext.load, find_best_subtopic_with_fallback, and
# select_cycle_interactions all only SELECT. This script writes NOTHING.
#
# Reflects R32 (transcription-based combination) AS OF 2026-06-17: the transcription
# axis keys on transcription_fr (the spoken words), not interaction_id.
#
# RUN (in the backend repo, with the venv + env loaded):
#   cd ~/Desktop/tuje-analyze-api
#   source venv/bin/activate
#   set -a; source .env; set +a
#   python test_selection.py
#
# Edit the CONFIG block below to change the scenario, then re-run.
#
# CAVEAT: cycle_level / cycle_boredom below are values YOU inject. In a real
# session they come from the (currently simplified) cycle-calc. This harness
# tests SELECTION GIVEN setup values — not the setup-calc itself.
# ============================================================================

import asyncio
import os
import asyncpg

# --- The real modules under test ---
from session_context import SessionContext
from interaction_search import find_best_subtopic_with_fallback
from cycle_manager.interaction_selection import select_cycle_interactions

# ============================================================================
# CONFIG — edit these, then re-run
# ============================================================================
USER_ID = "D08BC99B-0996-4E2B-B4FB-80CF9E0B33DC"
CYCLE_BOREDOM = 0.30          # 0.0 - 1.0
CYCLE_LEVEL = 0               # 0 - 400, step 50
INTERACTION_USER_LEVEL = 0    # level the search filters around (usually == CYCLE_LEVEL for cycle 1)
SESSION_MOOD = "effective"    # effective | playful | cultural | relax | listening
CYCLE_GOAL = "story"          # story | notion | intent  (only story is fully built)
# ============================================================================


def hr(title: str = ""):
    print("\n" + "=" * 70)
    if title:
        print(title)
        print("=" * 70)


async def main():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL not set. Run: set -a; source .env; set +a  before this script."
        )

    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=2)
    try:
        hr("CONFIG")
        print(f"  user_id              : {USER_ID}")
        print(f"  cycle_boredom        : {CYCLE_BOREDOM}")
        print(f"  cycle_level          : {CYCLE_LEVEL}")
        print(f"  interaction_user_level: {INTERACTION_USER_LEVEL}")
        print(f"  session_mood         : {SESSION_MOOD}")
        print(f"  cycle_goal           : {CYCLE_GOAL}")

        # --- 1. Load the REAL context (the user's actual recent history) ---
        context = await SessionContext.load(USER_ID, pool)
        hr("SESSION CONTEXT (real history)")
        print(f"  seen_subtopics      ({len(context.seen_subtopics)}): {sorted(context.seen_subtopics)}")
        print(f"  seen_interaction_ids({len(context.seen_interaction_ids)}): {sorted(context.seen_interaction_ids)}")
        print(f"  seen_intents        ({len(context.seen_intents)}): {sorted(context.seen_intents)}")
        print(f"  seen_transcriptions ({len(context.seen_transcriptions)}): {sorted(context.seen_transcriptions)}")
        if not context.seen_subtopics and not context.seen_interaction_ids and not context.seen_intents:
            print("  >> NOTE: empty history. Every candidate will resolve to combination 5 (all 'new').")
            print("     This is the cold-start case — selection cannot differentiate by combination.")

        # --- 2. Run the REAL search (candidate pool construction + fallback) ---
        try:
            candidates = await find_best_subtopic_with_fallback(
                db_pool=pool,
                interaction_user_level=INTERACTION_USER_LEVEL,
                cycle_boredom=CYCLE_BOREDOM,
                session_mood=SESSION_MOOD,
                context=context,
                cycle_goal=CYCLE_GOAL,
            )
        except Exception as e:
            hr("SEARCH FAILED")
            print(f"  {type(e).__name__}: {e}")
            print("  (InsufficientInteractionsError here means no subtopic had >=7 qualifying")
            print("   interactions even after all fallback phases — a CONTENT issue, not a code bug.)")
            return

        hr(f"CANDIDATE POOL ({len(candidates)} found)")
        subtopic = candidates[0].subtopic_id if candidates else "—"
        print(f"  chosen subtopic: {subtopic}")
        print(f"  {'id':<22} {'comb':>4} {'boredom':>8} {'level':>6} {'entry':>6}  why(subtopic/transcription/intent)")
        print("  " + "-" * 92)
        for c in candidates:
            # Re-derive the seen/new breakdown so you can see WHY each combination value.
            st = "seen" if c.subtopic_id in context.seen_subtopics else "new"
            tr = "seen" if c.transcription_fr in context.seen_transcriptions else "new"
            it = "seen" if any(i in context.seen_intents for i in c.intent_ids) else "new"
            print(f"  {c.id:<22} {c.combination:>4} {c.boredom_rate:>8.2f} "
                  f"{c.level_from:>6} {str(c.is_entry_point):>6}  {st}/{tr}/{it}")

        # --- 3. Run the REAL ordering/selection ---
        ordered_ids = await select_cycle_interactions(
            interactions=candidates,
            cycle_level=CYCLE_LEVEL,
            cycle_boredom=CYCLE_BOREDOM,
            cycle_goal=CYCLE_GOAL,
        )

        # Build a lookup so we can annotate the final picks.
        by_id = {c.id: c for c in candidates}
        hr("FINAL SELECTION (ordered 7)")
        for pos, iid in enumerate(ordered_ids, start=1):
            c = by_id.get(iid)
            if c:
                tag = " (entry point)" if c.is_entry_point else ""
                print(f"  {pos}. {iid}   comb={c.combination}  boredom={c.boredom_rate:.2f}{tag}")
            else:
                print(f"  {pos}. {iid}   (not in candidate map?)")

        # Quick read on whether combination actually differentiated anything.
        combos_used = {by_id[i].combination for i in ordered_ids if i in by_id}
        hr("DIAGNOSIS")
        if len(combos_used) == 1:
            print(f"  All selected interactions share combination {combos_used.pop()}.")
            print("  Selection could not differentiate by combination — either cold-start")
            print("  (empty history) or thin content. NOT necessarily a code problem.")
        else:
            print(f"  Selected interactions span combinations {sorted(combos_used)} —")
            print("  combination differentiation IS happening.")

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
