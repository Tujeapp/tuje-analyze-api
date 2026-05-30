# TuJe v1 — Onboarding & Session Architecture Plan

**Status:** Living document. Updated as decisions evolve.
**Last updated:** 2026-05-30 (Onboarding architecture aligned with original product vision: two-phase model, 15 phases)
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

### Milestone 3 — Session score (initial session) ✅ COMPLETE (2026-05-29)

**Goal (as achieved):** At the end of the initial session, compute and store the `session_score` (rounded average of the 7 `interaction_score` values, 0–100).

**Status:** DONE. Folded into Case A of `/api/initial-session/complete-interaction` — when the session is being marked complete, the same atomic UPDATE also writes `session.session_score = ROUND(AVG(interaction_score))`. Returned in the response so iOS can use it.

**What changed vs. the original plan:** The original M3 was scoped as "score-bucket → CEFR level mapping, write to brain_user.level." That was based on an outdated spec. The corrected spec (Point D from the user) clarified:
- The 0–100 number computed at session end is the **session score**, not a user level
- The CEFR user level (0–400) is updated by notion validation (regular-session machinery, deferred)
- Initial session does NOT write to `brain_user.level`
- The session_score → CEFR interpretation is the **feedback step**, deferred to M5 (not yet designed)

So M3 became much smaller: just compute an average and store it. Took ~30 minutes of work.

**Implementation details:**
- `session_score` column already existed on `session` (integer, nullable, default 0). No schema change needed.
- SQL: `SELECT ROUND(AVG(interaction_score))::INTEGER FROM session_interaction WHERE session_id = $1 AND status = 'completed'`
- NULL guard: if AVG returns NULL (no rows), defaults to 0.
- Verified with a 7-row seed: scores 80/90/70/85/75/95/65 → average 80 → DB confirms `session_score = 80`.

**Out of scope for M3 (handled in M5):** the score → CEFR level interpretation, the feedback screen design, whether to update `brain_user.level` based on this. See decision D13.

### Milestone 4 part 1 — iOS components for initial sessions ✅ COMPLETE (2026-05-29)

**Goal (as achieved):** Build the iOS code paths needed to run an initial session against the new backend endpoints. Compiles cleanly. Functional verification deferred to M4 part 2 (blocked on routing architecture, see below).

**Approach used:** Option 1 (branch SessionViewModel with `isInitialSession` flag) — chosen after discovery revealed Option 3 (separate views) would require duplicating most of SessionView's UI machinery since the regular-session features (pre-prompt, rescue, answer modes) are all valid for initial sessions too. See decision D14.

**Files created:**
- `TuJe/Models/InitialSessionModels.swift` — Codable models for `/start` and `/complete-interaction`
- `TuJe/Services/InitialSessionService.swift` — singleton wrapping the two endpoint calls, typed errors (`onboardingIncomplete`, `templateIncomplete`, etc.)
- `TuJe/Views/Components/InitialPreSessionPromptView.swift` — dedicated pre-session prompt with explanatory copy ("Are you ready to speak, or would you prefer a silent session?" / "To use TuJe, you'll need to speak into your microphone sometimes.")

**Files modified:**
- `TuJe/ViewModels/SessionViewModel.swift` — added 7 initial-session properties; `loadInteractionForPlayback(id:)` (variant of `fetchInteraction` that skips `startInteraction`); `startInitialSession()`; `continueAfterInitialPrompt[Silent]()`; `completeInitialInteractionAndAdvance()`; 3-line early return in `onFeedbackContinue()`. All regular-session methods untouched.
- `TuJe/Views/SessionView.swift` — extended init with `isInitialSession`, `userToken`, two closures (`onInitialSessionComplete`, `onOnboardingIncomplete`); progress pill at top-center (conditional on `interactionTotal`); InitialPreSessionPromptView overlay; branched `.onAppear`; two `.onChange` handlers; hid always-silent persistent toggle and session picker button during initial sessions.
- `TuJe/Views/Onboarding/OnboardingView.swift` — replaced `.initialSession` stub with configured `SessionView`.
- `TuJe/ViewModels/OnboardingCoordinator.swift` — added `goBackToForm()` method.

