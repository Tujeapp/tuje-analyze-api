# TuJe — Manual Testing Tools (Session Setup & Selection)

*A toolkit for testing the adaptive session-setup and interaction-selection logic against
real DB content, using a controlled test user. All tools verified working as of this writing.*

---

## What this is for

The adaptive engine calculates a session's setup (boredom, level, mood, modulo) from the
user's history, then uses those values to build and order each cycle's interactions. To test
that logic we need to **control the user's state** and **observe what the engine does** — without
grinding through full 21-interaction sessions every time.

These tools let you:
- Inject a session's setup values directly (bypass deriving them from history), and
- Manufacture a prior completed session so history-dependent calculations have something to read.

**Test user:** `d08bc99b-0996-4e2b-b4fb-80cf9e0b33dc`
**DB:** Render Postgres via TablePlus (External Database URL, `.oregon-postgres.render.com`)
**API base:** `https://tuje-analyze-api.onrender.com`

---

## The core mechanism (PROVEN)

`start-session` and `start-cycle` are **separate API calls**. `start-session` computes the
session setup and **writes it to the `session` row**. `start-cycle`'s cycle calculation
(`calculate_cycle_boredom`, `calculate_cycle_level`) **reads those values back from the row**.

Therefore: editing the `session` row **between** the two calls changes what the cycle
calculation sees. Verified — editing `session_boredom = 0.80` produced `cycle_boredom: 0.8`
in the start-cycle response.

> **Why this matters:** it means we can override setup values with a simple SQL `UPDATE`
> on the row — no code change needed. The window is "after start-session, before start-cycle."
> Use `/docs` or curl (NOT the simulator) for this, because the simulator fires both calls
> back-to-back with no editable gap.

---

## The two edit-points (DO NOT CONFUSE THESE)

The single most important distinction in this toolkit:

| Edit point | Which row | Drives | Tool |
|---|---|---|---|
| **Current session** | the session just created by start-session | `session_boredom` → cycle-1 boredom | Tool 2 |
| **Previous session** | an earlier *completed* session | `session_level`, `session_level_direction`, `session_score`, `session_mood`, `session_boredom` → the NEXT session's setup calc | Tool 4 |

**Critical trap:** `session_level` / `session_level_direction` on the *current* session do
**NOT** affect cycle-1 level. `calculate_cycle_level` (cycle 1) reads the *previous completed
session*, not the current row. So **level is set via Tool 4, not Tool 2.** Setting level in
Tool 2 and concluding "level does nothing" would be a false negative.

---

## The Tools

### Tool 1 — Create a new session

```bash
curl -s -X POST https://tuje-analyze-api.onrender.com/api/session-adaptive/start-session \
  -H "Content-Type: application/json" \
  -d '{"user_id":"d08bc99b-0996-4e2b-b4fb-80cf9e0b33dc","session_type":"short","session_mood":"effective"}' \
  | python3 -m json.tool
```
Returns the `session_id` plus the computed setup baseline (`session_boredom`, etc.).
Note the `session_id` — Tools 2 and 3 need it. Always use a FRESH session (don't reuse, or
Tool 3 hits the `unique_session_cycle_number` constraint).

### Tool 2 — Override the CURRENT session (between Tool 1 and Tool 3)

```sql
-- Proven effective on cycle-1: session_boredom.
-- session_level / direction here do NOT affect cycle-1 (use Tool 4 for level).
UPDATE session
SET session_boredom = 0.80
WHERE id = '<session_id from Tool 1>';
```

### Tool 3 — Create the cycle (observe the result)

```bash
curl -s -X POST https://tuje-analyze-api.onrender.com/api/session-adaptive/start-cycle \
  -H "Content-Type: application/json" \
  -d '{"session_id":"<session_id>","cycle_number":1,"session_mood":"effective"}' \
  | python3 -m json.tool
```
Returns `cycle_level`, `cycle_boredom`, `cycle_goal`, `subtopic_id`, `first_interaction_id`,
`first_brain_interaction_id`. Compare against what you injected and predicted.

### Tool 4 — Force-complete / author a PRIOR session state (use BEFORE Tool 1)

Converts an existing session row into "the designated past" that the next session reads.

```sql
-- Scope HARD to one session id. Never bulk-update by user_id alone.
UPDATE session
SET status                  = 'completed',
    completed_at            = NOW(),       -- backdate for streak/date tests: NOW() - INTERVAL '2 days'
    session_nbr_cycle       = 3,           -- MUST be correct: expected_score = nbr_cycle*7*100 (3 -> 2100)
    session_score           = 1680,        -- SCALE IS 0..(nbr_cycle*700). 1680/2100 = 0.80 rate. NOT 0-1!
    session_level           = 300,         -- -> next session's cycle-1 level
    session_level_direction = 'down',      -- 'up'|'stable'|'down' -> boredom coef + cycle-1 level
    session_mood            = 'effective', -- -> top-mood + boredom coef
    session_boredom         = 0.40         -- -> next session's boredom (coefficient applied to THIS value)
WHERE id = '<session_id>';
```

