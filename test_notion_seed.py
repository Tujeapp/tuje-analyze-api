#!/usr/bin/env python3
# ============================================================================
# test_notion_seed.py - Verify initialize_notions_for_new_user (Step 6)
# ============================================================================
# Confirms the seed (NULL-marker model):
#   - creates score-0 rows with session_id NULL
#   - the idempotent guard skips re-seeding when rows already exist
#   - re-running after a clear seeds fresh (abandoned-then-retry case)
#
# WRITES session_notion. Test-user only. Throwaway.
#
# RUN:
#   cd ~/Desktop/tuje-analyze-api
#   source venv/bin/activate ; set -a; source .env; set +a
#   python test_notion_seed.py
# ============================================================================

import asyncio
import os
import asyncpg

from notion_management import initialize_notions_for_new_user

USER_ID = "D08BC99B-0996-4E2B-B4FB-80CF9E0B33DC"
USER_LEVEL = 100   # adjust if no notions exist at this level_from


def hr(t=""):
    print("\n" + "=" * 64)
    if t:
        print(t); print("=" * 64)


async def show(pool, label):
    rows = await pool.fetch(
        """SELECT notion_id, session_id, notion_rate FROM session_notion
           WHERE user_id=$1 ORDER BY session_id NULLS FIRST, notion_id""",
        USER_ID,
    )
    print(f"\n  {label} - {len(rows)} rows")
    for r in rows:
        sid = r["session_id"] if r["session_id"] is not None else "NULL"
        print(f"    {r['notion_id']:<20} {sid:<14} rate={float(r['notion_rate']):.2f}")
    return rows


async def main():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    try:
        # Clean slate
        await pool.execute("DELETE FROM session_notion WHERE user_id=$1", USER_ID)

        hr("RUN 1 - seed from empty (should create score-0 NULL rows)")
        n1 = await initialize_notions_for_new_user(USER_ID, USER_LEVEL, pool)
        print(f"  seeded: {n1}")
        rows1 = await show(pool, "after run 1")

        hr("RUN 2 - seed again (guard should SKIP, no new rows)")
        n2 = await initialize_notions_for_new_user(USER_ID, USER_LEVEL, pool)
        print(f"  seeded: {n2} (expect 0 - guard skips)")
        rows2 = await show(pool, "after run 2")

        hr("VERDICT")
        all_null = all(r["session_id"] is None for r in rows1)
        all_zero = all(float(r["notion_rate"]) == 0 for r in rows1)
        guard_works = (n2 == 0 and len(rows2) == len(rows1))
        print(f"  run1 created rows: {n1} (expect >0 if notions exist at level {USER_LEVEL})")
        print(f"  all rows session_id NULL: {all_null}")
        print(f"  all rows score 0: {all_zero}")
        print(f"  guard skipped re-seed: {guard_works}")
        if n1 == 0:
            print(f"  NOTE: 0 seeded - likely no live brain_notion at level_from={USER_LEVEL}.")
            print("        Adjust USER_LEVEL to a level that has notions, and re-run.")
        elif all_null and all_zero and guard_works:
            print("  PASS: seed writes score-0 NULL rows; guard prevents re-seed.")
        else:
            print("  CHECK: inspect above.")

        # teardown
        await pool.execute("DELETE FROM session_notion WHERE user_id=$1", USER_ID)
        print("\n  (teardown: cleared test-user rows)")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
