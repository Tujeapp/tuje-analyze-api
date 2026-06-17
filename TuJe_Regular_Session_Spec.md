# TuJe — Regular Session System — Build Specification

**Status:** Phase 1 in progress. Backend chunks 0, 1a, 1b, 1c, 3 complete and deployed to Render. R8 fixed today (notion_management.py column renames). iOS chunk structurally complete: mood-selection screen built, central button rewired, SessionView/SessionViewModel adaptive mode added, picker relocated to HomeView dev button, video-unavailable fallback. Picker regression test passed; adaptive end-to-end test BLOCKED on backend schema-vs-code drift in non-brand_new code paths (early_user → process_notions_for_session_start successful after R8, then crashes on session.created_at column not existing). Next session's first task: schema-vs-code drift audit (Phase 1 live schema inventory, Phase 2 code reference inventory) before any further iOS testing.
**Last updated:** Conversation of June 2026.
**Scope:** The core plumbing of the everyday adaptive learning session a user gets after onboarding — session setup, the adaptive interaction loop, cycle open/close, and session close. **Phase 1 is story-only.** Out of scope for now: session UI/visual design, extra buttons, nice-to-haves.

> This is a living document. It is updated via a precise Claude Code edit as each chunk completes, so the plan, milestones, and decision log stay captured in one place. Each chunk **opens with its own read-only discovery** (read the relevant code in full before designing against it) — the summaries here are from the initial discovery pass and are not a substitute for reading the actual function bodies at build time.

---

## 1. What a regular session is

- **Entry point:** the HomeView bottom-bar central button, only after onboarding is complete.
- **Structure:** 1 session = 3 cycles; 1 cycle = 7 interactions.
- **Adaptive, not a fixed playlist:** the next interaction is chosen from the user's performance as they go (see Decision 2 — fixed candidate pool, dynamic next pick).
- **Distinct from the initial/onboarding session,** which is template-driven and already built.

### Lifecycle ↔ logic-doc mapping

The six lifecycle phases map onto the seven numbered sections of `Details_of_logic_of_session`:

| Lifecycle phase | Logic-doc section |
|---|---|
| Session setup | §1 (set new session) + §2 first-cycle branch + §3 first interaction |
| Next-interaction calc (adaptive step) | §3 "set next interaction", fed by §4 (interaction score) + §5 (end interaction) |
| Cycle close | §6 (end cycle) |
| Cycle open (cycles 2–3) | §2 not-first-cycle branch + §3 first interaction |
| Session close | §7 (end session) |
| Return to HomeView | frontend |

---

## 2. Current state of the codebase (from discovery)

### The adaptive engine already exists — but is dead code

The full server-authoritative adaptive pipeline is written and wired together, sitting behind an **unmounted router**:

- `session_management_router.py` — adaptive `POST /start-session`, `POST /start-cycle`, `GET /session/{id}`.
- `user_state.py` — `detect_user_state()` (brand_new / early / active / returning).
- `session_init.py` — four initializers (brand_new, early, returning, active).
- `session_calculations.py` — top mood, session boredom, mood recommendation, modulo, seen intents/subtopics.
- `cycle_manager/` — `cycle_creation` (`start_new_cycle`, `advance_to_next_interaction`), `cycle_calculations` (`calculate_cycle_level/boredom/goal`, `interaction_user_level`), `interaction_selection` (`select_cycle_interactions`, `select_first_interaction_story`, `select_next_interaction`), `cycle_completion` (`complete_cycle`, `update_cycle_level_direction`).
- `interaction_search.py` — `find_best_subtopic_with_fallback`, `search_interactions` (filters to interactions whose linked notions the user has mastered).

### Why it's dead

In `main.py`, line 21 (`from routers.session_router import router as session_router`) rebinds the same name used on line 20 for the adaptive router. Both mounts at lines 84–85 therefore point at the **CRUD router** (`routers/session_router.py`); line 85 is a redundant duplicate of line 84. The adaptive `start-session` / `start-cycle` are never mounted.

### What is actually live at `/api/session`

The **CRUD router** (`routers/session_router.py`) — a thin-server design whose `start-cycle` takes `subtopic_id` and `cycle_level` as **client-supplied inputs** and does no adaptive calculation server-side. This is the opposite of what we want (Decision 1). Its genuinely useful non-adaptive endpoints — `start-interaction`, `submit-answer`, `record-hint`, the `GET` reads — we **keep and reuse**. Also live: `complete_interaction_router.py` at `/api/session` (`POST /complete-interaction`) with its own **legacy random next-interaction logic** — a collision risk (see Risks).

### Scoring already matches the logic doc

`session_management/scoring_service.py` `calculate_interaction_score()` implements §4A (gross score = 100 first attempt else prior; coefficient `((answer_optimum/interaction_optimum) + (answer_optimum/cycle_level)) / 2`), plus button/timing variants and `bonus_malus_service`. Phase 1 **consumes** this; it is not rebuilt.

### Schema (live, confirmed) — and the gaps