**Verified:**
- Clean build in Xcode (no errors, no warnings).
- Backend endpoints reachable (curl health check).
- Scope respected: no changes to `APIService`, `FeedbackSheetView`, `MultipleButtonsAnswerView`, `VideoPlayerView`, `AudioService`, regular-session methods in SessionViewModel, hardcoded regular-session values, or existing debug `print()` statements.

**Blocked from end-to-end verification:** Simulator test revealed `TuJeApp.swift`'s routing condition (`if user.goalId == nil → OnboardingView else ContentView`) is too crude. After the form submits and sets `goalId`, the app immediately graduates the user to `ContentView`, bypassing the remaining onboarding stubs (`.transition`, `.micPermission`, `.conditions`, `.initialSession`, `.feedback`). The `.initialSession` step we built is structurally unreachable today. This bug pre-dates M4 (the stubs were already unreachable in production), but M4 surfaced it. Resolution: M4 part 2 (below).

### Milestone 4 part 2 — Onboarding phase architecture (~3 sessions, REVISED 2026-05-30)

**Goal:** Establish a proper `onboarding_phase` lifecycle as the source of truth for routing. Build phase 1 (sequential, pre-account) of the two-phase onboarding model. Phase 2 (account creation + tier selection) is M7+.

**Big-picture context — two-phase onboarding (D18):**

The original product vision (recovered 2026-05-30) is a two-phase onboarding:
- **Phase 1 = "Taste the product" (anonymous, fast):** Account check → HomeView teaser → goal/level selection → initial session → feedback → brief visual reward on HomeView → account creation gate triggers.
- **Phase 2 = "Commit" (gated):** Account creation → email/phone verification → plan tier selection → fully committed user.

Phase 2 is mandatory but is triggered from the post-initial-session HomeView (not the moment the initial session ends). The user briefly sees the HomeView with subtle visual changes, then a tap (or a timer-driven prompt) opens account creation. The user cannot do anything else with the app until they complete Phase 2.

M4 part 2 builds **Phase 1 only** through phase `feedback_acknowledged`. Phase 2 work is M7+ (see below).

**Full phase lifecycle (15 phases — see D18):**

PHASE 1 — sequential, anonymous:
1. `not_started` — app just installed, splash screen
2. `account_checked` — user answered "no account, continue as new"
3. `home_first_view` — user saw dormant HomeView placeholder, tapped "Try first session"
4. `goal_selected` — user picked goal (own screen, one task one screen per D19)
5. `level_selected` — user picked level (own screen)
6. `mic_authorized` — user granted mic access
7. `disclaimer_confirmed` — user saw wifi/quiet/headphones screen
8. `initial_session_started` — initial session began (set by backend on `/start`)
9. `initial_session_completed` — 7 interactions done (set by backend on session complete)

BRIDGE — feedback shown:
10. `feedback_acknowledged` — user dismissed feedback screen, briefly sees modified HomeView; account creation gate is now armed

PHASE 2 — sequential, account-required (M7+ work, NOT M4 part 2):
11. `account_creation_started` — user tapped (or accepted prompt); account creation modal opened
12. `account_credentials_entered` — user entered email/phone + password + profile info
13. `account_verified` — confirmed email/phone via code
14. `plan_tier_selected` — chose Free / Basic / Pro
15. `onboarding_completed` — user lands on HomeView, fully committed and functional

**Stub mapping (current OnboardingView stubs → new phase model):**

