#!/usr/bin/env python3
# ============================================================================
# test_notion_carryforward.py - Test tool for notion carry-forward + scoping
# ============================================================================
# Verifies the notion session-start pipeline pieces (steps 2 & 3):
#
#  STEP 2 - update_notion_rates_on_session_start (carry-forward):
#    - reads the previous session's rows (highest-rank completed session)
#    - creates NEW rows with session_id NULL and DECAYED rates
#    - preserves the previous session's rows (history untouched)
#
#  STEP 3 - calculate_notion_priority_rates / _complexity_rates (NULL scoping):
#    - compute priority/complexity ONLY on the current (NULL-session) rows
#    - history rows' priority/complexity are NOT touched
#
# Reusable: auto-detects the previous session, crafts its rows (with DISTINCT
# priority/complexity sentinel values so we can prove history is protected),
# runs the pipeline, verifies, and tears down. Re-run safe.
#
# WRITES session_notion. Test-user only. Throwaway-style - not imported by app.
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

from notion_management import (
    update_notion_rates_on_session_start,
    calculate_notion_priority_rates,
    calculate_notion_complexity_rates,
)

# ---- CONFIG ----------------------------------------------------------------
USER_ID = "D08BC99B-0996-4E2B-B4FB-80CF9E0B33DC"
TEST_NOTIONS = ["NOT202408090927", "NOT202408130245"]
START_RATES = [0.50, 0.30]
# Sentinel priority/complexity on the HISTORY rows - if step 3 is correctly
# scoped, these must remain UNCHANGED after the pipeline runs.
HISTORY_PRIORITY = 0.99
HISTORY_COMPLEXITY = 0.88
SETUP = True
TEARDOWN = True
STREAK7, STREAK30, SESSION_MOOD = 0.5, 0.5, "relax"
# ---------------------------------------------------------------------------


def hr(title=""):
    print("\n" + "=" * 70)
    if title:
        print(title)
        print("=" * 70)


async def get_prev_session_id(pool):
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
               notion_priority_rate, notion_complexity_rate
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
    print(f"    {'notion_id':<20} {'session_id':<28} {'rate':>5} {'prio':>5} {'cplx':>5}")
    print("    " + "-" * 72)
    for r in rows:
        sid = r["session_id"] if r["session_id"] is not None else "NULL"
        print(f"    {r['notion_id']:<20} {sid:<28} "
              f"{float(r['notion_rate']):>5.2f} "
              f"{float(r['notion_priority_rate'] or 0):>5.2f} "
              f"{float(r['notion_complexity_rate'] or 0):>5.2f}")
    return rows


async def setup_rows(pool, prev_session_id):
    await pool.execute("DELETE FROM session_notion WHERE user_id = $1", USER_ID)
    for notion_id, rate in zip(TEST_NOTIONS, START_RATES):
        await pool.execute(
            """
            INSERT INTO session_notion (
                user_id, notion_id, session_id, notion_rate, notion_introduction_date,
                notion_passive_mentioned, notion_active_mentioned,
                notion_priority_rate, notion_complexity_rate,
                created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, NOW() - INTERVAL '10 days', 0, 0, $5, $6, NOW(), NOW())
            """,
            USER_ID, notion_id, prev_session_id, rate,
            HISTORY_PRIORITY, HISTORY_COMPLEXITY,
        )


async def main():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL not set. Run: set -a; source .env; set +a")

    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=2)
    try:
        prev_id = await get_prev_session_id(pool)
        if not prev_id:
            print("No completed session for the test user - nothing to carry forward.")
            return
        print(f"Previous session (highest-rank completed): {prev_id}")

        if SETUP:
            hr("SETUP - craft previous-session rows (history priority/complexity = sentinels)")
            await setup_rows(pool, prev_id)
            print(f"  crafted {len(TEST_NOTIONS)} rows; history prio={HISTORY_PRIORITY} cplx={HISTORY_COMPLEXITY}")

        hr("BEFORE")
        await show_rows(pool, "before")

        hr("RUN - full session-start notion pipeline (steps 2 + 3)")
        created = await update_notion_rates_on_session_start(
            user_id=USER_ID, streak7=STREAK7, streak30=STREAK30,
            session_mood=SESSION_MOOD, db_pool=pool,
        )
        print(f"  carry-forward created: {created}")
        prio_n = await calculate_notion_priority_rates(USER_ID, pool)
        print(f"  priority updated: {prio_n}")
        cplx_n = await calculate_notion_complexity_rates(USER_ID, pool)
        print(f"  complexity updated: {cplx_n}")

        hr("AFTER")
        after = await show_rows(pool, "after")

        hr("VERDICT")
        # 1. NULL rows exist and got priority/complexity populated (non-zero).
        null_rows = [r for r in after if r["session_id"] is None]
        hist_rows = [r for r in after if r["session_id"] == prev_id]
        null_have_prio = all(float(r["notion_priority_rate"] or 0) > 0 for r in null_rows)
        null_have_cplx = all(float(r["notion_complexity_rate"] or 0) > 0 for r in null_rows)
        # 2. History rows kept their sentinel priority/complexity (untouched).
        hist_protected = all(
            abs(float(r["notion_priority_rate"] or 0) - HISTORY_PRIORITY) < 0.001
            and abs(float(r["notion_complexity_rate"] or 0) - HISTORY_COMPLEXITY) < 0.001
            for r in hist_rows
        )
        print(f"  NULL rows: {len(null_rows)} (expect {len(TEST_NOTIONS)})")
        print(f"  NULL rows have priority > 0: {null_have_prio}")
        print(f"  NULL rows have complexity > 0: {null_have_cplx}")
        print(f"  history rows priority/complexity UNCHANGED ({HISTORY_PRIORITY}/{HISTORY_COMPLEXITY}): {hist_protected}")
        if (len(null_rows) == len(TEST_NOTIONS) and null_have_prio
                and null_have_cplx and hist_protected):
            print("  PASS: step 3 scoping correct - current rows computed, history protected.")
        else:
            print("  CHECK: inspect the AFTER table above.")
            if not hist_protected:
                print("  >> HISTORY WAS MODIFIED - the session_id IS NULL scope is missing somewhere!")

        if TEARDOWN:
            await pool.execute("DELETE FROM session_notion WHERE user_id = $1", USER_ID)
            print("\n  (teardown: cleared test-user session_notion rows)")

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