Present and rich: `session` has `session_mood`, `session_level`, `session_boredom`, `streak7/30`, `modulo`, `top_session_mood`, `mood_recommendation`; `session_cycle` has `cycle_goal`, `cycle_level`, `cycle_boredom`, plus `template_interaction_ids VARCHAR[]` (initial-session pattern). Gaps that phase 1 must close:

- `session_cycle` — no `cycle_level_direction`, no `cycle_rate`, no persisted **candidate pool**.
- `session_interaction` — no `interaction_user_level`, no `interaction_boredom`.
- **Notion data model** — `brain_notion` NOT FOUND; `session_notion` has only `notion_rate` (no passive/active rate, weightiness, introduction date). This blocks the notion **goal** (phase 2) *and* the notion-rate **update** calcs in §1G and §5A. See Risk R3.

---

## 3. Architecture decisions (see full Decision Log, §6)

1. **Server-authoritative.** All session state in Postgres; iOS renders. (Confirmed by the build; matches intent.)
2. **Fixed candidate pool, dynamic next pick (Option B).** One heavy search at cycle open; persist the pool; pick the next interaction from it using freshly-updated state. No mid-cycle re-search.
3. **Phase 1 is story-only.** Cycle goal hardcoded to `'story'`; goal selection (§2B), list-of-notions sort (§1 H–J), and intents-seen are skipped until later phases.
4. **Wiring: Option 1 (surgical).** Mount the adaptive router at a distinct prefix; leave CRUD where it is. Promote to canonical `/api/session` later (chunk 6), only once the lifecycle is proven.

---

## 4. Phase 1 build plan — chunk by chunk

Each chunk is independently testable and ordered by dependency. **Schema changes are deliberately spread across chunks 2–4, not front-loaded** — each chunk adds only the columns it needs, run section-by-section in TablePlus. Every chunk begins by reading the relevant code in full (discovery), then builds, then tests before moving on.

### Chunk 0 — Make the adaptive flow reachable
- Rename the adaptive import (e.g. `adaptive_session_router`); mount at `/api/session-adaptive`. Remove the duplicate CRUD mount (line 85).
- Discovery within this chunk: confirm whether CRUD `submit-answer` / scoring assumes the CRUD `start-cycle` ran (sets `subtopic_id` / `cycle_level` a particular way). The answer may pull chunk 6 forward.
- **Test:** adaptive `POST /api/session-adaptive/start-session` returns 200 (was 404); CRUD endpoints unchanged.

### Chunk 1 — Session setup runs end-to-end (story-only) — *highest risk*
- First real execution of `detect_user_state` → `session_init` → §1 calculations (mood, streaks, session boredom, modulo, mood recommendation). Skip §1 H–J (notion sort) and intents-seen.
- Resolve Risk R3 here (notion-rate updates): confirm what `notion_management.py` does and whether it touches the missing fields; default is to **defer notion-rate writes to phase 2** (mastery filter still reads existing rates).
- **Test:** a real user with history hits `start-session`; inspect the `session` row — every computed field populated and sane.
- **Natural stopping point to reassess** before continuing.

### Chunk 2 — Cycle open, first cycle (story)
- `start_new_cycle` → `find_best_subtopic_with_fallback` → `calculate_cycle_level/boredom`; goal hardcoded `'story'`.
- **Schema:** persist the candidate pool. Proposed: `session_cycle.candidate_pool_ids VARCHAR[]` (parallels existing `template_interaction_ids`). This is the Option B persistence + the resumability fix in one.
- **Test:** `start-cycle` returns a first interaction; pool is in the DB; cycle-row fields correct.

### Chunk 3 — The interaction loop (the adaptive heart)
- `submit-answer` → score (existing) → complete interaction → **pick next from the persisted pool using fresh state** (`select_next_interaction`, combination sequencing).
- **Schema:** `session_interaction.interaction_user_level INTEGER`, `interaction_boredom NUMERIC`.
- Decide here how deep to take §5 end-interaction (speaking/comprehension/accuracy rates feed `interaction_user_level`); keep minimal for first pass if the inputs aren't all available.
- **Test:** answer 7 interactions; each next pick reflects the prior score; cycle flags complete at 7.

### Chunk 4 — Cycle close + auto-open next cycle
- §6: `cycle_rate`, cycle boredom average, `cycle_level_direction`; then auto-open cycles 2 and 3. Fixes the "orchestrator never opens the next cycle" gap.
- **Schema:** `session_cycle.cycle_level_direction VARCHAR`, `cycle_rate NUMERIC`.
- **Test:** completing cycle 1 closes it and opens cycle 2 with recalculated level/boredom.

### Chunk 5 — Session close + return to HomeView
- §7: session score, session level, session level direction; auto-fire after cycle 3. Fixes the "no session-level auto-completion" gap.
- **Test:** completing cycle 3 closes the session and returns the HomeView signal.

### Chunk 6 (late, optional) — Promote adaptive router to canonical `/api/session`
- Mount adaptive at `/api/session`; retire CRUD **lifecycle** endpoints (`create-session`, CRUD `start-cycle`, `complete-cycle`, `complete-session`) while **keeping** the reused non-adaptive ones. Removes the iOS prefix seam from Decision 4.
- Done only once the lifecycle is proven end-to-end.