| Current stub view | Phase set when leaving it | Action |
|---|---|---|
| `accountCheck` | `not_started → account_checked` | KEEP — was wrongly marked vestigial before. Two-button screen ("I have an account" / "I'm new"). For "new" → continue. For "have an account" → login flow (separate, not part of onboarding). |
| `parisianTeaser` | `account_checked → home_first_view` | KEEP — shows the placeholder HomeView, dormant state. Tapping "Try first session" CTA on HomeView advances. |
| `tryFirstSessionCTA` | (no phase change — UI within HomeView itself) | REMOVE as standalone stub — fold into `home_first_view` HomeView |
| `twoQuestionForm` (real form) | `home_first_view → goal_selected → level_selected` | **SPLIT** into two screens: `GoalSelectionView` and `LevelSelectionView`. Per D19, "one screen, one task." Replaces D17's M4-pragmatism. |
| `transition` | (no phase change — transitional UI) | KEEP as transitional screen ("Now we'll do a quick session") — brief screen with Continue, no phase advancement. |
| `micPermission` | `level_selected → mic_authorized` | KEEP — real OS-level permission request. |
| `conditions` | `mic_authorized → disclaimer_confirmed` | KEEP — wifi/quiet/headphones disclaimer screen. |
| `initialSession` | `disclaimer_confirmed → initial_session_started → initial_session_completed` | KEEP — M4 part 1 work. Backend advances phases atomically (already designed). |
| `feedback` | `initial_session_completed → feedback_acknowledged` | M5 work. User dismisses → lands on HomeView in `feedback_acknowledged` state → bridge to Phase 2 (M7+). |

**Backend work (M4 part 2):**
- Update `brain_user.onboarding_phase` CHECK constraint to allow all 15 phase values
- New endpoint `POST /users/me/advance-onboarding-phase` body `{ "to_phase": "..." }` — validates forward-only transitions, idempotent (advancing to the current phase is a no-op), rejects backward and skip-too-far jumps
- Modify `/api/initial-session/start` to atomically advance phase to `initial_session_started` (single transaction with session/cycle/interaction creates from M1)
- Modify `/api/initial-session/complete-interaction` (Case A only) to atomically advance phase to `initial_session_completed`
- Define which transitions are valid (forward-only with skip rules — TBD during implementation discovery)

**iOS work (M4 part 2):**
- Refactor `TuJeApp.swift` routing — phase-based, not `goalId == nil`:
  - Phase `not_started` → `accountCheck` screen
  - Phase `account_checked` → `parisianTeaser` (placeholder HomeView with "Try first session" CTA)
  - Phase `home_first_view` → `GoalSelectionView`
  - Phase `goal_selected` → `LevelSelectionView`
  - Phase `level_selected` → `transition` screen
  - Phase `mic_authorized` → `conditions` screen
  - Phase `disclaimer_confirmed` → `SessionView(isInitialSession: true)` (M4 part 1)
  - Phase `initial_session_started` → `SessionView(isInitialSession: true)` (resume mid-session if quit)
  - Phase `initial_session_completed` → feedback view (M5 stub for now)
  - Phase `feedback_acknowledged` → HomeView placeholder (clickable but currently leads nowhere — M7+ adds the account creation gate)
- Each stub's "Next →" button calls `advance-onboarding-phase` then advances coordinator step (or the routing re-renders automatically based on the new phase)
- Split the existing single-screen form into `GoalSelectionView.swift` and `LevelSelectionView.swift` (D19)
- Handle resume: user reopening app mid-onboarding lands on the correct screen based on stored phase
- `tryFirstSessionCTA` stub is removed/folded into the placeholder HomeView

**M4 part 2 deferred to Phase 2 / M7+:**
- The post-feedback gate behavior (timer + tap → account creation modal). For M4 part 2, the HomeView placeholder shown at phase `feedback_acknowledged` is just a placeholder — clickable but the click leads nowhere (or shows a "Coming soon" message). The full gate is M7 work.

**Verification (M4 part 2):**
- Delete app, reinstall, complete Phase 1 → land on HomeView placeholder at phase `feedback_acknowledged`
- Quit mid-flow at various phases, reopen → resume at correct screen
- TablePlus: phase advances correctly through phases 1-10 in order
- Initial session DB rows created (session, cycle, 7 interactions, session_score) per M1-M3 work
- "I have an account" branch on the accountCheck screen routes to a (stubbed-for-now) login flow

