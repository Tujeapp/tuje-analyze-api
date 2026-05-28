# TuJe v1 — Onboarding & Session Architecture Plan

**Status:** Living document. Updated as decisions evolve.
**Last updated:** 2026-05-28 (Milestone 2 complete)
**Owner:** Rémi
**Goal:** Reach a solid v1 of TuJe with a complete, testable onboarding flow and a foundation we can sleep on.

---

## 1. Vision

### The two-system architecture

TuJe has two distinct session experiences that share an execution engine but have separate generation systems:

```
┌─────────────────────────────────────────────────────────────┐
│  GENERATION LAYER (two completely separate systems)         │
│                                                             │
│  ┌──────────────────────┐    ┌──────────────────────┐       │
│  │  Initial Session     │    │  Regular Session     │       │
│  │  Generator           │    │  Generator           │       │
│  │                      │    │                      │       │
│  │  • Read template     │    │  • Detect user state │       │
│  │  • Order 7 interactions│  │  • Score boredom     │       │
│  │  • Compute level     │    │  • Pick subtopic     │       │
│  │    estimation at end │    │  • Select interactions│      │
│  │  • Simple, one-shot  │    │  • Mood, notions,    │       │
│  │                      │    │    streaks, etc.     │       │
│  └──────────┬───────────┘    └──────────┬───────────┘       │
│             │                           │                   │
└─────────────┼───────────────────────────┼───────────────────┘
              │                           │
              ▼                           ▼
┌─────────────────────────────────────────────────────────────┐
│  EXECUTION ENGINE (shared)                                  │
│                                                             │
│  • start-interaction      (load video, mark active)         │
│  • User interacts         (mic, buttons, hints, vocab)      │
│  • submit-answer          (adjust, match, score, GPT)       │
│  • complete-interaction   (mark done, advance)              │
│                                                             │
│  Decision after "Continue":                                 │
│  ├─ Initial session → next in pre-defined template list     │
│  └─ Regular session → calculate next dynamically            │
└─────────────────────────────────────────────────────────────┘
```

### Why this shape

- **Different generation, same execution.** Initial and regular sessions are conceptually different products (guided onboarding demo vs. lifelong learning sessions), but the user-facing interaction mechanics (mic, buttons, hints, scoring) are the same. Sharing the execution engine eliminates duplicate scoring/matching code.

- **Independent evolution.** The regular session generator will eventually grow rich logic (mood, notions, streaks, state detection). The initial session stays intentionally simple — it's a demo, not a learning session. Separating their generators means regular-session features can develop without polluting initial-session code, and vice versa.