---

## 5. Risks & open items

- **R1 — Cold code, first run (high).** The adaptive pipeline has never executed end-to-end. Chunk 1 is where failures will concentrate. Treat reaching the end of chunk 1 cleanly as the first reassessment gate.
- **R2 — Legacy completion collision (medium).** `complete_interaction_router.py` is live at `/api/session` with its own random next-interaction and 3-cycle completion logic. Chunks 3–5 must ensure iOS calls the adaptive completion path and the legacy one cannot interfere. Candidate for retirement in chunk 6.
- **R3 — Notion data-model gap (medium, scoping).** Missing `brain_notion` and `session_notion` fields block notion-rate updates in §1G and §5A, not just the notion goal. **Recommended default:** defer all notion-rate *writes* to phase 2 alongside the data model; phase 1 reads existing rates for the story mastery filter. Confirm in chunk 1.
- **R4 — Pool persistence schema choice.** Array column on `session_cycle` vs. a separate pool table. Recommended: array column (consistency with `template_interaction_ids`). Revisit only if the pool needs per-item metadata.
- **R5 — iOS prefix seam.** Until chunk 6, iOS calls `/api/session-adaptive/*` for lifecycle and `/api/session/*` for `submit-answer` etc. Document this for the frontend work.
- **R6 — user_id type mismatch (medium, latent).** `brain_user.id` is `uuid`; `session.user_id` (and likely session_cycle/session_interaction user_id columns) are `varchar`. UUIDs written as varchar aren't normalized, so casing differences (observed: same UUID stored both upper- and lower-case) can cause silent user-history join misses — a returning user could be mis-detected as brand_new. Audit and normalize before chunk 1c's history-dependent queries rely on user_id joins.
- **R7 — chunk 1 routing now load-bearing for crash-safety.** Per the Option A decision, the first regular session must route to the seed path. Because we write ONLY session_level at initial close (not session_nbr_cycle etc.), the initial session row still has NULL columns that the early/active calculators would crash on (None * 7 * 100). Fix 1 routing is therefore the sole protection against those crashes — chunk 1b testing must explicitly verify the calculators are never reached for an initial-only user.
- **R8 — Notion pipeline column mismatches (FIXED TODAY).** Five column renames applied in notion_management.py: `bn.notion_weightiness` → `bn.weightiness` (3 occurrences), `bn.notion_name` → `bn.name_fr` (1), `bn.notion_level_from` → `bn.level_from` (1), plus matching Python row[...] readers updated. Discovered via iOS test today. Surfaces in early_user / non-brand_new sessions.
- **R9 — Cold-code-vs-live-schema drift (general, applies to remaining chunks).** Chunks 1a/1b surfaced ~10 separate code-vs-schema mismatches: missing columns (`created_at` on session), wrong column names in `brain_notion` reads, function signature mismatches, and multiple unhandled NOT NULL constraints (`session_type`, `expected_cycles`, etc.). The pattern: cold code was written against an imagined schema looser than what's deployed. Expect similar density in chunks 1c–5. Tactic established: when a function accumulates many small fixes (≥3), surgical rewrite using the live schema is faster than continued patching.
- **R10 — iOS central button currently triggers a subtopic/interaction picker panel, not a regular session.** Migration needed once chunk 1 is complete: central button should call adaptive `start-session`. The picker panel should be preserved (it's useful for content-specific testing) but relocated, e.g. to a developer/debug area. Constraint on chunk 6: if/when CRUD lifecycle endpoints are retired, verify the picker panel's CRUD endpoint calls (which already exist) still resolve, or migrate them too.
- **R15 — Decimal × float arithmetic drift (general).** Postgres `numeric` columns return as Python `Decimal` via asyncpg; multiplying by a Python `float` raises `TypeError`. Surfaced in chunk 3 at `cycle_calculations.py:150` (`cycle_boredom * coefficient`) — fixed with `float()` conversion at the use site. Latent risk anywhere code does arithmetic on a value pulled from a numeric column without converting at the read site. Future hardening: standardize on `float()` conversion at all `fetchrow`/`fetchval` reads of numeric columns, rather than at use sites. Early-path float() on streak7/streak30 folded into commit 6a8afb9.
- **R16 — Cycle-goal rotation is a placeholder for session_rank ≥ 2.** The current `calculate_cycle_goal` falls through to a hardcoded `{1: story, 2: notion, 3: story, ...}` rotation for sessions beyond the first. Per ramp-up doc §6, the real algorithm involves cycle-boredom bands, the last cycle's goal, and three goal-usage scores over a 7-day window — none of which are implemented yet. Affects session_rank ≥ 2 only; safe for the current scope.
- **R17 — Half B's cycle-completion + next-cycle-open is not atomic.**
- **R18 — Casing inconsistency for session_mood strings.** brain_session_mood.name stores capitalized strings ("Effective", "Cultural", etc.). helpers.py:get_mood_types uses lowercase keys and calls .lower() on the input, papering over the mismatch. StartSessionRequest.session_mood is unvalidated str. The system currently works because iOS will pass whatever it received from the mood-recommendation endpoint (capitalized) and helpers lowercases it. Deferred consistency pass should pick a canonical casing across DB, helpers, and request validation. Until then, treat capitalized strings (matching brain_session_mood.name) as the canonical wire format for session_mood. The richer `complete_cycle` commits cycle-N's state, then the auto-open of cycle-(N+1) runs as a separate sequence. If the auto-open fails (e.g., `InsufficientInteractionsError`, or another bug surfacing), cycle-N stays committed but cycle-(N+1) is not created — iOS sees a 500 with no recovery path. Recovery today is a manual `start-cycle` call. Production hardening should either wrap Half B in a single transaction or build an idempotent "session is mid-progress, last cycle done, open the next if not done" recovery in `start-cycle`.
### R19 — Schema-vs-code drift audit (OPEN, in progress)
Two sources of truth only: live Postgres (Render) and raw-SQL column references in
backend Python. No migrations layer exists (see R21), so there is no third reference.
Trigger: early_user / returning_user session-adaptive paths crash on drifted columns
that the brand_new path short-circuits past. Confirmed drift so far: R15 (Decimal×float),
R8 (notion_management column renames, fixed today), R20 (session.created_at).
Method: Phase 1 = information_schema column inventory of public schema; Phase 2 = grep
asyncpg SQL literals + dynamic-query pass, cross-reference against Phase 1. Audit is
read-only; fixes applied as one coordinated batch afterward, not bug-by-bug.

### R20 — session.created_at: nonexistent column (FIXED)
Symptom: POST /api/session-adaptive/start-session →
"column \"created_at\" of relation \"session\" does not exist".
Code writes session.created_at on session insert; live `session` table has no such column.
Correct column TBD by Phase 1 (candidates: started_at / created_time / inserted_at / none).
Fix folded into the R19 coordinated batch, not patched standalone.
FIXED — commit 6a8afb9, deployed Render. created_at dropped from 3 session_init INSERTs;
get_session_status SELECT aliased started_at AS created_at. Verified early_user via /docs
(local + Render) and on simulator (decodes clean, advances to start-cycle).

### R21 — No migrations source of truth (OPEN, post-fix hardening)
Live DB is hand-migrated via TablePlus throughout project history; repo has no Alembic,
schema.sql, or CREATE TABLE files. Consequence: no audit trail of column add/rename/remove,
which is the mechanism by which R8/R15/R20-class drift accumulates invisibly. Proposed
remedy: adopt Alembic, or at minimum maintain a checked-in schema.sql regenerated after each
TablePlus change. Out of scope for the immediate audit; addresses the root cause R19 only
patches the symptoms of.

### R22 — early/returning/active session INSERTs omit NOT NULL columns (FIXED)
session_init.py INSERTs in initialize_early_user (L271), initialize_returning_user (L397),
and initialize_active_user (L545) omit session_type, expected_cycles, expected_total_score —
all NOT NULL with no default on live `session`. Masked by the R20 created_at parse error,
which fires first. brand_new (L105) is the correct template; the other three are stale,
predating the columns being made NOT NULL (consequence of R21 — no migration trail).
Fix: align all three to the brand_new column set. Surgical rewrite, not patch (Decision 5).
Fold in (R15 family): early path passes raw Decimal streak7/streak30 into
calculate_mood_recommendation (L239) and calculate_modulo (L244); active wraps them in
float() (L512/517). Align early to active while rewriting.
FIXED — commit 6a8afb9, deployed Render. session_type/expected_cycles/expected_total_score
added to early/returning/active INSERTs; started_at/last_activity_at set explicitly.
Verified early_user (row values short/3/3/2100). NOTE: returning_user (Edit 2) verified by
INSPECTION ONLY — no 30+-day-inactive path was executed.

### R23 — session cycle-count stored redundantly across 4 columns (OPEN, refactor post-audit)
`session` encodes one fact (cycle count) in session_type, session_nbr_cycle, expected_cycles,
and expected_total_score (= count × 700). session_type is a label for the count, consumed only
via get_cycle_count(); no behavioral reads confirmed yet (pending grep). Denormalization is the
root cause of R22 (INSERTs must keep 4 columns in sync; 3 fell out of sync).
Proposed end state: keep cycle count as the single source, derive the rest or drop the extras.
Blocked on: (a) grep confirming zero behavioral reads of session_type; (b) verifying whether
check_session_type_cycles constraint is live (Phase 1 pulled columns only). Risky drop under R21
(no migration trail) — do as its own chunk, not folded into the R20/R22 unblock.

### R24 — Two parallel session-creation/cycle stacks (OPEN — confirmed causing bugs)
Two coexisting stacks both serve session/cycle flows with separate, hand-maintained
response models that have drifted:
  - Adaptive: session_management_router.py (start-session/start-cycle) → session_init.py
  - CRUD/legacy: routers/session_router.py → session_management/session_service.py (SessionPicker)
Originally intentional during migration (SessionPicker kept as dev tooling), but the
duplicate StartCycleResponse definitions drifted and are now demonstrably causing failures:
  - R26: adaptive StartCycleResponse missing first_brain_interaction_id that CRUD version has.
  - R28: SessionView opens isAdaptive=false and re-runs the CRUD stack on top of an
    adaptive launch, creating a second session and bypassing the adaptive engine.
Decision needed (post-stabilization): consolidate to one stack, or formally retire CRUD.
Until then, every shared response model must be kept in sync by hand across both — the
exact mechanism producing R26/R28.

### R25 — Client/server response-contract drift (PARTIALLY FIXED)
iOS Decodable structs and backend Pydantic response models share no source of truth and
drifted independently. start-session: Swift StartSessionResponse required session_type/
expected_cycles the adaptive backend never sent (original simulator blocker) and needed
rescue_level/always_silent the backend didn't return.
FIXED for start-session — backend commit 9fa6cbf (response trimmed to {session_id,
rescue_level, always_silent} via user_behavior fetch-or-create, mirroring
routers/session_router.py) + iOS commit 5414b7d (StartSessionResponse trimmed to match).
Simulator-verified: decodes clean, advances to start-cycle.
OPEN as a class: same root family as R21 (no shared schema). Other endpoints (start-cycle,
submit-answer) may carry the same drift — audit each when touched. R26 is the first instance.

### R26 — start-cycle: no first interaction (FIXED)
Simulator: mood → start-session (decodes clean) → start-cycle → app-level error
"Server returned no first interaction". start-cycle returned first_interaction_id correctly
in isolated /docs testing, so the failure differs for a real adaptive-created session via the
app. Two candidate causes, not yet diagnosed:
  (1) iOS reads firstInteractionId (optional in StartCycleResponse, may be nil) — client guard;
  (2) backend select_cycle_interactions yields empty ordered_ids for this session — ordered_ids[0]
      then has no first interaction.
Cycle-content selection path was audited at table/INSERT level only (cycle_creation.py INSERTs
structurally sound), NOT at column/logic level. This is the next work item.
FIXED — commit <TBD, fill after Handoff 2>, deployed Render. Adaptive
StartCycleResponse + return now include first_brain_interaction_id (from
cycle_data['ordered_interactions'][0]). Verified via curl (field present) and simulator
(guard clears, first interaction loads). iOS unchanged — field was already declared/consumed.

### R27 — Orphan active sessions never reaped (OPEN, hygiene/correctness)
detect_user_state and streak calcs read session WHERE status='active'. No timeout →
'incomplete' transition is implemented (v1.0 spec specifies 60-min inactivity rule).
Test user has 9+ active sessions, most with an open cycle, none completed — and R28's
double-session bug doubles the rate. Pollutes user-state detection and history math.
Decide: implement timeout-reaper, or enforce one-active-session-per-user at start
(complete/abandon prior active before creating new). Not blocking; adjacent to R28.

### R28 — SessionView runs CRUD stack despite adaptive launch (FIXED)
Simulator: adaptive mood flow succeeds (start-session + start-cycle return correct adaptive
session + first_brain_interaction_id), MainTabView presents SessionView — but SessionView
opens with isAdaptive=false and re-runs the legacy CRUD path (/api/session/create-session,
/session/start-cycle, /session/start-interaction), creating a SECOND different session
(SESSION_71A9… vs adaptive …7F0A). The interaction that plays is CRUD-driven, not adaptive.
Also: SessionView init/onAppear fires TWICE (doubled create-session, SESSION INIT, onAppear).
Root: R24 two-stack coexistence — MainTabView passes adaptive ids but isAdaptive defaults
false, so SessionView falls back to CRUD startup. Fix is iOS view-layer wiring, not backend.
Consequence: adaptive engine bypassed end-to-end; doubles orphan sessions (R27).
FIXED — iOS commit 081afd1. MainTabView now passes the full adaptive param set to
SessionView (isAdaptive: true + adaptiveSessionId/CycleId/FirstInteractionId/
FirstBrainInteractionId/SessionMood); SessionView.onAppear gained a hasStarted re-entry
guard. Simulator-verified: isAdaptive true, zero CRUD calls (create-session/start-cycle
silent), single startup, adaptive first interaction video + answers load. Adaptive engine
now drives the session end-to-end THROUGH THE FIRST INTERACTION. R24 two-stack root remains
(CRUD stack still exists for SessionPicker dev path) — not consolidated, just no longer
bypassing adaptive.

### R29 — /answers-by-interaction URL shape inconsistency (OPEN, low priority)
Answers call uses path /answers-by-interaction (no /api/ prefix, not under
session-adaptive/ namespace) — works, but inconsistent URL shape vs all other endpoints.
Verify intentional when touching the answer path; may need alignment if API gateway or
prefix routing is ever enforced.

### R30 — Cycle/session boundary handling (Piece 1 FIXED / Piece 2 OPEN)
Full-session simulator test exposed the cycle boundary stub. Split into two pieces:

PIECE 1 — FIXED (iOS commit <fill hash>). advanceAdaptive's cycleComplete branch
dismissed SessionView instead of advancing. Now unwraps lastNextCycle (backend
auto-opens the next cycle and returns its first interaction in the submit-answer
response), sets cycleId/sessionInteractionId/currentInteractionId, resets
interactionsCompletedInCycle, and loads the next cycle's first interaction. Session
complete still dismisses to HomeView (correct). Simulator-verified end-to-end: full
session = 3 cycles x 7 interactions, both boundaries advance, completes to HomeView.

PIECE 2 — OPEN (design + build). The intended UX has a feedback/summary screen between
cycles ("quick feedback appears, next cycle loads behind it, user continues") and a
complete-feedback screen at session end before returning to HomeView. Currently cycles
advance directly with no feedback screen (functional but abrupt). Data exists
(CycleSummary/SessionSummary structs decoded into lastCycleSummary/lastSessionSummary;
onFeedbackContinue() already routes to advanceAdaptive for adaptive mode) but no
adaptive cycle-feedback VIEW is built. This is the next work item — design-heavy
(what the feedback screen shows/feels like), not a patch.

### R31 — Adaptive interaction selection (RE-CHARACTERIZED — mostly BUILT, not random)
CORRECTION: R31 was previously logged as "selection is placeholder/random — core engine
stub." That was WRONG, based on an iOS debug log string ("selection_method: random"). Verified
by code read this session: the selection pipeline IS built and spec-faithful for story goal:
  - search (interaction_search.py): filters subtopic+interaction by level window, boredom,
    mood-type match, seen/new split, >=7-qualifying-subtopic — matches spec Parts 1-3.
  - combination tagging (session_context.get_combination): computes seen/new for
    subtopic+transcription+intent and maps to combinations 1-5 per Definitions — built, correct.
    seen-sets loaded from real history in SessionContext.load.
  - ordering (interaction_selection.py): entry-point-first for story, then combination-proximity
    next — matches spec Parts 4-6.
  - find_best_subtopic_with_fallback adds a 4-phase relaxation (new->seen->reduce boredom->
    reduce level) to guarantee >=7 — beyond spec, a robustness layer.
The "random" FEEL in testing = cold-start: a sparse-history user on thin content makes most
candidates resolve to the same combination, so the sort has nothing to differentiate and
selection collapses to query order. Expected behavior, NOT a code defect; resolves as real
history + a fuller content library accrue.

GENUINELY OPEN (deliberately deferred, decision-gated — these are the real R31):
  (a) Notion-mastery filter (notion_rate >= 0.8 join) is coded-around and DISABLED, gated to
      session_rank >= 2 (R11). Re-enabling is a product decision, not a bug.
  (b) Notion-goal selection branch — buildable (spec complete), not yet implemented.
  (c) Intent-goal selection branch — BLOCKED on design: spec says "list of intents not set yet"
      / "needs brainstorm." This is Remi's design work, not implementation.
  (d) cycle_manager/cycle_calculations.py (cycle level/boredom/goal) is the SIMPLIFIED
      placeholder, not the full spec algorithm. Separate from selection; also open.
Note: first regular session forces all cycles to story (session_rank=1), so story-goal
selection alone covers the entire first-session experience; (b)/(c) only matter from rank 2.

Testing: see TESTING_TOOLS.md (5 SQL tools + planned selection-trace script) for how to
exercise selection against real content with a controlled user.

**R31 — Combination classification VALIDATED on real data (2026-06-16):**
Using test_selection.py against the real DB with a controlled test user
(D08BC99B-... — note uppercase, see R33), combination classification was validated by
constructing each seen/new state and confirming get_combination returns the right number:
  - Combination 1 (seen/seen/seen): validated — played a cycle, re-ran harness, the 7 played
    interactions read seen/seen/seen.
  - Combination 2 (seen/new/seen): validated — an unplayed interaction in a seen subtopic
    whose intent was seen via another played interaction read seen/new/seen.
  - Combination 3 (seen/new/new): validated — re-tagged that unplayed interaction with a
    fresh intent (not in seen_intents); it flipped 2→3, single variable changed.
  - Combination 5 (new/new/new): validated — cold-start run (empty seen-sets) read all new.
  - Combination 4 (new/seen/seen): NOT validatable — BLOCKED BY R32. Requires "new subtopic /
    seen transcription", which the current code cannot produce (transcription axis keys on
    interaction_id, not transcription_fr). Becomes testable only after R32 fix.