### Milestone 5 — Feedback screen (~1 session, slightly revised 2026-05-30)

**Goal:** Beautiful, brand-appropriate feedback screen that interprets the user's `session_score` (computed in M3) into a CEFR-aligned verdict, considering what they self-reported at onboarding. On dismiss, lands the user on the HomeView placeholder.

**Work:**
- Decide the interpretation logic (product/UX): given `session_score` (0–100) and `initial_level_bucket` (0/1/2), what does the screen say? Per Point D, it might confirm/adjust the user's self-report, or flag "needs clarification in a first regular session."
- Design the screen (copy, visuals, CEFR naming — A0.0 / A0.5 / A1.0 etc. per Point A)
- SwiftUI implementation
- Dismiss action advances phase to `feedback_acknowledged` and routes to HomeView placeholder

**Verification:**
- Multiple test runs with different goal/level combos and different score outcomes (high/low/mid) → feedback adapts appropriately
- On dismiss, user lands on HomeView placeholder with phase `feedback_acknowledged`

### Milestone 6 — Phase 1 v1 readiness (~1 session, revised 2026-05-30)

**Goal:** Phase 1 of v1 is ship-ready. Full simulator test from cold launch through `feedback_acknowledged`. No known bugs, no dead code in the Phase 1 path, full documentation. The placeholder HomeView is clickable but doesn't yet trigger account creation — that's M7+.

**Note:** v1 cannot fully ship without Phase 2 (M7+) because account creation is mandatory. But Phase 1 being verifiably complete is the foundation for everything that follows. M6 establishes that foundation.

### Milestone 7+ — Phase 2: account creation + tier selection (NEW, multi-session, ~4-6 sessions)

**Goal:** Build the gated Phase 2 onboarding — account creation, email/phone verification, plan tier selection. The bridge from `feedback_acknowledged` (Phase 1 done, anonymous user) to `onboarding_completed` (fully committed user).

**Likely milestone breakdown (subject to revision when we get there):**
- **M7:** The HomeView gate behavior — timer + tap → account creation modal. Phase advancement to `account_creation_started`.
- **M8:** Account creation form — backend `/auth/upgrade-anonymous` already exists; iOS wraps it. Phases `account_creation_started → account_credentials_entered`.
- **M9:** Email/phone verification — requires choosing a provider (Twilio for SMS? SES for email?), code generation and validation endpoints, iOS verification screen. Phases `account_credentials_entered → account_verified`.
- **M10:** Plan tier selection UI — Free/Basic/Pro presentation, persistence to `brain_user.subscription_tier`. Phase `account_verified → plan_tier_selected`. NOTE: StoreKit 2 integration (real subscriptions, App Store Server Notifications V2, receipt validation) likely deferred to a v1.1 unless mandatory for v1.
- **M11:** Final transition + v1 polish — landing on the (committed) HomeView, phase `onboarding_completed`, full end-to-end test.

These milestones are placeholders. We'll scope each properly when we reach them. M7-M11 numbering may shift.

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

### 2026-05-29

**D13: Session score vs. user level — two distinct concepts.** The number computed at the end of an initial session is the **session score** (0–100), the rounded average of the 7 interaction scores. It is NOT the user's CEFR level (0–400, A0.0–B2.0). The user's CEFR level is independent infrastructure updated by notion validation (regular-session work, deferred). The initial session writes only to `session.session_score`, never to `brain_user.level`. The score → CEFR interpretation (e.g. "your session score of 65 suggests you're around A0.5, consistent with what you reported") is the **feedback step** — Milestone 5 — and is product/UX work, not backend logic. M3 stops at "compute and store the number"; M5 takes it from there.