- **Shared data model.** Both systems write to the same `session`, `session_cycle`, `session_interaction`, `session_answer` tables. A `session.is_initial_session = true` flag distinguishes them where it matters (e.g., the execution engine's "what's next?" decision). Analytics, history, GDPR all work naturally — initial sessions are just the user's first session.

---

## 2. What stays, what changes, what's new

### Stays as-is (until further notice)
- iOS Stage 1 onboarding form (works, tested live)
- Anonymous authentication flow + `restoreSession()` hybrid validation
- `brain_user_goal`, `brain_initial_session_template`, `brain_user.goal_id`, `brain_user.initial_level_bucket` (schema as-is)
- Existing matching/adjustment pipelines (TranscriptionAdjuster, answer_matching_service, GPT fallback) — they're the core IP and they work
- `scoring_service.py` calculation logic — works, but invocation needs review (see below)

### Changes (refactor / improve)
- **The execution engine endpoints** (start-interaction, submit-answer, complete-interaction, update-always-silent) get cleaned up and made deterministic. Currently scattered across `routers/session_router.py`, `complete_interaction_router.py`, `answer_processing_orchestrator.py` with latent bugs.
- **iOS hardcoded values** removed: `subtopic_id`, fallback `firstInteractionId`, hardcoded `session_type`.
- **Status string normalization**: `'complete'` vs `'completed'` inconsistency fixed across the codebase.
- **`completed_cycles` counter logic**: unified to one pattern (increment OR absolute, pick one).
- **Phantom column investigation**: confirm or remove `session_cycle.user_id`, `session_cycle.cycle_level_direction`.

### New (build from scratch)
- **Initial session generator subsystem**: new endpoints, template lookup, ordered playback persistence, level estimation.
- **`session.is_initial_session` boolean column** to distinguish session types at the execution-engine layer.
- **A way to persist the ordered template interaction list** for a cycle (most likely a `session_cycle.template_interaction_ids TEXT[]` column).
- **Level estimation logic**: score-bucket → estimated CEFR level, written to `brain_user.level` at end of initial session.
- **iOS level-estimation feedback screen** (post-initial-session).
- **iOS plumbing**: trigger initial session after form, navigate through it, show feedback screen.

### Deferred / parked
- `session_management_router.py` (the NEW router) — parked as reference material. Not mounted, not used. When regular-session work begins, we'll review whether to revive parts of it or rebuild fresh.
- Mood, notion processing, streak displays, user-state-aware messaging in the **regular** session — all real product features, all deferred until post-v1.

---

## 3. Sequenced milestones

Each milestone is self-contained, has clear verification criteria, and ends with a clean stopping point. Estimated effort is in focused sessions (~90 min each).

### Milestone 1 — Initial session backend foundation ✅ COMPLETE (2026-05-28)

**Goal:** Backend can create an initial session that loads 7 templated interactions in order.

**Status:** DONE. `POST /api/initial-session/start` is built, deployed on Render, and verified end-to-end. All three paths tested: onboarding-incomplete (400), happy path (200, DB rows confirmed), template-incomplete (422). Creation is atomic (transaction-wrapped). Schema columns added. See decisions D9-D11.

**Work:**
- Design new endpoint(s): `POST /api/initial-session/start` (and any necessary supporting endpoints — TBD during planning)
- Schema change: add `session.is_initial_session BOOLEAN NOT NULL DEFAULT FALSE`
- Schema change: add `session_cycle.template_interaction_ids TEXT[]` (nullable)
- Implement template lookup: given `(goal_id, initial_level_bucket)`, fetch 7 ordered interaction IDs
- Implement fallback: if template missing or partial (< 7 rows), document the failure mode (probably error out for v1 — better than wrong content)
- Create the `session` row with `is_initial_session = true`
- Create the `session_cycle` row with `template_interaction_ids` populated
- Create the first `session_interaction` row (position 1) ready to play

**Verification:**
- curl test: hit the new endpoint with a user who has `goal_id=GOAL3`, `initial_level_bucket=0` → response includes session_id, cycle_id, first interaction_id
- TablePlus: confirm `session.is_initial_session = true`, `session_cycle.template_interaction_ids` contains the 7 IDs in order, `session_interaction` has one row with `interaction_number=1`

### Milestone 2 — Template-aware completion (initial-session path) ✅ COMPLETE (2026-05-28)

**Goal (as achieved):** Initial sessions advance through their 7 templated interactions in order, and the single cycle completes correctly.

**Status:** DONE for the initial-session path. Instead of modifying the shared (buggy) `complete_interaction_router.py`, we built a SEPARATE clean endpoint `POST /api/initial-session/complete-interaction` (decision D12). It only advances — submit-answer owns all scoring. Verified across four cases:
- B1: advance interaction 1→2 → served template position 2 ✅
- B2: advance interaction 6→7 → served template position 7 ✅
- A: cycle completed → session marked complete (no hardcoded "3 cycles" bug) ✅
- C: bad cycle status → 409 cycle_not_active ✅

**What changed vs. the original plan:** The original M2 bundled regular-session cleanup (status normalization, counter logic, phantom columns, scoring verification) with template-aware completion. By building a separate initial-session endpoint, we sidestepped all the regular-session cleanup — those items are now purely regular-session concerns, moved to the regular-session work (separate conversation). The initial-session v1 path needed none of them.

**iOS flow for initial sessions (no start-interaction calls):**
1. `/api/initial-session/start` creates session + first interaction row, returns interaction_id + brain_interaction_id
2. iOS fetches video for brain_interaction_id, plays it
3. User answers → iOS calls `/api/session/submit-answer` (shared engine — scores + marks complete)
4. iOS calls `/api/initial-session/complete-interaction` (advances) → returns next interaction_id + next_brain_interaction_id, OR session_complete: true
5. Repeat through interaction 7

**Deferred to regular-session work (NOT v1 initial-session blockers):**
- Status string normalization (`'complete'` vs `'completed'`) in the OLD router
- `completed_cycles` increment-vs-absolute logic
- Phantom columns (`session_cycle.user_id`, `cycle_level_direction`)
- The regular `complete-interaction` score-overwrite bug (see TODO bank)
- Hardcoded `3` cycles in the OLD router

### Milestone 3 — Level estimation (~1 session)

**Goal:** At the end of the initial session, calculate and store the user's estimated level.

**Work:**
- Implement score-bucket → level mapping (per spec: 0-210 → level 0, 211-385 → 50, etc.)
- Trigger at end of session 7 (or as part of session completion)
- Write to `brain_user.level`
- Return level via API response so iOS can display it

**Verification:**
- Complete a full initial session via curl → check `brain_user.level` reflects the score buckets correctly
- Verify the API response includes the estimated level

### Milestone 4 — iOS integration: trigger and run initial session (~2 sessions)

**Goal:** iOS app, after form submission, runs the initial session end-to-end using the new endpoints.

**Work:**
- New iOS service: `InitialSessionService` (parallel to existing `APIService`)
- After form submission, trigger `POST /api/initial-session/start`
- New iOS view: `InitialSessionView` (or reuse `SessionView` with a mode flag — TBD)
- Connect to the execution engine endpoints (which are already used by regular sessions, just need updated request/response models)
- Handle session completion → fetch level estimation
- Remove iOS hardcoded values (`subtopic_id`, fallback `firstInteractionId`)

**Verification:**
- Cold launch on simulator → form → tap Continue → see initial session video play → interact with all 7 → see cycle progress → complete 3 cycles → land on level estimation screen
- TablePlus: full session/cycle/interaction tree exists with correct data
- No crashes, no error messages on screen

### Milestone 5 — iOS level estimation feedback screen (~1 session)

**Goal:** Beautiful, brand-appropriate feedback screen showing the user's estimated level after initial session.

**Work:**
- Design the screen (copy, visuals, level naming per spec)
- SwiftUI implementation
- "Save your progress" CTA → routes back to onboarding flow (or to ContentView for now)

**Verification:**
- End-to-end flow on simulator: launch → onboarding form → initial session → feedback screen → tap CTA → land on next state
- Multiple test runs with different goal/level combos → feedback adapts

### Milestone 6 — Cleanup & v1 readiness checklist (~1 session)

**Goal:** Ship-ready state. No known bugs, no dead code in critical paths, full documentation.

**Work:**
- Walk the TODO bank below, decide what blocks v1
- Fix anything that blocks
- Update PLAN.md with current state
- Tag v1 release in git

**Verification:**
- Fresh simulator install → complete onboarding flow on iPhone (not simulator) → no surprises

---

## 4. Decision log

Choices we've made, in chronological order. Don't relitigate without strong reason.

### 2026-05-27

**D1: Two-system architecture for sessions.** Initial sessions and regular sessions have separate generation systems but share an execution engine. Reason: the generation logic is fundamentally different (template lookup vs. dynamic calculation), but the user-facing interaction mechanics are identical.

**D2: Shared tables, distinguished by flag.** Both session types write to `session`, `session_cycle`, `session_interaction`. A `session.is_initial_session` boolean flag distinguishes them where the execution engine needs to decide "what's next?" Reason: avoids duplicating bug fixes across parallel tables, makes analytics natural, doesn't fragment the data model.

**D3: NEW router parked.** `session_management_router.py` is not mounted, not used. It contains valuable patterns but is half-implemented (no `start-interaction`, `complete-interaction`, etc.). When regular-session work begins, we'll evaluate whether to revive parts of it. Reason: adopting it now would force a multi-week project to complete its execution-engine half.

**D4: Solid v1 over fast v1.** When trading "ship templates on top of known bugs" vs "build a foundation worth sleeping on," we chose the latter. Reason: v1 should be something Rémi can demo and build on without dread.

**D5: Mood / notions / streaks deferred for initial session.** These are real product features for the regular session experience. They are NOT part of the initial session. Reason: initial session is a guided demo, not a full learning experience.

**D6: `learning_goal` column dropped.** Vestigial duplicate of `goal_id`. Dropped from `brain_user`. Reason: zero references in code, zero data in column, clean schema.

**D7: `restoreSession()` hybrid validation.** Anonymous tokens validated against `/users/me` in background after instant local routing. On 401, stale token recovered by creating fresh anonymous user. Reason: prevents stuck-app-on-deleted-user scenario.

**D8: iOS git setup.** iOS project versioned at `https://github.com/Tujeapp/tuje-ios`. Reason: foundational hygiene.

### 2026-05-28

**D9: `session_type` normalized to `initial`/`regular`.** Every regular session is exactly 3 cycles. The old `short`/`medium`/`long` model (3/5/7 cycles) is deprecated. If a user wants more practice, they start another session. **Implementation of the regular-session side is deferred** to the regular-session milestone — only `"initial"` is used in M1. As a stopgap, the two CHECK constraints on `session` were extended to allow `('initial' AND cycles=1)` while keeping short/medium/long. Full normalization (remove short/medium/long, add regular) happens later.

**D10: `session.user_id` is TEXT, but `brain_user.id` is UUID.** `get_current_user` returns `id` as a Python UUID object; the session tables' `user_id` is TEXT. The initial-session endpoint casts with `str(current_user["id"])` at the boundary. This is a schema-level type mismatch papered over at the application layer — noted, not resolved. Any future code joining `brain_user.id = session.user_id` will require a cast.

**D11: Initial session creation is atomic.** The three INSERTs (session, cycle, first interaction) are wrapped in a single `conn.transaction()`. If any fails, all roll back — no orphan rows possible. Reason: solid-foundation discipline; a half-created session is worse than a clean failure.

**D12: Separate initial-session completion endpoint (not modifying the shared handler).** Initial sessions use their own `POST /api/initial-session/complete-interaction`, which ONLY advances — reads `template_interaction_ids`, creates the next interaction row, or marks the session complete. It does NOT score or re-mark interactions; `submit-answer` (shared engine) owns all of that. Regular sessions keep the existing `complete_interaction_router.py` untouched. Reason: matches D1 ("Continue is where the two systems diverge"); avoids inheriting the OLD router's three bugs (hardcoded `3` cycles, mislabeled `next_interaction_id`, `'complete'` vs `'completed'` status); keeps regular sessions safe from changes made for initial sessions. The shared piece is interaction *execution* (start/submit/score); the divergent piece is *what comes next*.

---

## 5. TODO bank

Organized by whether they block the milestones above or are independent.

### Blocks a milestone (high-priority, in scope for v1)

- [x] **Schema:** Add `session.is_initial_session BOOLEAN NOT NULL DEFAULT FALSE` (M1) ✅ 2026-05-28
- [x] **Schema:** Add `session_cycle.template_interaction_ids TEXT[]` nullable (M1) ✅ 2026-05-28
- [x] **Backend:** New `/api/initial-session/start` endpoint (M1) ✅ 2026-05-28
- [x] **Backend:** Template lookup logic with fallback handling (M1) ✅ 2026-05-28 (fail-fast: 400 onboarding_incomplete, 422 template_incomplete; plan-B similar-interaction fallback deferred to interaction-engine work)
- [x] **Backend:** Make initial-session completion serve templated interactions in order (M2) ✅ 2026-05-28 — built as separate endpoint `/api/initial-session/complete-interaction` (D12), tested 4 cases (B1, B2, A, C)
- [x] **Backend:** ⚠️ M2 CARRY-FORWARD CAUTION (RESOLVED) — confirmed `submit-answer` has ZERO `session_type` branching and never calls the validators, so it's safe for `session_type='initial'`. The advance endpoint is separate and never touches regular-session validators. Initial sessions stay clear of all OLD-router create/validate paths. ✅
- [x] **Backend:** Verify scoring invocation (M2) ✅ 2026-05-28 — confirmed `submit-answer` does all scoring correctly (full bonus-malus); the initial-session advance endpoint does NOT score (by design).
- [ ] **Backend:** Implement level estimation: score-buckets → `brain_user.level` (M3)
- [ ] **iOS:** New `InitialSessionService` (M4)
- [ ] **iOS:** Remove hardcoded `subtopic_id` in `startCycle` (M4)
- [ ] **iOS:** Remove hardcoded fallback `firstInteractionId` (M4)
- [ ] **iOS:** Decode `first_interaction_id` from start-cycle response (M4)
- [ ] **iOS:** Initial session UI flow (M4)
- [ ] **iOS:** Level estimation feedback screen (M5)

### High-priority, independent of milestones

- [ ] **Backend addendum part 2:** `/auth/login` and `/auth/register` should also return `is_anonymous`, `onboarding_phase`, `subscription_tier`. Then tighten iOS `User` model to non-Optional for those three fields.
- [ ] **Unify the networking layer (iOS):** `GoalsService` and `OnboardingService` should route through `APIService.perform()` for consistent 401 recovery via `.anonymousTokenInvalid` notification.
- [ ] **Backend:** Resolve `main.py` import collision (lines 20-21, 83-84). Even if we don't mount the NEW router, the duplicate `include_router` is confusing.
- [ ] **D9 normalization (regular-session milestone):** Update both CHECK constraints (`check_session_type_cycles`, `session_session_type_check`) to the `initial`/`regular` model — drop `short`/`medium`/`long`, add `regular` (3 cycles). Update OLD router `create-session` to always use 3 cycles. Update iOS to send `"regular"` (or let backend default). Note: constraints currently allow `initial` as a stopgap (added 2026-05-28). Existing test data has deprecated `short` rows — harmless, but note for analytics.

### Regular session work (SEPARATE conversation — not v1 initial-session blockers)

These were originally bundled into M2 but were sidestepped by building a separate initial-session completion endpoint (D12). They are all about the OLD router / regular-session execution engine and will be tackled when regular sessions are built.

- [ ] **Backend:** Fix `'complete'` vs `'completed'` status inconsistency in `complete_interaction_router.py` (writes `'complete'`, everything else uses `'completed'`).
- [ ] **Backend:** Unify `completed_cycles` increment-vs-absolute logic (OLD router writes absolute; NEW router increments).
- [ ] **Backend:** Investigate phantom `session_cycle.user_id`, `session_cycle.cycle_level_direction` — confirm existence in DB, then decide to write or drop.
- [ ] **Backend:** Hardcoded `3` cycles in `complete_interaction_router.py:68` (`if completed_cycles >= 3`) — should read `expected_cycles` or branch on session type.
- [ ] **Backend (data-degradation bug):** The regular `complete-interaction` DESTRUCTIVELY overwrites submit-answer's good score. submit-answer writes the full bonus-malus `interaction_score` + `status='completed'`; then complete-interaction overwrites with `int(similarity_score)` (cruder) + `status='complete'` (buggy). The worse score wins because it runs second. Fix when reworking the regular execution engine.
- [ ] **Backend:** Mislabeled `next_interaction_id` in `complete_interaction_router.py` — returns a `brain_interaction.id`, not the `session_interaction.id`. (The initial-session endpoint already returns both IDs correctly.)
- [ ] **Decide:** whether regular sessions keep the OLD router, revive the parked NEW router, or get a fresh clean endpoint (like we did for initial sessions).



- [ ] **iOS:** `StartCycleResponse` only decodes `cycle_id`; backend already returns more.
- [ ] **iOS:** Debug `print()` calls in `APIService.perform()` logging auth tokens to console ("REMOVE AFTER TESTING").
- [ ] **iOS:** Centralize base URL (currently hardcoded in 5 separate files).
- [ ] **iOS:** Session-complete UI when `complete-interaction` returns `session_complete: true` (currently a TODO with no UI).
- [ ] **iOS:** `UserViewModel` uses `URLSession.shared` and `authToken` — should use `NetworkConfiguration.shared.session` and `currentToken`.
- [ ] **Backend:** `brain_user_goal` needs a `sort_order` column. Current ID-based sort is fragile.
- [ ] **iOS:** `User` model has non-optional `level: Int` and `role: String` — if backend ever omits these, decoding crashes.
- [ ] **Backend:** Stale error wording in onboarding-prefs: "no matching live goal found" should drop "live".
- [ ] **iOS:** MARK comment mismatch on `/answers-by-interaction`.
- [ ] **iOS:** `session_type` always hardcoded to `"short"` — no UI to pick length.
- [ ] **Backend:** Investigate the 3 non-anonymous users with `onboarding_phase = 'not_started'` (data from 2026-05-27). Decide whether `/auth/register` should default to `phase_1_in_progress`.

### Low-priority (cosmetic / future cleanup)

- [ ] **iOS:** Warnings pass — `AuthAPIService:44` optional interpolation, `SessionViewModel` unused interactionId, `MainTabView` deprecated onChange, `AppState` Swift 6 actor isolation on `logout()`.
- [ ] **iOS:** Level button copy in `TwoQuestionFormView` — currently generic "Beginner/Intermediate/Advanced"; spec calls for "Like a first time tourist" etc.
- [ ] **Backend:** Per-request asyncpg pool pattern + generic 500 exception leak — codebase-wide refactor.
- [ ] **Backend:** Two-connection pattern in `/auth/login` — same future asyncpg pass.
- [ ] **Backend:** `/users/me` returns more fields than iOS knows about (`first_name`, `last_name`, `avatar_url`, `bio`, `current_streak_days`, etc.) — decide if iOS needs them; if yes, extend `User` model.
- [ ] **Backend:** Rename `brain_initial_session_template.user_level` → `initial_level_bucket` for cross-table naming consistency.
- [ ] **Backend:** `complete_interaction_router.py:134` returns `next_interaction_id` that's actually a `brain_interaction.id`, not a `session_interaction.id` — naming inconsistency.
- [ ] **Backend:** `update_always_silent` silent failure — UPDATE with no INSERT fallback, returns 200 even if 0 rows affected.
- [ ] **Backend:** `bonus_malus_service._check_hint_malus` mutates cached object — subsequent reads within 300s TTL get the mutated value.
- [ ] **Backend:** `calculate_simple_score` in `scoring_service.py` is dead code (defined after `return` statement).
- [ ] **Backend:** Schema type smell — `brain_user.id` is UUID, but session tables' `user_id` and FKs are TEXT. Currently papered over with `str()` at the boundary (see D10). Consider normalizing types in a future schema pass so joins don't require casts.

### Parked indefinitely (not relevant unless product direction changes)

- `session_management_router.py` — exists as reference. Don't delete; don't mount.
- `detect_user_state` and notion/streak/boredom infrastructure — works in isolation, not surfaced anywhere. Revisit when regular-session work begins.

---

## 6. How to use this document

- **Start of each session:** read sections 1, 3, and the current milestone's checklist before proposing code.
- **Mid-session decisions:** if a new architectural choice comes up, add it to the Decision log with date.
- **Discovered TODOs:** add them to the TODO bank under the appropriate priority.
- **Completed work:** check off the items, but don't delete them — historical record matters.
- **Plan drift:** if reality diverges from the plan, update the plan. The plan serves us, not the other way around.