Conclusion: get_combination classification is correct for all patterns the current code can
produce. The re-tag→re-run loop (edit content intent in Airtable, re-run harness) is a
reliable way to engineer specific combination states without replaying sessions.

OBSERVATION (open, not yet investigated): across repeat sessions (rank 1 → rank 2), the engine
re-served the SAME 7 interactions from the same subtopic (SUBT202510161396), never reaching
the broader content library. Combination 1 dominates repeat play; the engine does not appear
to advance toward newer content/subtopics across sessions as boredom rises. This is the
boredom→novelty / sort-direction question (see test_selection_MANUAL.md "Check 2") — the real
adaptiveness question, still open. Likely the highest-value next investigation.

### R32 — Combination "transcription" axis keys on interaction_id, not transcription (OPEN — core selection correctness)
DESIGN INTENT (confirmed by Rémi): the combination system's middle axis tracks whether the
user has seen the actual SPOKEN WORDS before — transcription_fr — NOT the interaction id. The
same transcription (e.g. "comment ça va?") deliberately exists as multiple distinct
interactions across different subtopics (same words, different video/setting). So a user can
have "seen" a transcription in subtopic A while subtopic B (same transcription) is still "new"
— the language-TRANSFER case central to TuJe's pedagogy (same language, new situation).

BUG: get_combination (session_context.py) uses
  transcription_status = "seen" if interaction_id in self.seen_interaction_ids else "new"