**D14: M4 iOS — Option 1 (branch SessionViewModel), not Option 3 (separate views).** Initially leaned toward separate Views to quarantine regular-session bugs, but discovery revealed initial sessions need essentially the same UI machinery (pre-session prompt, rescue, answer modes — all interaction-driven, not session-type-driven). Building a parallel View would mean duplicating ~80% of SessionView's UI. Branching at the API-call level (where the bugs live) is cleaner: regular-session API calls stay untouched and buggy; initial-session API calls go through new clean `InitialSessionService`. The pre-session prompt is the one exception — it gets its own `InitialPreSessionPromptView` because the copy is materially different, and the dismiss handler routes to different code paths.

**D15: `onboarding_phase` becomes the source of truth for routing.** Currently `TuJeApp.swift` routes based on `goalId == nil` (form filled = graduated). This is too crude and made the multi-step onboarding stubs unreachable. Replace with phase-based routing using a 10-phase lifecycle (see M4 part 2). Backend is the source of truth; iOS reads and acts on `brain_user.onboarding_phase`. Resume-on-reopen falls out for free.

**D16: `speaking_or_silent_selected` is implicit, not a routed phase.** Although the lifecycle technically has 10 phases, the speaking/silent choice happens via the `InitialPreSessionPromptView` AFTER the session has already started (the prompt is shown inside SessionView, after `/api/initial-session/start` runs). Routing only honors 9 phases; the speaking/silent state is recorded as session metadata (`isSilentSession`), not as a phase the router cares about. Future product redesign could split the prompt out as a standalone onboarding screen, but that would require restructuring the session-start sequence.

**D17: Goal+level form stays single-screen for now, advances two phases on submit.** Rémi's product vision wants separate screens for goal selection and level selection ("one screen, one task"), but redesigning is deferred. M4 pragmatism: the existing single-screen form submits and advances phase from `home_first_view` to `level_selected` in one step, skipping the intermediate `goal_selected`. When the form is split into two screens later, we'll add the missing `goal_selected` transition between them. **SUPERSEDED by D19 (2026-05-30): form will be split into two screens as part of M4 part 2.**

### 2026-05-30

**D18: Two-phase onboarding architecture (recovered from original product vision).** Onboarding is two distinct phases with different purposes:
- **Phase 1 (anonymous, fast):** Get the user to taste the product with minimum friction. Account check → HomeView teaser → goal/level selection (two screens) → initial session → feedback → brief visual reward on HomeView → account creation gate triggers.
- **Phase 2 (gated, mandatory):** Account creation → email/phone verification → plan tier selection → fully committed user.

The user remains anonymous throughout Phase 1 (the `brain_user` row exists with `is_anonymous=true`). At the moment they trigger the Phase 2 gate (tapping HomeView post-feedback, or accepting the timer-prompted CTA), the account creation modal opens. Phase 2 is mandatory — the user cannot use the app freely without completing it. But Phase 1 gets them to value first before any commitment is asked. The same `brain_user.id` carries forward from anonymous to permanent (`/auth/upgrade-anonymous` already exists in the backend). 

This is a 15-phase lifecycle (full list in M4 part 2 section). Phase 1 (phases 1-10) is M4 part 2 + M5 + M6. Phase 2 (phases 11-15) is M7+. SUPERSEDES the simpler 10-phase model in D15 — that model missed Phase 2 entirely.

**D19: Form splits into two screens — `GoalSelectionView` and `LevelSelectionView`.** Replaces D17's M4-pragmatism. The original product vision is "one screen, one task" — we should not carry incorrect product behavior forward into M4 part 2 when correcting it costs ~1 extra session of iOS work. The current `TwoQuestionFormView` gets replaced with two dedicated views, each advancing phase atomically on submit.

