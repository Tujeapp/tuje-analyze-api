#!/usr/bin/env python3
# ============================================================================
# test_notion_carryforward.py - Test tool for notion carry-forward (Step 2+)
# ============================================================================
# Verifies update_notion_rates_on_session_start (the NULL-marker carry-forward):
#   - reads the previous session's rows (highest-rank completed session)
#   - creates NEW rows with session_id NULL and DECAYED rates
#   - preserves the previous session's rows (history untouched)
#
# Reusable: auto-detects the previous session, sets up its own crafted notion
# rows, runs the function, verifies, and (optionally) cleans up. Re-run safe.
#
# WRITES session_notion (test rows + the carry-forward output). Test-user only.
# Throwaway-style diagnostic - not imported by app code.
#
# NOTE: this calls update_notion_rates_on_session_start DIRECTLY (unit test of
# step 2). In the full pipeline, process_notions_for_session_start runs the
# orphan-cleanup (step 1) FIRST, which deletes leftover NULL rows so carry-forward
# never duplicates. This tool's own setup_rows() clears rows first to mimic that.
#
# RUN:
#   cd ~/Desktop/tuje-analyze-api
#   source venv/bin/activate
#   set -a; source .env; set +a
#   python test_notion_carryforward.py
# ============================================================================

import asyncio
import os
import asyncpg

from notion_management import update_notion_rates_on_session_start

# ---- CONFIG ----------------------------------------------------------------
USER_ID = "D08BC99B-0996-4E2B-B4FB-80CF9E0B33DC"
# Notions to craft as the "previous session" rows (must exist in brain_notion).
TEST_NOTIONS = ["NOT202408090927", "NOT202408130245"]
START_RATES = [0.50, 0.30]          # starting notion_rate for each (0<rate<1)
SETUP = True                         # craft the previous-session rows before running
TEARDOWN = True                      # delete ALL test-user session_notion rows after
# Decay inputs (feed Coefficient A):
STREAK7, STREAK30, SESSION_MOOD = 0.5, 0.5, "relax"
# ---------------------------------------------------------------------------


def hr(title=""):
    print("\n" + "=" * 70)
    if title:
        print(title)
        print("=" * 70)


async def get_prev_session_id(pool):
    """The session the carry-forward will read = highest-rank completed session."""
    return await pool.fetchval(
        """
        SELECT id FROM session
        WHERE user_id = $1 AND status = 'completed'
        ORDER BY session_rank DESC
        LIMIT 1
        """,
        USER_ID,
    )


async def show_rows(pool, label):
    rows = await pool.fetch(
        """
        SELECT notion_id, session_id, notion_rate,
               notion_passive_mentioned, notion_active_mentioned
        FROM session_notion
        WHERE user_id = $1
        ORDER BY session_id NULLS FIRST, notion_id
        """,
        USER_ID,
    )
    print(f"\n  {label} - {len(rows)} rows:")
    if not rows:
        print("    (none)")
        return rows
    print(f"    {'notion_id':<20} {'session_id':<28} {'rate':>5} {'pass':>5} {'act':>4}")
    print("    " + "-" * 70)
    for r in rows:
        sid = r["session_id"] if r["session_id"] is not None else "NULL"
        print(f"    {r['notion_id']:<20} {sid:<28} "
              f"{float(r['notion_rate']):>5.2f} "
              f"{r['notion_passive_mentioned']:>5} {r['notion_active_mentioned']:>4}")
    return rows


async def setup_rows(pool, prev_session_id):
    """Craft previous-session notion rows (stamped with the real prev session id)."""
    # Clear any prior test rows first (idempotent - mimics step-1 orphan cleanup).
    await pool.execute("DELETE FROM session_notion WHERE user_id = $1", USER_ID)
    for notion_id, rate in zip(TEST_NOTIONS, START_RATES):
        await pool.execute(
            """
            INSERT INTO session_notion (
                user_id, notion_id, session_id, notion_rate, notion_introduction_date,
                notion_passive_mentioned, notion_active_mentioned, created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, NOW() - INTERVAL '10 days', 0, 0, NOW(), NOW())
            """,
            USER_ID, notion_id, prev_session_id, rate,
        )


async def main():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL not set. Run: set -a; source .env; set +a")

    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=2)
    try:
        prev_id = await get_prev_session_id(pool)
        if not prev_id:
            print("No completed session for the test user - carry-forward has nothing to")
            print("read (this is the correct first-regular-session skip). Nothing to test.")
            return
        print(f"Previous session (highest-rank completed): {prev_id}")

        if SETUP:
            hr("SETUP - craft previous-session notion rows")
            await setup_rows(pool, prev_id)
            print(f"  crafted {len(TEST_NOTIONS)} rows stamped session_id={prev_id}")

        hr("BEFORE")
        await show_rows(pool, "before")

        hr("RUN - update_notion_rates_on_session_start (carry-forward)")
        created = await update_notion_rates_on_session_start(
            user_id=USER_ID, streak7=STREAK7, streak30=STREAK30,
            session_mood=SESSION_MOOD, db_pool=pool,
        )
        print(f"  returned (rows created): {created}")

        hr("AFTER")
        after = await show_rows(pool, "after")

        hr("VERDICT")
        new_null = await pool.fetchval(
            "SELECT COUNT(*) FROM session_notion WHERE user_id=$1 AND session_id IS NULL",
            USER_ID,
        )
        preserved = await pool.fetchval(
            "SELECT COUNT(*) FROM session_notion WHERE user_id=$1 AND session_id=$2",
            USER_ID, prev_id,
        )
        # Decay check: each NULL row's rate should be strictly below its source rate.
        decayed_ok = True
        src = {r["notion_id"]: float(r["notion_rate"])
               for r in after if r["session_id"] == prev_id}
        for r in after:
            if r["session_id"] is None:
                s = src.get(r["notion_id"])
                if s is not None and not (float(r["notion_rate"]) < s):
                    decayed_ok = False

        print(f"  new NULL-session rows: {new_null} (expect {len(TEST_NOTIONS)})")
        print(f"  preserved previous-session rows: {preserved} (expect {len(TEST_NOTIONS)})")
        print(f"  all NULL rows decayed below source: {decayed_ok}")
        if (created == len(TEST_NOTIONS) and new_null == len(TEST_NOTIONS)
                and preserved == len(TEST_NOTIONS) and decayed_ok):
            print("  PASS: carry-forward created decayed NULL rows; history preserved.")
        else:
            print("  CHECK: inspect the AFTER table above.")

        if TEARDOWN:
            await pool.execute("DELETE FROM session_notion WHERE user_id = $1", USER_ID)
            print("\n  (teardown: cleared test-user session_notion rows)")

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
