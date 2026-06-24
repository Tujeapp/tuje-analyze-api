# Notion System — Testing Tools Guide

How to use the notion test tools and interpret their output. Companion to
`TuJe_Notion_Model_Redesign.md` (the model) and `TuJe_Notion_List_Build_Plan.md`
(the build).

There are two tools, both at the repo root, both **test-user only** and both
**WRITE to session_notion** (unlike the read-only search diagnostics). They are
throwaway-style diagnostics — not imported by app code.

Common setup for both:
```bash
cd ~/Desktop/tuje-analyze-api
source venv/bin/activate
set -a; source .env; set +a
```
(If a fresh terminal "cannot run" the script, it's almost always the env not
loaded — re-run the three lines above.)

---

## 1. test_notion_carryforward.py — the session-start pipeline (steps 2+3+4)

**What it tests:** the session-start notion pipeline on the NULL-marker model —
carry-forward (step 2), priority/complexity scoping (step 3), and the top-notions
list (step 4) — all in one run, asserting history is protected throughout.

**What it does, in order:**
1. Auto-detects the user's **previous session** = highest-`session_rank` completed
   session (the same logic the real carry-forward uses).
2. SETUP: crafts notion rows stamped with that previous session's id, at known
   starting rates, AND with **sentinel** priority/complexity values (0.99 / 0.88)
   — these sentinels are the trick that lets us prove history is untouched.
3. Runs `update_notion_rates_on_session_start` (carry-forward), then
   `calculate_notion_priority_rates`, then `calculate_notion_complexity_rates`,
   then `get_top_notions_list`.
4. Prints BEFORE / AFTER tables + the LIST output + a VERDICT.
5. TEARDOWN: clears the test-user rows.

**Run:** `python test_notion_carryforward.py`

**How to read it — a PASS means all of:**
- **new NULL rows = expected count** — carry-forward created the current session's
  rows (session_id NULL).
- **NULL rows have priority > 0 and complexity > 0** — step 3 computed them on the
  current rows.
- **history prio/cplx UNCHANGED (0.99/0.88)** — the sentinels survived, proving the
  `session_id IS NULL` scoping never wrote to history rows. **This is the critical
  safety check.**
- **list returns the expected count, using current priorities (not the 0.99
  sentinel)** — step 4's list reads only current rows, no history leak.

**The AFTER table is the clearest view:** current rows show `session_id = NULL` with
*decayed* rates and *computed* prio/cplx; history rows show the real session id with
the *original* rates and the *sentinel* prio/cplx. If a history row's prio/cplx ever
changed from 0.99/0.88 → a scope is missing somewhere (the tool prints an explicit
"HISTORY MODIFIED" warning).

**Failure signals to watch:**
- "HISTORY MODIFIED" → a `session_id IS NULL` scope is missing in priority or
  complexity (step 3).
- "LIST LEAKED HISTORY" → `get_top_notions_list` scope missing (step 4): list count
  too high, or list shows the 0.99 sentinel priority.
- Duplicate NULL rows accumulating across runs → you're running an OLD version of the
  tool without setup-clear/teardown; or the orphan-cleanup isn't running. (The current
  tool clears rows in SETUP, so this shouldn't happen.)

**Config (top of file):** `TEST_NOTIONS`, `START_RATES`, `HISTORY_PRIORITY`,
`HISTORY_COMPLEXITY`, `SETUP`, `TEARDOWN`, and the decay inputs
(`STREAK7`/`STREAK30`/`SESSION_MOOD`). Change `START_RATES` to test different decay
cases (e.g. a near-mastered 0.9 notion). Set `TEARDOWN=False` to leave rows for manual
inspection in TablePlus.

**Important:** the tool calls `update_notion_rates_on_session_start` DIRECTLY (a unit
test of step 2), bypassing `process_notions_for_session_start` — so the orphan-cleanup
(step 1) does NOT run inside it. The tool's own SETUP clears rows first to mimic that.
In the real pipeline, orphan-cleanup runs before carry-forward, which is what prevents
duplicate NULL rows in production.

---

## 2. test_notion_seed.py — the new-user seed (step 6)

**What it tests:** `initialize_notions_for_new_user` on the NULL-marker model — it
creates score-0 rows with `session_id NULL`, and the idempotent guard prevents
re-seeding.

**What it does:**
1. Clears the test-user rows.
2. RUN 1: seeds from empty — expects score-0 NULL rows created.
3. RUN 2: seeds again — expects 0 (the `existing > 0` guard skips).
4. VERDICT + teardown.

**Run:** `python test_notion_seed.py`

**Set `USER_LEVEL` first** (top of file) to a `level_from` that actually has live
notions, or the seed returns 0 (nothing to seed). Find a good level:
```sql
SELECT level_from, COUNT(*) FROM brain_notion WHERE live = true
GROUP BY level_from ORDER BY level_from;
```

**A PASS means:**
- **run1 created rows > 0** — seed pulled notions at that level.
- **all rows session_id NULL** — NULL-marker write (backfilled at cycle 1 later).
- **all rows score 0** — seeded as "introduced, not yet practiced."
- **guard skipped re-seed** — RUN 2 created 0, row count unchanged.

**If run1 = 0:** no live `brain_notion` at that `level_from`. Adjust `USER_LEVEL` and
re-run (the tool prints this hint).

---

## What these tools do and don't prove

**They prove** each pipeline function works against the live DB at the unit level —
carry-forward, scoping, list, seed — and crucially that **history is protected** by the
`session_id IS NULL` scoping.

**They do NOT prove** the full integration — i.e. a real session start running the
whole flow together (`process_notions_for_session_start` → cycle building →
`start_new_cycle` cycle-1 backfill). The orphan-cleanup (step 1) and the cycle-1
backfill (step 5) are verified separately (orphan-cleanup: a TablePlus DELETE test;
backfill: a TablePlus UPDATE test). The natural final validation is a **real session
run**: start a session for the test user, reach cycle 1, and confirm in TablePlus that
the NULL rows flip to the real session_id at cycle 1, then a second session reads them
as the previous session.

---

## Quick cleanup (between manual experiments)

```sql
-- Clear all test-user notion rows (the tools also do this in teardown)
DELETE FROM session_notion WHERE user_id = 'D08BC99B-0996-4E2B-B4FB-80CF9E0B33DC';

-- See current state
SELECT notion_id, session_id, notion_rate, notion_priority_rate, notion_complexity_rate
FROM session_notion
WHERE user_id = 'D08BC99B-0996-4E2B-B4FB-80CF9E0B33DC'
ORDER BY session_id NULLS FIRST, notion_id;
```

Note: NULL session_id = the about-to-start session's rows; non-NULL = history.
