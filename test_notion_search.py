#!/usr/bin/env python3
# ============================================================================
# test_notion_search.py - Plumbing test for the notion-goal cycle search (Piece 4)
# ============================================================================
# Calls find_best_notion_interactions_with_fallback directly and reports what
# happens. Validates the PLUMBING:
#   - the notion list is read (first notion extracted)
#   - the notion-filtered query is built and runs
#   - candidates flow back (InteractionCandidate list), OR it raises
#     InsufficientInteractionsError cleanly
#
# IMPORTANT: given the current content gap, the EXPECTED outcome is finding < 7
# interactions and raising InsufficientInteractionsError after the fallbacks.
# That is CORRECT plumbing — the path runs and queries right; it just fails
# cleanly on content. A full cycle needs content (separate authoring task).
#
# Setup: crafts a current-session NULL notion row so get_top_notions_list has a
# first notion to return (it filters 0<rate<1 AND session_id IS NULL). WRITES
# session_notion (test-user only); tears down after.
#
# RUN:
#   cd ~/Desktop/tuje-analyze-api
#   source venv/bin/activate ; set -a; source .env; set +a
#   python test_notion_search.py
# ============================================================================

import asyncio
import os
import asyncpg

from models import InsufficientInteractionsError
from session_context import SessionContext
from interaction_search_notion import find_best_notion_interactions_with_fallback
from notion_management import get_top_notions_list

USER_ID = "D08BC99B-0996-4E2B-B4FB-80CF9E0B33DC"
# A notion to seed as the current-session list entry. Must exist in brain_notion.
# Use one that interactions actually tag in expected_notion_id for a richer test.
FIRST_NOTION = "NOT202408090927"
INTERACTION_USER_LEVEL = 100
CYCLE_BOREDOM = 0.3
SESSION_MOOD = "relax"


def hr(t=""):
    print("\n" + "=" * 66)
    if t:
        print(t); print("=" * 66)


async def main():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    try:
        # Setup: a current-session NULL notion row so the list returns a first notion.
        await pool.execute(
            "DELETE FROM session_notion WHERE user_id=$1 AND session_id IS NULL", USER_ID
        )
        await pool.execute(
            """INSERT INTO session_notion
               (user_id, notion_id, session_id, notion_rate,
                notion_priority_rate, notion_complexity_rate,
                notion_introduction_date, notion_passive_mentioned,
                notion_active_mentioned, created_at, updated_at)
               VALUES ($1,$2,NULL,0.30,0.50,0.40,NOW(),0,0,NOW(),NOW())""",
            USER_ID, FIRST_NOTION,
        )

        hr("CHECK - get_top_notions_list returns a first notion")
        top = await get_top_notions_list(USER_ID, limit=1, db_pool=pool)
        if top:
            print(f"  first notion: {top[0]['notion_id']} "
                  f"(prio={top[0]['priority_rate']:.2f}, cplx={top[0]['complexity_rate']:.2f})")
        else:
            print("  list EMPTY - the search will raise (expected if no 0<rate<1 NULL rows)")

        hr("DIAGNOSTIC - interactions tagging this notion in expected_notion_id")
        cnt = await pool.fetchval(
            "SELECT COUNT(*) FROM brain_interaction WHERE live=true "
            "AND expected_notion_id @> ARRAY[$1]::text[]",
            FIRST_NOTION,
        )
        print(f"  live interactions with expected_notion_id containing {FIRST_NOTION}: {cnt}")
        print("  (if < 7 after the Part-2 filters, the search correctly cannot build - content gap)")

        hr("RUN - find_best_notion_interactions_with_fallback")
        context = await SessionContext.load(USER_ID, pool)
        try:
            candidates = await find_best_notion_interactions_with_fallback(
                db_pool=pool,
                interaction_user_level=INTERACTION_USER_LEVEL,
                cycle_boredom=CYCLE_BOREDOM,
                session_mood=SESSION_MOOD,
                context=context,
                cycle_goal="notion",
            )
            hr("RESULT - candidates returned")
            print(f"  PLUMBING OK: returned {len(candidates)} candidates")
            for c in candidates[:10]:
                print(f"    {c.id:<20} subtopic={c.subtopic_id:<18} "
                      f"comb={getattr(c, 'combination', '?')} boredom={c.boredom_rate:.2f}")
        except InsufficientInteractionsError as e:
            hr("RESULT - clean InsufficientInteractionsError (EXPECTED with low content)")
            print(f"  PLUMBING OK: path ran, query executed, raised cleanly:")
            print(f"    {e}")
            print("  This is the correct plumbing outcome when content is insufficient.")

    finally:
        await pool.execute(
            "DELETE FROM session_notion WHERE user_id=$1 AND session_id IS NULL", USER_ID
        )
        await pool.close()
        print("\n  (teardown: cleared test NULL rows)")


if __name__ == "__main__":
    asyncio.run(main())
