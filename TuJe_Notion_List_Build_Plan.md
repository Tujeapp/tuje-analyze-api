# TuJe — Notion List Build Plan (carry-forward, decoupled calculate/persist)

**Status:** PIECE 2 COMPLETE — all 6 steps built and verified (see status block below).
Companion to `TuJe_Notion_Model_Redesign.md` (the model) and `NOTION_TESTING.md` (the
test tools). The NULL-marker approach replaced the in-memory decouple (a user can have
only one open session, so a session_notion row with session_id NULL = the about-to-start
session's row; backfilled at cycle 1).

**Goal:** get the **list of notions** working so a notion-goal cycle can be set. DONE —
the session-start notion pipeline produces a correct, history-protected list end-to-end.

---

## STATUS BLOCK (Piece 2 — all steps verified)

- **Step 1 — orphan cleanup** DONE/verified. process_notions_for_session_start top:
  DELETE session_notion WHERE user_id AND session_id IS NULL (clears stale NULLs before
  writes; protects history; makes NULL marker reliable).
- **Step 2 — carry-forward-new-rows** DONE/verified. update_notion_rates_on_session_start
  reads previous session (highest session_rank, completed), decays, INSERTs new
  session_id-NULL rows + carried introduction_date + reset counts; history preserved
  (0.50->0.15, 0.30->0.09 on real data).
- **Step 3 — priority/complexity scoping** DONE/verified. Both functions scope SELECT
  and UPDATE to session_id IS NULL — compute on current rows only, history untouched
  (proven via sentinel values 0.99/0.88).
- **Step 4 — list scoping** DONE/verified. get_top_notions_list scopes to
  session_id IS NULL — returns only current notions, sorted priority desc, complexity
  desc; no history leak.
- **Step 5 — cycle-1 backfill** DONE/verified. start_new_cycle (cycle_number==1):
  UPDATE session_notion SET session_id=<this session> WHERE user_id AND session_id IS
  NULL -> NULL rows become permanent history. Closes the lifecycle loop.
- **Step 6 — seed NULL-marker** DONE/verified. initialize_notions_for_new_user writes
  session_id NULL + dead ON CONFLICT removed (guard + orphan-cleanup prevent duplicate
  seeding). Seeds 5 score-0 NULL rows; guard skips re-seed.

**Test tools:** test_notion_carryforward.py (steps 2+3+4), test_notion_seed.py (step 6).
See NOTION_TESTING.md.

## REMAINING (post-Piece-2 roadmap)

1. **Full real-session integration run** — the 6 steps are UNIT-verified, not yet
   exercised together in one live session. Start a real session, reach cycle 1, confirm
   NULL rows flip to the session_id at cycle 1, and a second session reads them as the
   previous session. The natural final validation.
2. **§8 inverted Coefficient B** — decay currently uses the OLD buckets (observed steep:
   0.50->0.15). Implement the inverted/recalibrated buckets from the redesign doc §8,
   then validate on real data. (Also the passive/active rate->score rename +
   confidence-weighted formula, deferred from this build per Option 1.)
3. **Double-session guard** — the NULL-marker rests on one-open-session, currently
   unenforced. Orphan-cleanup protects Piece 2 meanwhile; a real guard is its own task.
4. **Moment 2 — per-interaction tracking** — increment passive/active counts during the
   session (passive buildable now via interaction_notion; active needs answer-notion
   detail). This raises seed rows above score 0 so they enter the list.
5. **Piece 4 — notion-goal cycle SEARCH** — the list is built but nothing consumes it for
   cycle selection yet. Build interaction_search_notion.py (separate file, story
   untouched) that takes the top notion(s) and finds interactions; once-per-subtopic
   ordering. Read LIVE interaction_search.py (project-knowledge copy is stale).

---

## (Original plan detail below — retained for reference)

**Goal:** get the **list of notions** working so a notion-goal cycle can be set —
without the invasive session-init reordering the naive approach would require.

---

## The key design insight — decouple CALCULATE from PERSIST

The naive carry-forward model ("create new session_notion rows at session start, stamped
with session_id") hits an ordering problem: at session start, notion processing may run
**before** the session row exists, so there's no session_id to stamp. Reordering the
init flow across 4 initializers is invasive and risky.

**The fix (Rémi's):** split the two concerns.
- **CALCULATE the carried-forward notion list in memory** at session start — pure, no
  writes, no session_id needed. This is what *drives the cycle*.
- **PERSIST the new session_notion rows later** — at first-cycle creation, where
  session_id is guaranteed to exist.

This mirrors the locked cycle architecture (Option B: compute the decision, persist when
the structure to hang it on exists). It removes the flow-reordering risk entirely.

---

## The session lifecycle (the model this serves)

1. **Initial (onboarding) session** → no session_notion saved.
2. **First regular session** (rank 1, all story cycles) → session_notion rows are BORN
   from interactions seen + answers given during the session (the *tracking* path).
3. **Rank >= 2, at session start:** read the **previous session's** session_notion rows;
   for each with score **> 0 and < 1**, create a **new** row for this session
   (carry-forward) and **decay-update** its score. Rows at exactly 0 or 1 are skipped
   (no new row). That decayed set = the notion list for cycle selection.

Two distinct write events on session_notion:
- **(a) start-of-session carry-forward-and-decay** — for the LIST (calculate in memory,
  persist at cycle 1).
- **(b) during-session tracking** — for the COUNTS (passive/active; Moment 2, built
  later; needs answer-notion detail).

---

## Discovery findings (live code, confirmed this session)

- **Current model is UPDATE-IN-PLACE.** `update_notion_rates_on_session_start`
  (notion_management.py L20-139) does `UPDATE session_notion SET notion_rate=...`
  per (user, notion). One row per user-notion, mutated each session. **No session_id
  column.** Conflicts with the new-rows-per-session lifecycle.
- **Constraint:** `unique_user_notion UNIQUE (user_id, notion_id)` — the ONLY thing
  enforcing one-row-per-user-notion. Must change to include session_id.
- **Only ONE `ON CONFLICT (user_id, notion_id)` references it** —
  notion_management.py L519, in `initialize_notions_for_new_user` (the seed). (L568 is
  `(user_id, intent_id)` on session_intents — different table, unaffected.)
- **`process_notions_for_session_start`** is called from 4 places in session_init.py
  (L80, 247, 384, 535 — brand_new / returning / early / active). It internally calls
  `update_notion_rates_on_session_start` (L635). **session_id is NOT passed** to these
  calls (and the session row may not exist yet at that point — hence the decouple).
- **The persist hook is clean:** `start_new_cycle` (cycle_manager/cycle_creation.py)
  has `session_id` in scope (used at L85, L94 when inserting session_cycle and the first
  session_interaction). It runs per cycle, so guard the notion persist with
  `cycle_number == 1` to run once per session.
- **`get_top_notions_list`** (notion_management.py ~L403-458) already builds a list
  (priority desc, complexity desc, excludes score 0/1). Will need to read THIS session's
  rows (filter by session_id) once rows are session-owned.
- **`expected_notion_id`** exists (active target); **`interaction_notion`** now exists
  and syncs (passive source) — verified in real data (INT202501300888:
  interaction_notion {NOT202408090927, NOT202408130245}, expected_notion_id same + a
  third).

---

## Build pieces (execute in order, verify each)

### Piece 1 — Schema (TablePlus) — DONE
Applied (TablePlus, not in a migration file — recorded here per R21):
```sql
ALTER TABLE session_notion ADD COLUMN session_id varchar;   -- matches session.id (varchar)
DELETE FROM session_notion;                                  -- clean start (was 5 obsolete rows, 1 user)
ALTER TABLE session_notion DROP CONSTRAINT unique_user_notion;
ALTER TABLE session_notion ADD CONSTRAINT unique_user_notion_session
    UNIQUE (user_id, notion_id, session_id);
```
Verified: only `unique_user_notion_session` remains; table empty (0 rows); `session_id
varchar` present.

**Deferred out of Piece 1 (the seed's session_id):** `initialize_notions_for_new_user`
(notion_management.py L465, called from the orchestrator L626) writes session_notion
rows but has NO session_id in scope (same timing problem as the decay). Its `ON CONFLICT
(user_id, notion_id)` (L519) and INSERT still need updating — but how it gets session_id
is the same question as Piece 2/3, so it's handled there, not in the schema step. Until
resolved, the seed would write NULL-session_id rows (unreadable by carry-forward).

**Consequence:** schema is ready but NOTHING writes valid session-stamped rows yet
(seed deferred, persist not built). Expected for a foundation piece.

**Follow-up:** once all writers stamp session_id, consider `ALTER ... session_id SET NOT
NULL` as a safety net (Postgres treats NULLs as distinct in unique constraints, so NULL
rows wouldn't dedupe).

### Piece 2 — Calculate the carried-forward list — DISCOVERY DONE, DECISION PENDING

**The assumption that didn't survive discovery:** the plan said "calculate the list in
memory, pure function, no writes." But the existing session-start pipeline
(`process_notions_for_session_start`, L586-647) is **write-then-read DB-coupled**:
1. `update_notion_rates_on_session_start` — UPDATEs notion_rate in place.
2. `calculate_notion_priority_rates` — reads rate, WRITES notion_priority_rate.
3. `calculate_notion_complexity_rates` — reads, WRITES notion_complexity_rate.
4. `get_top_notions_list` — reads all three back, sorts, returns.
So "calculate the *list* in memory" means either reimplementing priority/complexity
in-memory (duplication, drift risk) or restructuring the pipeline.

**The core tension (three constraints that pull against each other):**
- The notion **list is needed BEFORE cycle 1** (a rank-2 session's cycle 1 can be a
  notion cycle, needing the list to select interactions).
- **session_id is only reliably available AT cycle 1** (`start_new_cycle`) — the reason
  for the calculate/persist decouple.
- Want to **avoid reimplementing** priority/complexity (reuse existing functions) and
  **avoid the invasive session-init reorder**.

**Three approaches considered:**
1. **In-memory everything** — new function computes decay + priority + complexity in
   memory, returns sorted list, writes nothing; persist at cycle 1. *Keeps decouple
   pure, but duplicates priority/complexity logic.*
2. **Persist early** — write session-stamped rows at session start, reuse existing
   functions with a session_id filter. *No duplication, but needs session_id at session
   start (the timing problem).*
3. **Decay-in-memory, then reuse pipeline after persist** — Piece 2 = decay only
   (in-memory, small); persist at cycle 1; then existing priority/complexity/list run on
   persisted rows. *Smallest Piece 2, but priority/list then compute AFTER cycle 1 —
   too late for cycle 1's own selection. Circular.*

**Decision pending** — pick deliberately next session; the choice shapes Pieces 2-4.

### Piece 2 (ADOPTED APPROACH) — NULL-session_id marker, update one centralized function

**Key discovery — the pipeline is ALREADY centralized.** The four initializers
(brand_new / returning / early / active in session_init.py) all already call
`process_notions_for_session_start` (L80, 247, 384, 535) for notions, and it already
RETURNS `top_notions` in its result. The pre-cycle calc functions
(`calculate_top_session_mood`, `calculate_session_boredom_full`,
`calculate_mood_recommendation`, `calculate_modulo`) are already standalone functions the
initializers call. So the steps are already modular; the four initializers differ
*deliberately* by user type (brand_new hardcodes 0s; active computes from full history;
returning uses special boredom/modulo). **We do NOT need to refactor the four
initializers.** To change the notion calculation, change `process_notions_for_session_start`
(one place) — all four inherit it.

So Piece 2 = rewrite the notion path inside that one function (and the functions it
calls) to the carry-forward model, incrementally, one step at a time.

**The session_id-timing solution — Rémi's NULL-marker approach (ADOPTED, replaces the
in-memory decouple):** since a user can only have ONE open session at a time, a
session_notion row with `user_id` set and `session_id` NULL unambiguously means "the rows
for the session this user is about to start." So:

1. **Orphan cleanup (REQUIRED for safety):** at session-start notion processing,
   `DELETE FROM session_notion WHERE user_id = $1 AND session_id IS NULL` — clears any
   stale NULL rows from a failed/abandoned prior start, so the NULL rows always reflect
   THIS start.
2. **Carry-forward as new NULL rows:** read the **previous session's** rows (the user's
   most recent rows WITH a session_id, where 0 < score < 1), INSERT NEW rows with
   `user_id` + `session_id = NULL` + decayed scores.
3. **Priority / complexity / list** run on these new rows (found by `user_id` +
   `session_id IS NULL`) — existing functions, adjusted to that filter. The list is
   available immediately for cycle 1 selection (no in-memory threading needed — it's in
   the table, just not yet session-stamped).
4. **Backfill session_id at cycle 1:** in `start_new_cycle` when `cycle_number == 1`,
   `UPDATE session_notion SET session_id = $1 WHERE user_id = $2 AND session_id IS NULL`.

**Clean separation:** `session_id IS NULL` = the about-to-start session's rows;
`session_id IS NOT NULL` = history (previous sessions, backfilled when they were created).
Carry-forward reads the NOT-NULL history; the list reads the NULL current rows.

**Why this beats the in-memory decouple:** it reuses the existing write-then-read pipeline
(which already writes rows and returns the list) instead of reimplementing
priority/complexity in memory. Smaller change, plays to the pipeline's existing shape.

### `modulo` and the other pre-cycle values
`modulo` (session_init.py L72/244/359/530 — hardcoded for brand_new/returning, computed
via `calculate_modulo` for early/active) plus streaks, boredom, mood, level direction are
all already computed before cycle 1 in each initializer. They are NOT broken — just
confirming the full pre-cycle-1 set is: top_session_mood, streak30, streak7,
session_boredom, mood_recommendation, modulo, + the notion steps (update score, priority,
complexity, list). The notion steps are the only ones changing (Piece 2); the rest already
work.

### Incremental step order inside `process_notions_for_session_start` (and callees)
1. Orphan cleanup (DELETE NULL rows for user).
2. Rewrite `update_notion_rates_on_session_start`: update-in-place → read previous
   session's rows, INSERT new NULL-session_id rows with decayed scores.
3. Adjust `calculate_notion_priority_rates` / `_complexity_rates` to operate on the new
   NULL rows.
4. Adjust `get_top_notions_list` to read the NULL rows (current session).
5. Backfill session_id at cycle 1 (`start_new_cycle`, cycle_number == 1).
6. The seed (`initialize_notions_for_new_user`) likewise writes NULL-session_id rows,
   backfilled at cycle 1 — resolves the deferred seed-session_id question the same way.
Each step verifiable; test with crafted previous-session rows.

### SEPARATE TASK (not part of Piece 2) — double-session guard
The NULL-marker safety rests on "one open session per user," which is currently NOT
enforced — there is no guard against a user starting two sessions. The orphan-cleanup
(step 1) protects the notion rows specifically, so Piece 2 is safe without the guard. But
a proper **double-session guard** (session creation refuses/reuses if the user already has
an active session) is genuinely needed (two open sessions would break far more than
notion) and should be its own task. Logged here so it isn't lost.

### Piece 3 — Persist at cycle 1
- In `start_new_cycle`, when `cycle_number == 1`, write the carried-forward rows to
  session_notion stamped with this session_id. Runs once per session, session_id
  guaranteed.

### Piece 4 — Wire the list into the notion-goal cycle
- The notion interaction search: new file `interaction_search_notion.py` (separate-file
  architecture; leave story's `interaction_search.py` untouched). Consumes the list;
  searches interactions whose notions match the top notion(s); per *Details of logic*:
  subtopic list + interactions whose expected/interaction notion contains the top
  notion, >=7 total, once-per-subtopic ordering.
- Branch in `start_new_cycle`: `cycle_goal == "notion"` -> notion search; else existing.
- **Read LIVE interaction_search.py** to mirror conventions (project-knowledge copy is
  STALE: live uses `i.boredom`, `bit.name`, 4-arg `get_combination`).

### Later — Moment 2 tracking (separate)
- Increment passive/active counts during the session (passive side buildable now via
  `interaction_notion`; active side needs the answer's produced-notions detail, deferred
  by Rémi for now — "the answer returns notions, wire specifics later").

---

## Sequencing honesty

- Piece 2 (calculate) is **low-risk** and doesn't touch session-init ordering — it's the
  real "update the list" deliverable.
- The carry-forward reads the *previous* session's rows, which are written by the
  *tracking* path (event b) / the seed. Until Moment 2 tracking exists, carry-forward
  carries **seed rows** (and whatever rank-1 story cycles happen to write). So the list
  is correct in *mechanism* immediately; correct in *data* once tracking lands. Build
  structure first, enrich after (the pattern that's worked).
- Rank-1 = all story (already in `calculate_cycle_goal`), so the notion list is only
  *consumed* for cycle selection from rank 2 — no empty-history edge case.

---

## Open / decide at build time
- session_id column type (match the `session` table's id type).
- Transition for existing session_notion rows (backfill vs clean start).
- Where exactly the in-memory list lives (SessionContext field vs returned-and-threaded).
- Piece 4's notion-search shape: confirm against *Details of logic* notion section
  (subtopic-list + notion-match, >=7 total, once-per-subtopic ordering) — and resolve
  the §8 inverted Coefficient B (already designed in the redesign doc) when the score
  feeds in.