keying on interaction_id; SessionContext.load fills seen_interaction_ids from
si.brain_interaction_id. So two same-transcription interactions are treated as DIFFERENT on
this axis — opposite of design.

CONSEQUENCE: combinations depending on "same words, different interaction" cannot fire as
designed. Combination 4 (new subtopic / seen transcription / seen intent) is effectively
UNREACHABLE under current code (can't have a seen interaction_id without seeing its subtopic;
but you CAN have a seen transcription without seeing the subtopic). Combination 2 also
affected. Combinations 1, 3, 5 unaffected and testable as-is.

FIX (scoped, deferred — own focused pass):
  - Add SessionContext.seen_transcriptions: Set[str] = recent transcription_fr strings the
    user encountered (4-day window, mirroring current interaction window). Loaded by joining
    session_interaction -> brain_interaction, collecting transcription_fr.
  - get_combination transcription_status must check candidate's transcription_fr against
    seen_transcriptions, NOT interaction_id against seen_interaction_ids.
  - "Same transcription" = EXACT transcription_fr string match (Rémi's decision: no
    normalization, grouping, or punctuation-insensitivity).
  - Verify whether seen_interaction_ids is still needed elsewhere (e.g. recent-repeat
    avoidance) before removing.

TESTING IMPACT: combinations 2 & 4 cannot be validated against current code regardless of
content volume (code/design mismatch, not content gap). Validate 1/3/5 now; 2/4 after fix.
CONTENT NOTE: deliberate transcription reuse across subtopics is what makes combinations 2 & 4
reachable/testable post-fix — worth tracking which transcriptions repeat where.

