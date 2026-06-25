#!/usr/bin/env python3
# ============================================================================
# test_intent_list.py - Verify get_top_intents_list (intent build step 1)
# ============================================================================
# Confirms the list sorts by priority_score DESC, then intent_score ASC.
# Reads whatever is in session_intents for the test user (craft rows first,
# see chat). Read-only — does NOT write or tear down (so it won't clobber
# crafted rows; clean up manually after).
#
# RUN: cd ~/Desktop/tuje-analyze-api ; source venv/bin/activate ; set -a; source .env; set +a ; python test_intent_list.py
# ============================================================================

import asyncio, os, asyncpg
from intent_management import get_top_intents_list

USER_ID = "D08BC99B-0996-4E2B-B4FB-80CF9E0B33DC"


async def main():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    try:
        intents = await get_top_intents_list(USER_ID, limit=10, db_pool=pool)
        print(f"get_top_intents_list returned {len(intents)} intents:\n")
        if not intents:
            print("  (empty — craft session_intents rows first, see chat)")
        for i, x in enumerate(intents):
            print(f"  {i+1}. {x['intent_id']:<22} name={x['intent_name']!r:<24} "
                  f"priority={x['priority_score']:.2f} score={x['intent_score']:.2f}")
        # Verify sort: priority desc, then score asc
        ok = True
        for a, b in zip(intents, intents[1:]):
            if a['priority_score'] < b['priority_score']:
                ok = False
            elif a['priority_score'] == b['priority_score'] and a['intent_score'] > b['intent_score']:
                ok = False
        if intents:
            print(f"\n  sort correct (priority DESC, score ASC tiebreak): {ok}")
            print("  PASS" if ok else "  CHECK ordering")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
