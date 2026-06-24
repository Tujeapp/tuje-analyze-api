# TuJe — Notion List Build Plan (carry-forward, decoupled calculate/persist)

**Status:** Build plan, ready to execute. Companion to `TuJe_Notion_Model_Redesign.md`
(the model spec). This doc is the *how-to-build-the-list* plan, worked out through live
discovery. Not yet started.

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

### Piece 1 — Schema (TablePlus)
- `ALTER TABLE session_notion ADD COLUMN session_id varchar;` (match session id type)
- Drop `unique_user_notion`; recreate as `UNIQUE (user_id, notion_id, session_id)`.
- Update the seed's `ON CONFLICT (user_id, notion_id)` (notion_management.py L519) to
  `(user_id, notion_id, session_id)`, and add session_id to that INSERT (L514-518).
- **Transition note:** existing rows have no session_id. Either backfill, or treat as a
  clean start (the carry-forward only works forward from the first session that writes
  session-stamped rows). Decide at build time.

### Piece 2 — Calculate the carried-forward list (in memory, pure)
- New function: read the **previous session's** session_notion rows (0 < score < 1),
  apply the decay (reuse `_calculate_coefficient_a` / `_calculate_coefficient_b`),
  return the carried-forward, decayed notion list. **No writes. No session_id needed.**
- "Previous session's rows" = rows whose session_id = the user's last completed session.
  (The decay fn already finds the last completed session, L64-75, for coefficient data —
  reuse that to know which session's rows to carry forward.)
- This *is* "update the list." It can drive the cycle immediately.
- Likely lives on / near SessionContext so both cycle-building and the persist hook can
  reach it.

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