### R33 — user_id stored case-sensitively with inconsistent case (OPEN — data integrity, silently breaks seen/new)
SYMPTOM (caught live this session): a session played in-app was stored with user_id
"D08BC99B-..." (UPPERCASE), while older sessions are "d08bc99b-..." (lowercase). Querying by
lowercase returned nothing; the row only appeared with uppercase or LOWER(). Source: the JWT
payload / request URLs carried the uppercase form (start-cycle URL showed user_id=D08BC99B-...),
so that session was written uppercase.

WHY IT MATTERS: every user-scoped query uses exact match (WHERE user_id = $1). If the app
sends a different case than what's stored, the query silently returns empty/partial results.
Critically, SessionContext.load (seen_subtopics/interactions/intents) filters WHERE
s.user_id = $1 — so case mismatch makes seen/new history come back EMPTY even when the user
has real recent sessions. This produces a FALSE cold-start: selection looks random/un-adaptive
not because of thin content but because the history query missed the rows. Confirmed live:
test_selection.py with lowercase id showed empty seen-sets + all combination 5; same harness
with uppercase id showed full seen-sets + correct combination 1, same content.

ROOT CAUSE: user_id column is text/varchar (confirm exact type — see Step 1), so case is
significant. (Extends R6, which first noted user_id is varchar and the same case observation; R33
adds live confirmation and the seen/new-history impact.) A real Postgres uuid type would normalize and compare case-insensitively.

