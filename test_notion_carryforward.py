#!/usr/bin/env python3
# ============================================================================
# test_notion_carryforward.py - Test tool for notion session-start pipeline
# ============================================================================
# Verifies steps 2, 3, 4 of the notion build (NULL-marker model):
#
#  STEP 2 - update_notion_rates_on_session_start (carry-forward):
#    reads previous session's rows, creates NEW session_id-NULL rows (decayed),
#    preserves history.
#  STEP 3 - calculate_notion_priority_rates / _complexity_rates:
#    compute on the current (NULL) rows only; history priority/complexity untouched.
#  STEP 4 - get_top_notions_list:
#    returns ONLY the current session's notions (NULL rows), not history.
#
# Crafts history rows with sentinel priority/complexity (to prove protection),
# runs the pipeline, verifies, tears down. Re-run safe. Test-user only. WRITES.
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
    get_top_notions_list,
)

# ---- CONFIG ----------------------------------------------------------------
USER_ID = "D08BC99B-0996-4E2B-B4FB-80CF9E0B33DC"
TEST_NOTIONS = ["NOT202408090927", "NOT202408130245"]
START_RATES = [0.50, 0.30]
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
            hr("SETUP - craft previous-session rows (history prio/cplx = sentinels)")
            await setup_rows(pool, prev_id)
            print(f"  crafted {len(TEST_NOTIONS)} rows; history prio={HISTORY_PRIORITY} cplx={HISTORY_COMPLEXITY}")

        hr("BEFORE")
        await show_rows(pool, "before")

        hr("RUN - full session-start notion pipeline (steps 2 + 3 + 4)")
        created = await update_notion_rates_on_session_start(
            user_id=USER_ID, streak7=STREAK7, streak30=STREAK30,
            session_mood=SESSION_MOOD, db_pool=pool,
        )
        print(f"  carry-forward created: {created}")
        prio_n = await calculate_notion_priority_rates(USER_ID, pool)
        print(f"  priority updated: {prio_n}")
        cplx_n = await calculate_notion_complexity_rates(USER_ID, pool)
        print(f"  complexity updated: {cplx_n}")
        top = await get_top_notions_list(USER_ID, limit=10, db_pool=pool)
        print(f"  top notions list returned: {len(top)} entries")

        hr("AFTER")
        after = await show_rows(pool, "after")

        hr("LIST (get_top_notions_list output)")
        if not top:
            print("    (empty)")
        for n in top:
            print(f"    {n['notion_id']:<20} rate={n['notion_rate']:.2f} "
                  f"prio={n['priority_rate']:.2f} cplx={n['complexity_rate']:.2f}")

        hr("VERDICT")
        null_rows = [r for r in after if r["session_id"] is None]
        hist_rows = [r for r in after if r["session_id"] == prev_id]
        null_have_prio = all(float(r["notion_priority_rate"] or 0) > 0 for r in null_rows)
        null_have_cplx = all(float(r["notion_complexity_rate"] or 0) > 0 for r in null_rows)
        hist_protected = all(
            abs(float(r["notion_priority_rate"] or 0) - HISTORY_PRIORITY) < 0.001
            and abs(float(r["notion_complexity_rate"] or 0) - HISTORY_COMPLEXITY) < 0.001
            for r in hist_rows
        )
        # Step 4: list returns exactly the current notions, no history duplication.
        list_count_ok = len(top) == len(TEST_NOTIONS)
        # The list should reflect current (decayed) priorities, NOT the history sentinel 0.99.
        list_not_history = all(abs(n["priority_rate"] - HISTORY_PRIORITY) > 0.001 for n in top)

        print(f"  NULL rows: {len(null_rows)} (expect {len(TEST_NOTIONS)})")
        print(f"  NULL rows have priority > 0: {null_have_prio}")
        print(f"  NULL rows have complexity > 0: {null_have_cplx}")
        print(f"  history prio/cplx UNCHANGED ({HISTORY_PRIORITY}/{HISTORY_COMPLEXITY}): {hist_protected}")
        print(f"  list returns {len(top)} entries (expect {len(TEST_NOTIONS)}, no history dupes): {list_count_ok}")
        print(f"  list uses current priorities (not history sentinel {HISTORY_PRIORITY}): {list_not_history}")
        if (len(null_rows) == len(TEST_NOTIONS) and null_have_prio and null_have_cplx
                and hist_protected and list_count_ok and list_not_history):
            print("  PASS: steps 2+3+4 all correct - current rows computed/listed, history protected.")
        else:
            print("  CHECK: inspect the tables above.")
            if not hist_protected:
                print("  >> HISTORY MODIFIED - a session_id IS NULL scope is missing!")
            if not list_count_ok or not list_not_history:
                print("  >> LIST LEAKED HISTORY - get_top_notions_list scope missing!")

        if TEARDOWN:
            await pool.execute("DELETE FROM session_notion WHERE user_id = $1", USER_ID)
            print("\n  (teardown: cleared test-user session_notion rows)")

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