### Tool 5 — Inspect "what past will the next session read?"

```sql
SELECT id, completed_at, session_rank, session_nbr_cycle,
       session_score, session_level, session_level_direction,
       session_mood, session_boredom
FROM session
WHERE user_id = 'd08bc99b-0996-4e2b-b4fb-80cf9e0b33dc'
  AND status = 'completed'
ORDER BY completed_at DESC
LIMIT 1;
```
Mirrors the exact query the engine uses. The row this returns is the one the next session
will read. Zero rows = no history (setup calc falls back to defaults; cycle-1 level = user level).

---

## Order of use

`session_score` / `session_level` / mood / etc. on the *new* session are **derived from the
previous completed session**. So:

- **Testing level / mood / boredom-from-history / non-story goals?**
  → **Tool 4 first** (author the past), then Tool 1 (reads it), then 2/3.
- **Testing only "does boredom flow into cycle selection"?**
  → No past needed. Tool 1 → Tool 2 (inject boredom) → Tool 3.

**Which past gets read:** the engine orders by `completed_at DESC LIMIT 1`. Tool 4 must set
`completed_at = NOW()` so its session is the most recent — otherwise an older completed
session may be read instead. Use Tool 5 to confirm.

---

## Gotchas (each one has burned us or nearly did)

1. **`session_score` scale is 0..(nbr_cycle×700), NOT 0–1.** For a rate of 0.8 on a 3-cycle
   session, score = 1680. Setting `0.8` yields a rate of ~0.0004 while looking plausible.
2. **Tool 2 cannot set cycle-1 level** — that reads the previous session (Tool 4).
3. **Streaks cannot be faked in one row.** `streak7`/`streak30` are recomputed from the count
   of completed sessions across distinct `completed_at` days. Faking a streak needs MULTIPLE
   Tool-4 rows with backdated `completed_at`.
4. **`session_rank ≥ 2` is required for non-story cycle goals** (rank 1 forces all cycles to
   story). Rank = count of prior sessions + 1. (Whether the rank count includes force-completed
   rows the way you expect is NOT yet verified — confirm before relying on goal experiments.)
5. **Use a fresh session per Tool-1 run** — reusing one with an open cycle hits the
   `unique_session_cycle_number` constraint.
6. **Use `/docs` or curl, not the simulator,** for the Tool 1→2→3 loop — the simulator gives
   no editable gap between the two calls.

---

## Known limitation: the cycle-calc is the SIMPLIFIED version

`cycle_manager/cycle_calculations.py` (`calculate_cycle_level`, `calculate_cycle_boredom`,
`calculate_cycle_goal`) is explicitly a **simplified placeholder**, not the full algorithm
from *Details of logic of session* / the ramp-up doc. It uses crude ±50 level steps and a
fixed goal-rotation. So:

- These tools faithfully test **how setup values flow into the cycle calc** and **selection**.
- They do **NOT** test the *designed* cycle-level/boredom/goal algorithm — that isn't built yet.
- Don't read "cycle level went X" as "the designed algorithm did X." It's the placeholder.

The session-*setup* calc (`session_calculations.py`: boredom, top-mood) appears faithful to spec.

---

## Cleanup procedure (keeping the DB un-messy)

Test sessions accumulate fast (orphan active sessions — see spec R27). To clean up while
keeping chosen sessions, delete **children before parent** (no ON DELETE CASCADE; FK is
restricted). Always **preview with a SELECT first**, then delete in order:

```sql
-- A: answers, B: interactions, C: cycles, D: sessions  (run in this order)
DELETE FROM session_answer      WHERE session_id IN (SELECT id FROM session WHERE id NOT IN ('<keep1>','<keep2>'));
DELETE FROM session_interaction WHERE session_id IN (SELECT id FROM session WHERE id NOT IN ('<keep1>','<keep2>'));
DELETE FROM session_cycle       WHERE session_id IN (SELECT id FROM session WHERE id NOT IN ('<keep1>','<keep2>'));
DELETE FROM session             WHERE id NOT IN ('<keep1>','<keep2>');
```

- Hardcode the keeper ids (don't use a recomputed subquery — it can resolve to a different
  row than you previewed).
- `session_notion` is keyed by `user_id`/`notion_id`, NOT `session_id` — it is NOT touched by
  the above, so notion-rate state survives a session cleanup.
- This is irreversible on live data. Preview the kill list first; confirm keepers are absent.

---

## Future tool (designed, not built): selection trace script

A read-only Python script that connects to the real Render Postgres, loads a real
`SessionContext` for the test user, and calls `find_best_subtopic_with_fallback` /
`select_cycle_interactions` directly — printing the FULL trace the curl loop hides:
candidate pool size, each candidate's combination value, sort order, the final 7 and why,
and which fallback phases fired. Real data (no illusion), full intermediate visibility.
Read-only (selection code only SELECTs). Not yet built.