FIX OPTIONS (decide later, own pass):
  (a) Normalize at the boundary — lowercase (or upcase) user_id everywhere it's written AND
      read (auth token issuance, all INSERTs, all WHERE user_id clauses). Lower-risk, no
      migration, but must be applied consistently or the bug persists.
  (b) Migrate the column (and all user-id columns across tables) to real uuid type — proper
      fix, normalizes automatically, but a schema migration on live data (and brain_user etc.
      must agree).
  Also: existing rows have mixed case — a one-time data cleanup (normalize stored values) is
  needed regardless of (a) or (b).

IMMEDIATE WORKAROUND for testing: match the case the session was stored under, or query with
LOWER(user_id) = lower(:id). test_selection.py / SessionContext.load use exact match, so set
the harness USER_ID to the stored case until fixed.

### Reliability & cost notes
- Per-cycle search (Decision 2) keeps heavy DB work to ~3 searches/session, not ~21.
- Whisper/GPT cost is unchanged by this work: scoring already runs on `submit-answer`; the adaptive "next pick" piggybacks on a round-trip we already make.
- Persisting the candidate pool (chunk 2) makes a dropped mid-cycle connection resumable.

---

## 6. Decision log

| # | Decision | Rationale |
|---|---|---|
| 1 | Server-authoritative; state in Postgres | Matches existing build; keeps adaptive IP in Python, changeable without app updates |
| 2 | Fixed candidate pool, dynamic next pick (Option B) | Honors "adaptive as they go" + the doc's "set next interaction"; same cost as pre-commit; resumable when persisted |
| 3 | Phase 1 story-only | Sidesteps notion data-model gap and undesignable intent work while exercising the full lifecycle + adaptive engine |
| 4 | Wiring Option 1 (surgical), promote later | Smallest change to get adaptive flow reachable; isolates "does it run" from router reorg |
| 5 | Surgical rewrite over continued patching when fixes accumulate (≥3 small fixes in one function) | `initialize_brand_new_user` was rewritten in chunk 1b after hitting 2 NOT NULL constraints in a row; rewrite produced cleaner code and pre-empted ≥2 more latent NOT NULL bugs the original would have hit. Establishes the tactic for future chunks. |
| 6 | Level-aware notion seeding for brand_new users, located in the brand_new initializer (not at initial-session close-out) | Replaces the current `initialize_notions_for_new_user` which writes all notions at rate 0.0 regardless of level — the bug that produced Issue 1's "no mastered notions" content gap. New behavior: all `brain_notion` rows with `level_from < user_level` seeded at `notion_rate = 1.0` (treated as owned); top 3 notions with `level_from = user_level` (exact match) by `rank` seeded at `notion_rate = 0.0` (in-play). Location decision (b, not a): notions belong to the session that uses them, not to the session that just ended — and elapsed time between initial completion and first regular session may be days/weeks, so seeding at first-regular-session-start is the honest model. Seed count of 3 is a placeholder for the first regular session; future selection algorithm (deferred) will compute it from priority/complexity rates. |
| 7 | First-regular-session cycle-goal override lives inside `calculate_cycle_goal`, not at call sites. Function reads `session.session_rank` and returns `"story"` directly when rank == 1. Falls through to the rotation pattern for rank ≥ 2. | Function-level enforcement means every caller (the adaptive `/start-cycle` handler too) inherits the correct behavior automatically; call-site logic would require every caller to remember the rule. Per ramp-up doc §4: "Cycle-goal selection (§6) does not run in this session — it begins at the second regular session." |

