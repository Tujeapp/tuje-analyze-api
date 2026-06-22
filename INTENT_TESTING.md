# Intent System — Testing Notes

Companion to `TESTING_TOOLS.md`. Covers `test_intent_populate.py`, the local
diagnostic for the `session_intents` population path (intent-goal build, Chunk 2).

---

## ⚠️ Read this first — it WRITES to the database

Unlike `test_selection.py` and `diagnose_search.py` (both strictly read-only),
**`test_intent_populate.py` writes rows into `session_intents`** for the
configured user. That is the whole point — it proves population works — but it
means:

- **Only run it against a test user.** It is hardcoded to the test user
  (`D08BC99B-...`). Do not point it at a real user's id.
- The rows it writes are real placeholder rows (scores 0.00 / 0.00) — the same
  ones session setup would write. They persist after the run.
- It is a **throwaway-style diagnostic kept for convenience**, not part of the
  app. Never imported by production code.

---

## What it proves (and what it doesn't)

**Proves:** the session-setup intent population works end-to-end against the
live DB *without deploying* — `get_seen_intents` returns the user's recent
intents, and `populate_intents_from_seen` upserts them into `session_intents`
with placeholder scores, idempotently.

**Does NOT prove:** anything about *using* those rows to build an intent cycle —
that is the intent-goal selection branch (a later chunk). This script only
covers population.

It runs the **same two real functions** that session setup calls
(`session_calculations.get_seen_intents` and
`notion_management.populate_intents_from_seen`), so a pass here means the live
session-setup path (in `initialize_early_user` / `initialize_active_user`) will
behave the same once deployed.

---

## How to run

From the backend repo root, with the venv and env loaded:

```bash
cd ~/Desktop/tuje-analyze-api
source venv/bin/activate
set -a; source .env; set +a
python test_intent_populate.py
```

To test a different user, edit the `USER_ID` constant at the top of the script.
(Remember the case-sensitivity gotcha — `user_id` is stored case-inconsistently;
use the exact stored case. See R33 in the spec.)

---

## How to read the output

The script runs four steps and prints a verdict.

1. **STEP 1 — the seen-intents set.** What `get_seen_intents` returns for the
   user (its last-7-day rolling window). This is the input session setup would
   feed into population.
2. **STEP 2 — `session_intents` BEFORE.** The table contents for this user
   before populating, so you can see the delta.
3. **STEP 3 — first populate call.** Runs `populate_intents_from_seen`, prints
   how many it upserted and the resulting rows (intent_id, score, priority,
   `updated_at`).
4. **STEP 4 — second populate call (idempotency check).** Runs it again. The row
   **count must stay the same** (the `ON CONFLICT (user_id, intent_id)` updates
   rather than duplicates), and `updated_at` should advance.

**A healthy PASS looks like:** N rows after step 3, the *same* N after step 4
(no duplicates), all scores `0.00 / 0.00`, `updated_at` newer in step 4.

---

## Interpreting the cases

- **Rows appear, count stable across both runs → PASS.** Population works and is
  idempotent. This is the expected healthy result.
- **Empty seen set → 0 rows upserted.** **Not a failure.** It means the user has
  no intents in the last-7-day window *right now*. `get_seen_intents` is a
  rolling 7-day query, so if the user's intent-carrying activity has all aged
  past 7 days, there is simply nothing to populate. To get a non-empty test, the
  user needs a recent intent-carrying completion.
- **Row count grows between the two runs (e.g. N → 2N) → real problem.** The
  upsert is duplicating instead of updating — check the `ON CONFLICT` clause and
  that the `UNIQUE (user_id, intent_id)` constraint exists on `session_intents`.

---

## Placeholder scores (Option A) — why everything is 0.00

`intent_score` and `intent_priority_score` are written as `0.00` deliberately.
The real formulas are **deferred** (see §8 of
`TuJe_Session_RampUp_and_Cycle_Goal_Logic.md`): the intent score depends on the
vocabulary design (not yet built), and the intent priority score depends on the
user-goal / interest / level design (not yet finalised). Until those land, the
rows exist and function structurally, but the scores carry no meaning — so any
sort that orders by them is mechanically correct but not yet *intelligent*.

When §8 is designed, the scores become meaningful and a CHECK constraint bounding
their range should be added to `session_intents` at that time (the table is
intentionally permissive on score range for now, since the range isn't decided).