**D20: HomeView during onboarding = clickable placeholder, no artistic work.** For v1, HomeView (the Parisian view) is a routing destination. Visual design (dormant/awakening/alive states, Blender renders, CoreMotion tilt, layered compositing) is its own conversation, deferred indefinitely. M4 part 2's HomeView at `feedback_acknowledged` is a placeholder that is clickable but currently does nothing on click. M7 adds the account creation gate behavior.

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
- [x] **Backend:** Compute and store `session_score` (rounded avg of interaction scores, 0–100) on initial-session completion (M3) ✅ 2026-05-29 — folded into Case A of `/api/initial-session/complete-interaction`. Scope corrected per D13: this writes `session.session_score`, NOT `brain_user.level`. CEFR interpretation deferred to M5.
- [x] **iOS:** New `InitialSessionService` (M4 part 1) ✅ 2026-05-29
- [x] **iOS:** Initial session UI flow — SessionView branching, progress pill, dedicated pre-prompt (M4 part 1) ✅ 2026-05-29
- [x] **iOS:** SessionViewModel branching with `isInitialSession`, `loadInteractionForPlayback`, `startInitialSession`, `completeInitialInteractionAndAdvance` (M4 part 1) ✅ 2026-05-29
- [x] **iOS:** OnboardingView wires `.initialSession` case to SessionView with closures (M4 part 1) ✅ 2026-05-29
- [ ] ⚠️ **iOS:** Hardcoded `subtopic_id`, fallback `firstInteractionId`, hardcoded `session_type "short"` — DEFERRED. These remain in the regular-session paths in SessionViewModel/APIService. They are NOT in the initial-session path (which uses our new clean code). Cleanup is regular-session conversation work.
- [ ] ⚠️ **iOS:** Decode full `start-cycle` response (currently only `cycle_id`) — DEFERRED. Regular-session API issue, not in the initial-session path.

### M4 part 2 — Onboarding phase architecture (Phase 1 only)

REVISED 2026-05-30: phase model expanded from 10 to 15 phases (per D18), form will be split into two screens (per D19), HomeView is placeholder for now (per D20).

- [ ] **Backend:** Update `brain_user.onboarding_phase` CHECK constraint to allow all 15 phase values (1-10 are M4 part 2 work; 11-15 are M7+ work but the constraint should accept them now).
- [ ] **Backend:** Define valid phase transitions (forward-only with skip rules) and document the matrix.
- [ ] **Backend:** New endpoint `POST /users/me/advance-onboarding-phase` body `{ "to_phase": "..." }` — validates forward-only transitions, idempotent for current phase, rejects invalid jumps.
- [ ] **Backend:** Modify `/api/initial-session/start` to atomically advance phase to `initial_session_started` (single transaction with the session/cycle/interaction creates).
- [ ] **Backend:** Modify `/api/initial-session/complete-interaction` (Case A — session-complete branch only) to atomically advance phase to `initial_session_completed`.
- [ ] **iOS:** Refactor `TuJeApp.swift` routing — phase-based, not `goalId == nil`. Routes per phase (see M4 part 2 section for the table).
- [ ] **iOS:** Each onboarding stub's "Next →" button calls `advance-onboarding-phase` then re-renders based on new phase.
- [ ] **iOS:** Split `TwoQuestionFormView` into `GoalSelectionView.swift` and `LevelSelectionView.swift` (per D19).
- [ ] **iOS:** `accountCheck` becomes a real screen with two buttons ("I have an account" / "I'm new"). "I'm new" advances phase; "I have an account" stubs to login (separate flow).
- [ ] **iOS:** `tryFirstSessionCTA` stub is removed; the CTA is folded into the placeholder HomeView shown at phase `account_checked`.
- [ ] **iOS:** Test resume — quit mid-onboarding at each phase, reopen, verify lands at correct screen.

### M5 — Feedback screen

- [ ] **iOS:** Build the post-initial-session feedback screen — reads `session_score` and `initial_level_bucket`, renders interpretation, dismiss advances phase to `feedback_acknowledged` and routes to HomeView placeholder.

### M6 — Phase 1 v1 readiness

- [ ] Full end-to-end simulator test of Phase 1 (cold launch through `feedback_acknowledged`). Document any remaining issues.

### M7+ — Phase 2: account + tier (multi-session, see PLAN section 3)

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