### Deferred to later phases
- **Phase 2 — notion goal:** notion data model (`brain_notion`, `session_notion` fields), §1 H–J notion sort, notion-rate updates (§1G, §5A), notion-goal interaction selection.
- **Phase 3 — intent goal:** requires the "list of intents" design (undefined in the logic doc).
- Bonus/malus rule definitions beyond what `bonus_malus_service` already supports.
- Full §5 depth (speaking/comprehension/accuracy) if trimmed in chunk 3.
- **Pin Render's Python version** (currently unpinned in render.yaml; local dev is 3.9.6, Render defaults to ~3.11). Add a runtime.txt or .python-version before launch so prod is reproducible.
- **Create a `.env.example`** listing required env var names with blank values (DATABASE_URL, OPENAI_API_KEY, AIRTABLE_API_KEY, AIRTABLE_BASE_ID, AIRTABLE_TOKEN, AIRTABLE_TABLE_NAME, JWT_SECRET, CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET) to document local setup without committing secrets.
- **Bucket→level mapping is a placeholder.** initial_level_bucket (0/1/2) → session_level (0/100/200), intentionally conservative (under-estimates; the regular session adapts upward). Loses granularity: onboarding has 5 level answers (A0–B2 = 0–400) collapsed into 3 buckets, so advanced beginners start under-leveled. Revisit when level semantics are finalized.
- **Initial→regular transition calc (future).** A richer close-out could read initial-session performance + elapsed-time-since-onboarding to set smarter opening values (not just level). Bounded in influence to ~the first cycle. Open question: compute at initial-session-end vs. first-regular-session-start. For now, only session_level is written at close-out; behavioral signal (mood, boredom, direction) is deliberately NOT inferred from the tutorial.
- **Verify `expected_total_score` formula.** Chunk 1b's rewrite extrapolated `expected_total_score = session_nbr_cycle * 700` from the initial-session convention (initial: 1 cycle, expected_total_score = 700). The formula isn't documented; revisit when defining the regular-session scoring model in chunks 4–5 to confirm it's right.
- **Numeric column → float standardization.** Per R15, convert at the read site rather than the use site, across all numeric column reads in the codebase. One coordinated pass, not mid-build.
- **Full cycle-goal algorithm (§6 of ramp-up doc).** Per R16, the boredom-band + goal-usage-score algorithm. Required when intent-goal cycles are built.
- **Atomic cycle-boundary in Half B.** Per R17. Lower-priority hardening for production.

---

## 7. Recommended next concrete step

Start **Chunk 0**: the surgical wiring fix plus its embedded discovery (does CRUD `submit-answer`/scoring depend on the CRUD `start-cycle`?). It's low-risk, unblocks everything, and its discovery answer may reorder chunk 6. Once chunk 0 is green, proceed to Chunk 1 — and stop there to reassess, since it's the first real run of cold adaptive code.
