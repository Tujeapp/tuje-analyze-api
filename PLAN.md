# TuJe v1 — Onboarding & Session Architecture Plan

**Status:** Living document. Updated as decisions evolve.
**Last updated:** 2026-06-02 (M8 backend chunks 1-5 COMPLETE — see TuJe_M8_Phase2_Spec.md for full details and D-M8-07/08 lessons. iOS chunks 6-12 remaining.)
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

### Milestone 4 part 2 — Onboarding phase architecture (COMPLETE ✅)

**Goal:** Establish a proper `onboarding_phase` lifecycle as the source of truth for routing. Build phase 1 (sequential, pre-account) of the two-phase onboarding model. Phase 2 (account creation + tier selection) is M7+.

**Backend status:** ✅ COMPLETE 2026-05-30. M4 part 2 first batch + piece 3 additions tested with 18 total verifications (9 in initial round, 9 in piece 3 round for cta_tapped + new endpoints).

**iOS piece 1 status:** ✅ COMPLETE 2026-05-30. Phase-based routing in TuJeApp + OnboardingView refactored to switch on phase + OnboardingCoordinator deleted. Build clean. End-to-end verified.

**iOS piece 2 status:** ✅ COMPLETE 2026-05-30. Each stub's Next button wired to advance phase via `/users/me/advance-onboarding-phase` + local sync. Mic permission gate at transition stub: grant advances to `mic_authorized`, deny shows alert with Open Settings deep-link. End-to-end verified both paths in simulator.

**iOS piece 3 status:** ✅ COMPLETE 2026-05-31. Six chunks shipped in one session, all clean builds, zero new warnings, end-to-end verified in simulator (cold launch → SessionView at initial_session_started).
- Chunk 1: Two new OnboardingService methods (`submitOnboardingGoal`, `revertOnboardingPhase`)
- Chunk 2: Form split — `GoalSelectionView` + `LevelSelectionView`. AppState's `updateUserFromOnboarding` made backwards-compatible with optional initialLevelBucket
- Chunk 3: `AccountCheckView` (real screen, AuthView modal via `.fullScreenCover`) + `HomePlaceholderView` (3-second simulated load timer at account_checked → home_first_view, in-place transition via combined switch case)
- Chunk 4: `OnboardingView` re-mapped — 4 stubs replaced with real views, new `cta_tapped` case added; `TuJeApp.shouldShowOnboarding` updated to include cta_tapped; `TwoQuestionFormView.swift` deleted
- Chunk 5: Back buttons on `LevelSelectionView` (revert to `cta_tapped`) and transition stub (revert to `goal_selected`) via optional `onBack` closure on `OnboardingStubView`
- Chunk 6: Simulator end-to-end test — walked through every screen + both back-button paths + forward through to SessionView. All 14 phase advances and 2 reverts succeeded. No crashes, no console errors.

**Big-picture context — two-phase onboarding (D18):**

The original product vision (recovered 2026-05-30) is a two-phase onboarding:
- **Phase 1 = "Taste the product" (anonymous, fast):** Account check → HomeView teaser → goal/level selection → initial session → feedback → brief visual reward on HomeView → account creation gate triggers.
- **Phase 2 = "Commit" (gated):** Account creation → email/phone verification → plan tier selection → fully committed user.

Phase 2 is mandatory but is triggered from the post-initial-session HomeView (not the moment the initial session ends). The user briefly sees the HomeView with subtle visual changes, then a tap (or a timer-driven prompt) opens account creation. The user cannot do anything else with the app until they complete Phase 2.

M4 part 2 builds **Phase 1 only** through phase `feedback_acknowledged`. Phase 2 work is M7+ (see below).

**Full phase lifecycle (16 phases — see D18 + cta_tapped addition):**

PHASE 1 — sequential, anonymous:
1. `not_started` — app just installed, splash screen
2. `account_checked` — user answered "no account, continue as new"; HomeView starts loading
3. `home_first_view` — HomeView/Parisian-view scene has finished loading and is ready to be explored; CTA appears
4. `cta_tapped` — user tapped "Try First Session"; first form screen now shown
5. `goal_selected` — user picked goal (own screen per D19)
6. `level_selected` — user picked level (own screen)
7. `mic_authorized` — user granted mic access
8. `disclaimer_confirmed` — user saw wifi/quiet/headphones screen
9. `initial_session_started` — initial session began (set by backend on `/start`)
10. `initial_session_completed` — 7 interactions done (set by backend on session complete)

BRIDGE — feedback shown:
11. `feedback_acknowledged` — user dismissed feedback screen, briefly sees modified HomeView; account creation gate is now armed

PHASE 2 — sequential, account-required (M7+ work, NOT M4 part 2):
12. `account_creation_started` — user tapped (or accepted prompt); account creation modal opened
13. `account_credentials_entered` — user entered email/phone + password + profile info
14. `account_verified` — confirmed email/phone via code
15. `plan_tier_selected` — chose Free / Basic / Pro
16. `onboarding_completed` — user lands on HomeView, fully committed and functional

**Final screen mapping (M4 part 2 piece 3 complete):**

| Phase | Screen rendered | Action that advances |
|---|---|---|
| `not_started` | **AccountCheckView** (real, chunk 3) | "I'm new" → advance to `account_checked`; "I have an account" → `.fullScreenCover(AuthView)` |
| `account_checked` | **HomePlaceholderView** (chunk 3) | 3-second timer fires → advance to `home_first_view` (D24 — real video onReady later) |
| `home_first_view` | **HomePlaceholderView** (same instance, in-place transition) | CTA "Try First Session" → advance to `cta_tapped` |
| `cta_tapped` | **GoalSelectionView** (chunk 2) | Pick goal → `submitOnboardingGoal` → `goal_selected` |
| `goal_selected` | **LevelSelectionView** (chunk 2) | Pick level → `submitPrefs` (both fields) → `level_selected`. Back chevron → revert to `cta_tapped` (chunk 5) |
| `level_selected` | Transition stub (still uses `OnboardingStubView`) | Next → mic permission → `mic_authorized`. Back chevron → revert to `goal_selected` (chunk 5) |
| `mic_authorized` | Conditions stub (still uses `OnboardingStubView`) | Next → `disclaimer_confirmed` |
| `disclaimer_confirmed`, `initial_session_started` | `SessionView` with `.id("initial_session")` | Backend `/start` advances → `initial_session_started`; backend `/complete-interaction` Case A advances → `initial_session_completed` |
| `initial_session_completed` | Feedback stub (M5 work — placeholder until then) | Dismiss → `feedback_acknowledged` |

**Backend work (M4 part 2) — ✅ ALL COMPLETE 2026-05-30:**
- ✅ Updated `brain_user.onboarding_phase` CHECK constraint to allow all 15 phase values. Pre-existing constraint named `check_onboarding_phase` was dropped; new constraint `brain_user_onboarding_phase_check` added.
- ✅ Data migration: 12 rows at `phase_1_in_progress` → `level_selected`; 0 rows at `phase_2_in_progress`; 3 rows at `not_started` (unchanged).
- ✅ New endpoint `POST /users/me/advance-onboarding-phase` body `{ "to_phase": "..." }` — strict forward-only: `to_phase = current_phase` returns 200 no-op; `to_phase = current_phase + 1` advances; anything else 400. Distinct error fields: `invalid_phase` for unknown values, `invalid_transition` for skip/backward.
- ✅ `/auth/anonymous` modified — writes `'not_started'` (was `'phase_1_in_progress'`)
- ✅ `/users/me/onboarding-prefs` modified — writes `'level_selected'` with don't-go-backward guard (also fixes a pre-existing bug: file used `logger` references without importing logging; now fixed at the top of `user_routes.py`)
- ✅ `/auth/upgrade-anonymous` modified — writes `'account_credentials_entered'` (was `'phase_2_in_progress'`). Not directly tested but structurally identical change to `/auth/anonymous` (Test 6); will get exercised in M7+ work.
- ✅ `/api/initial-session/start` modified — inside the existing atomic transaction, advances phase to `'initial_session_started'` (with guard)
- ✅ `/api/initial-session/complete-interaction` Case A modified — wraps session UPDATE + phase UPDATE in a new transaction, advances to `'initial_session_completed'` (with guard)
- ✅ All three embedded guards (`onboarding-prefs`, `initial-session/start`, `initial-session/complete-interaction` Case A) handle corrupt phases consistently: log an error and skip the phase update without breaking the primary operation.
- ✅ All three embedded guards have explicit code comments documenting the D17/D19 transitional permissiveness (forward-skip allowed until form splits into two screens).

**Backend verification — all 9 tests passed:**
- Test 6 (early): `/auth/anonymous` writes `not_started` ✅
- A1: new endpoint no-op (already at target) → 200 `changed: false` ✅
- A2: new endpoint valid forward-by-one → 200 `changed: true`, DB confirms ✅
- A3: new endpoint rejects forward skip → 400 `invalid_transition` ✅
- A4: new endpoint rejects backward → 400 `invalid_transition` ✅
- A5: new endpoint rejects unknown phase value → 400 `invalid_phase` ✅
- Test 7: `/users/me/onboarding-prefs` writes `level_selected` ✅
- Test 8: `/api/initial-session/start` writes `initial_session_started` (atomic with session/cycle/interaction creates) ✅
- Test 9: `/api/initial-session/complete-interaction` Case A writes `initial_session_completed` (atomic with session UPDATE + session_score computation = 80) ✅

**iOS work (M4 part 2):**

**Piece 1 — Phase-based routing (✅ COMPLETE 2026-05-30):**
- ✅ Refactored `TuJeApp.swift` routing — phase-based, not `goalId == nil`. Single private helper `shouldShowOnboarding(for:)` returns true for the 9 Phase 1 phases (`not_started` through `initial_session_completed`). Falls through to `ContentView` for `feedback_acknowledged` (TRANSITIONAL — M7+ replaces with gate behavior).
- ✅ Refactored `OnboardingView.swift` to switch on `appState.currentUser?.onboardingPhase` (Optional<String>). 9 named phase cases + defensive default. SessionView at `initial_session_started` correctly wired with M4 part 1's closures (onInitialSessionComplete calls `appState.updateOnboardingPhase("initial_session_completed")`).
- ✅ Deleted `OnboardingCoordinator.swift` and `OnboardingStep` enum entirely. Phase is now the single source of truth.
- ✅ Removed coordinator references from `TwoQuestionFormView.swift` (2 lines). Form's submit still works: `updateUserFromOnboarding` sets phase to `level_selected`, which triggers TuJeApp re-render → OnboardingView switches to transition stub automatically.
- ✅ Added `advanceOnboardingPhase(toPhase:token:)` to `OnboardingService.swift` with `AdvanceOnboardingPhaseRequest`/`AdvanceOnboardingPhaseResponse` structs. Same retry pattern as `submitPrefs` (1 retry on 5xx). Currently no callers (piece 2 will wire them).
- ✅ Added `updateOnboardingPhase(_:)` to `AppState.swift` — local-state-only update that preserves all 12 User fields, reassigns authState to trigger SwiftUI re-render.
- ✅ Fixed cold-launch stub at `AppState.swift:107` (`phase_1_in_progress` → `not_started`).
- ✅ Build clean. End-to-end verified: brand-new anonymous user routes to accountCheck stub.

Piece 1 phase → screen mapping (current state — to be refined in pieces 2-3):
- `not_started` → existing accountCheck stub
- `account_checked` → existing parisianTeaser stub
- `home_first_view` → existing tryFirstSessionCTA stub
- `goal_selected` → existing twoQuestionForm (real form)
- `level_selected` → existing transition stub
- `mic_authorized` → existing micPermission stub
- `disclaimer_confirmed` → existing conditions stub
- `initial_session_started` → SessionView(isInitialSession: true) [M4 part 1 work]
- `initial_session_completed` → existing feedback stub
- nil or unknown → existing accountCheck stub (defensive fallback)

**Piece 2 — Per-stub phase advancement (✅ COMPLETE 2026-05-30):**
- ✅ Extended OnboardingStubView to accept `onNext: () -> Void` closure
- ✅ Each stub Next button calls `OnboardingService.advanceOnboardingPhase(toPhase:, token:)` + `appState.updateOnboardingPhase(_:)` in a Task wrapper with do/catch error logging
- ✅ Transition stub special handling: requests OS mic permission via `AudioService.shared.requestMicPermission()`; on grant advances to `mic_authorized`; on deny shows SwiftUI alert ("Microphone Access Required" / "TuJe needs microphone access to teach you. Please enable it in Settings.") with Cancel and Open Settings buttons (deep-link via `UIApplication.openSettingsURLString`)
- ✅ Phase mapping under option C: `mic_authorized` now routes to conditions stub (was micPermission stub in piece 1); `disclaimer_confirmed` and `initial_session_started` combined in one case with `.id("initial_session")` to prevent SessionView teardown when the backend's `/start` advances phase mid-flow
- ✅ `import UIKit` added for the Settings deep-link
- ✅ Default case (nil/unknown phase) logs the corrupt state without advancing — surfaces bugs rather than papering over them
- ✅ Build clean, no new warnings
- ✅ End-to-end verified in simulator: fresh anonymous user → accountCheck → parisianTeaser → tryFirstSessionCTA → twoQuestionForm (submit) → transition → mic prompt (Allow) → conditions → SessionView with InitialPreSessionPromptView. Also verified deny path: SwiftUI alert appears, phase does NOT advance, user retains Open Settings escape hatch.

**Piece 3 — Form split + accountCheck as real screen + back buttons (PENDING):**
- Split `TwoQuestionFormView` into `GoalSelectionView.swift` and `LevelSelectionView.swift` (per D19)
- When form splits, each screen's submit becomes a one-step phase advance: GoalSelectionView submits → advance to goal_selected; LevelSelectionView submits → advance to level_selected (the existing onboarding-prefs endpoint can stay as-is — it saves both goal_id and initial_level_bucket together; iOS calls it once after the second screen completes)
- `accountCheck` becomes a real screen with two buttons ("I have an account" / "I'm new"). "I'm new" advances phase; "I have an account" stubs to login (separate flow, out of scope for M4)
- Add back buttons (per D-decision):
  - On LevelSelectionView → back button reverts to home_first_view (re-shows goal screen)
  - On transition stub → back button reverts to level_selected (re-shows level screen)
- Backend: new endpoint `POST /users/me/revert-onboarding-phase` with EXPLICIT allowed-reverts (NOT a general "go anywhere backward" — must enumerate the two valid backward transitions). Returns 400 for any unlisted revert.

**M4 part 2 deferred to Phase 2 / M7+:**
- The post-feedback gate behavior (timer + tap → account creation modal). For M4 part 2, the HomeView placeholder shown at phase `feedback_acknowledged` is just a placeholder — clickable but the click leads nowhere (or shows a "Coming soon" message). The full gate is M7 work.

**Verification (M4 part 2):**
- Delete app, reinstall, complete Phase 1 → land on HomeView placeholder at phase `feedback_acknowledged`
- Quit mid-flow at various phases, reopen → resume at correct screen
- TablePlus: phase advances correctly through phases 1-10 in order
- Initial session DB rows created (session, cycle, 7 interactions, session_score) per M1-M3 work
- "I have an account" branch on the accountCheck screen routes to a (stubbed-for-now) login flow

### Milestone 5 — Feedback screen ✅ COMPLETE (2026-05-31)

**Goal:** One-screen feedback at phase `initial_session_completed` showing the user's session_score (0-100) with a qualitative label, the goal context, and a Continue button that advances to `feedback_acknowledged` → HomePlaceholderView's terminal state.

**Scope intentionally minimized:** No CEFR estimation (the level system isn't wired for initial sessions yet — that's deferred to regular-session work). No comparison to self-declared `initial_level_bucket`. Just the headline number, a friendly label, and the user's goal. Honest about what we have.

**Score bucketing:**
- 0-40 → "Good effort"
- 41-70 → "Nice job"
- 71-100 → "Excellent"

**iOS work (5 chunks, all completed 2026-05-31, all clean builds, zero new warnings):**

- **Chunk 1** — UserDefaults persistence. Created `SessionKeys.swift` (enum with `lastInitialSessionId` and `lastInitialSessionScore` constants). SessionViewModel writes both at the moments they're set (lines 277 and 336). AppState clears them in all 4 logout/reset flows (mirrors `anonGoalIdKey` pattern). This is required because SessionViewModel is `@StateObject` owned by SessionView, which dies when OnboardingView's switch re-renders to FeedbackView — the in-memory state is gone, so UserDefaults is the bridge.

- **Chunk 2** — Created `FeedbackView.swift`. Reads `lastInitialSessionScore` via `UserDefaults.standard.object(forKey:) as? Int` (distinguishes nil from 0). Reads goal label via `GoalsService.shared.fetchGoals(token:)` + array find (cache is warm by this point). Graceful degradation: if score is nil, shows generic "Session complete!" without a number; if goal lookup fails, silent fail (goal context is decorative). Continue button advances phase to `feedback_acknowledged` via existing `OnboardingService.advanceOnboardingPhase`.

- **Chunk 3** — Extended `HomePlaceholderView` with a third terminal state for `feedback_acknowledged`. Added `isFeedbackAcknowledged` computed property; existing `isLoading` and `showsCTA` stay correctly false at this phase. Three-state overlay: loading (spinner) / feedback_acknowledged (accentColor checkmark + "Lesson complete") / default (building icon). Second title/subtitle variant: "Welcome back to Paris" + "More lessons are coming soon. Thanks for being an early explorer!" No CTA at this phase (terminal state). Header comment updated.

- **Chunk 4** — Routing changes. `OnboardingView.swift`: `initial_session_completed` case now routes to `FeedbackView` (was `OnboardingStubView`). `feedback_acknowledged` added to the existing combined HomePlaceholderView case (now 3 phases: `account_checked`, `home_first_view`, `feedback_acknowledged` — preserves view identity, no flicker between states). `TuJeApp.shouldShowOnboarding` Set extended to 11 phases with `feedback_acknowledged` inserted after `initial_session_completed`.

- **Chunk 5** — Simulator end-to-end test (shortcut method per D26). Used existing user at `mic_authorized`, jumped phase to `initial_session_completed` via TablePlus (bypasses strict-advance-by-one). Force-quit + relaunch → AppState fetched fresh `/users/me` → routed to FeedbackView. Verified: FeedbackView rendered correctly with graceful degradation (no score in UserDefaults → "Session complete!" generic message + goal context "You're one step closer to travel and vacation." correctly formatted). Tapped Continue → advanced to `feedback_acknowledged` → HomePlaceholderView terminal state rendered (checkmark + "Welcome back to Paris" + "More lessons coming soon" + no CTA). All checks passed.

**Key learnings:**
- **SessionViewModel @StateObject lifecycle** — confirmed that @StateObject dies when its owning view unmounts. Any state needed across view transitions must be persisted to UserDefaults (or AppState, but AppState would be overkill for two ints/strings).
- **Combined switch case for view identity preservation** — combining 3 phases (account_checked, home_first_view, feedback_acknowledged) into one case ensures SwiftUI keeps the HomePlaceholderView instance across phase changes. Internal computed properties (`isLoading`, `showsCTA`, `isFeedbackAcknowledged`) switch the rendered content without view recreation. This prevents flicker.
- **`UserDefaults.standard.integer(forKey:)` is ambiguous** — returns 0 if missing. Always use `object(forKey:) as? Int` for Optional<Int> reads.
- **Honest design over fake polish** — chose to show genuine data (session_score + goal) rather than fake CEFR estimates we can't actually compute. When the real level computation is built, M5 can be revisited.

### Milestone 6 — Airtable CMS for initial session templates ✅ COMPLETE (2026-06-01)

**Goal:** Make the 18 initial session templates (6 goals × 3 levels) manageable through Airtable as the CMS. Rémi can populate, edit, and reorder interactions across all templates visually; an Airtable→PostgreSQL webhook syncs changes to `brain_initial_session_template`.

**Why this milestone exists (per D30):** Without it, the 18 templates could only be populated via raw SQL inserts, which is slow, error-prone, and offers no creative feedback loop. With this, Rémi (the only content owner) can craft realistic learning sequences for every goal/level combination. M7's comprehensive walkthrough test then becomes meaningful — testing with real, intentionally-crafted content rather than test fixtures.

**Shipped in 5 chunks (engineering complete; content population is ongoing your-time work):**

**Chunk 1 — Initial Interaction sync infrastructure (backend)**
- SQL migration: `brain_initial_session_template` aligned with sync convention
  - Old `id` (auto-increment integer) → new `id` (TEXT primary key, TuJe-style "ISI..." IDs)
  - Existing 7 test rows deleted (will be repopulated via Airtable)
  - `updated_at` → `update_at` (matches framework convention across all 16 brain_* tables — per D32)
  - `last_modified_time_ref` changed from TIMESTAMP to BIGINT (framework sends raw ms epoch int; surfaced as bug during testing — see D31)
- Python additions to `airtable_routes.py` (~25 lines):
  - `InitialInteractionEntry` Pydantic model (4 fields: goalId, userLevel, position, interactionId)
  - field_mappings additions for `goalId` and `userLevel`
  - SYNC_CONFIGS entry "initial_interaction"
  - Webhook endpoint `POST /webhook-sync-initial-interaction`
- Verified via curl POST → 200 success, DB row written correctly

**Chunk 2 — User Goal sync infrastructure (backend)**
- SQL migration: `brain_user_goal` extended with 5 sync columns (airtable_record_id, last_modified_time_ref BIGINT, created_at, update_at, live), `name` made NOT NULL
- Existing 6 goal rows (GOAL1-GOAL6) preserved — first sync UPDATEs them to populate airtable_record_id
- Python additions (~15 lines): `UserGoalEntry` Pydantic model (1 field beyond BaseEntry: name), SYNC_CONFIGS entry "user_goal", webhook endpoint `POST /webhook-sync-user-goal`
- Verified via curl POST → 200 success, GOAL3 row UPDATEd correctly with `ON CONFLICT (id) DO UPDATE` semantics

**Chunk 3 — Airtable scripts (UI work)**
- User Goal sync script (minimal — just id + name + sync fields)
- Initial Interaction sync script (handles linked record lookups for Interaction ID and Goal ID, plus Level single-select parsing to int)
- Both scripts deployed to "Sync Data" button columns in Airtable
- End-to-end Airtable→backend→PostgreSQL syncs verified for both entities

**Chunk 4 — Content population (Rémi's time, ongoing)**
- 1 User Goal synced (GOAL1); GOAL2-GOAL6 remain to be synced (5 button clicks)
- 1 template populated (GOAL1 / level 0 / 7 rows, all using the same INT202505090900 for testing template plumbing not content variety)
- 17 templates remain (content work — Rémi's timeline)

**Chunk 5 — Backend verification**
- Fresh anonymous user created with goal_id=GOAL1, initial_level_bucket=0, phase=disclaimer_confirmed
- POST /api/initial-session/start → returned correct response: session_id, cycle_id, interaction_id, brain_interaction_id=INT202505090900 (position 1), total_interactions=7
- Verified `session_cycle.template_interaction_ids` contains all 7 ordered positions in PostgreSQL

**End-to-end pipeline now operational:** Edit interaction in Airtable → click Sync Data → PostgreSQL row written in <0.1s → backend `/api/initial-session/start` reflects the change → iOS receives the new content.

**Open follow-ups from M6:**
- Populate remaining 17 templates × 7 = 119 Initial Interaction rows + 5 User Goal rows (content work, your timeline)
- Consider fixing the "carrier" → "career" typo in GOAL5 via Airtable edit (one-click change now that User Goal syncs)

### Milestone 7 — Phase 1 v1 readiness (comprehensive walkthrough test) ✅ COMPLETE (2026-06-01)

**Goal:** Phase 1 of v1 is ship-ready. Full simulator test from cold launch through `feedback_acknowledged`. No known bugs, no dead code in the Phase 1 path. M7 closed the gaps between piece-by-piece testing and full end-to-end verification.

**Test setup pragmatic choice:** Single (GOAL1, level 0) template populated; the same multiple-buttons interaction (INT202505090900, "Bonjour, votre passeport s'il vous plait ?") synced 7 times to test template plumbing rather than content variety. This avoided the need to design 7 distinct French interactions AND avoided exercising the mic (which is destined for separate work — see Future Work below). Each of 7 interactions completed by tapping any of 2 rendered answer buttons.

**What was verified end-to-end (now proven, previously theoretical):**
- Cold launch → anonymous user creation with X-App-Version + X-Bundle-ID + X-Client-Platform headers
- All 9 onboarding phase advances (account_checked → home_first_view → cta_tapped → goal_selected → level_selected → mic_authorized → disclaimer_confirmed)
- SessionView onAppear → startInitialSession → backend lookup of (GOAL1, level 0) template → 7 ordered interactions returned
- For each of 7 interactions: video loaded → buttons rendered → tap → submit-answer → score 100 → complete-interaction → next loads
- Session-complete detection (sessionComplete=true, nextInteractionId=nil) → backend auto-advanced phase to `initial_session_completed`
- **CRITICAL NEW VERIFICATION:** SessionViewModel's M5 chunk 1 UserDefaults persistence ACTUALLY FIRED — console showed `✅ FeedbackView: loaded session score from UserDefaults: 100`. This was theoretical until M7.
- FeedbackView happy path rendered with real score (100/100) — not just graceful-degradation fallback
- Continue tapped → phase advanced to `feedback_acknowledged` → HomePlaceholderView terminal state

**Two real bugs surfaced AND fixed during M7 (see D31 and D32):**
1. **sessionInteractionId silently cleared by `resetTrackingForNewInteraction()`** → initial-session button taps did nothing (visual press feedback but no action). Root cause: helper method designed for regular-session flow (where startInteraction re-sets sessionInteractionId after the reset) was being called from initial-session flow (where sessionInteractionId was set by startInitialSession and there's no later set). Fix: removed sessionInteractionId clear from the helper; moved it explicitly into fetchInteraction (regular flow). Plus added defensive logs to submitButtonAnswer and submitSingleButtonTap guards to prevent future silent failures.
2. **VideoPlayerView same-URL guard prevented onVideoReady from firing on consecutive identical videos** → second interaction stuck on black loading screen because updateUIView's `guard currentURL != url` short-circuited swapURL, so the new status observation was never created, so onVideoReady never fired, so isLoadingVideo stayed true. Fix: added `playerIsReady: Bool` to Coordinator; when updateUIView sees same URL and player is already ready, re-fire onVideoReady manually so loading state clears.

**Future work surfaced (NOT M7 scope):**
- Mic-based answering system needs a dedicated separate conversation (per Rémi's note during M7 setup)
- `user_level=250` sent in `/answers-by-interaction` URL when test user's actual level was 0 — some default fallback is happening; worth investigating but not a blocker
- Only 2 answers returned when brain_interaction_answer has 4 live rows for this interaction — confirmed intentional (difficulty/answer-type filter, not a bug)

### Milestone 8 — Phase 2: account creation + onboarding questions + tier selection (multi-session, in progress)

**Status: Backend chunks 1-5 ✅ COMPLETE (2026-06-02). iOS chunks 6-12 remaining.**

**Goal:** Build the rest of v1's onboarding. User progresses from `feedback_acknowledged` (Phase 1 done, anonymous) to `onboarding_completed` (real account, all questions answered, tier picked).

**Full spec lives in `TuJe_M8_Phase2_Spec.md`** — that doc is authoritative for M8. PLAN.md captures only the high-level summary.

**Scope summary:**
- HomePlaceholderView gets a new "Create your account" CTA
- Existing AccountCreationView (built weeks ago) wraps `/auth/upgrade-anonymous` — needs locating + verification
- LoginView for returning users (accessible via "Already have an account?" link)
- 8 onboarding question screens (one phase each, same UX pattern as GoalSelection/LevelSelection)
- TierIntroView ("Thank you, pick a tier") — repurposes the `account_verified` phase slot
- TierSelectionView with 3 horizontal cards (Free / Basic / Pro, monthly only)
- PaymentStubView (light visual stub, no real payment; tier still saved to DB)
- Final state: `onboarding_completed`

**Out of scope for M8** (deferred to future work): email verification, Apple/Google Sign In, forgot password, profile editing, account deletion, yearly plans, real payment processing (StoreKit 2), real entitlement enforcement.

**Phase progression goes from 16 phases to 24 phases.** Specifically, 11 new phases inserted between `account_credentials_entered` and `onboarding_completed`. `account_verified` is repurposed to `tier_intro_shown` (since email verification is out of scope).

**Data model:**
- 3 existing columns reused: `language_level`, `native_language`, `preferred_session_duration_minutes`
- 5 new columns to add: `last_french_usage`, `french_importance`, `languages_spoken_count`, `age_bracket`, `user_source`
- `subscription_tier` (existing) gets written by tier selection. `subscription_status` stays `'never_subscribed'` until real payment.

**Endpoint strategy:**
- Reuse `/auth/upgrade-anonymous` (already works)
- Reuse `/auth/login` (already works; may extend response to include `onboarding_phase`)
- New: `POST /users/me/onboarding-question` (generic dispatcher for all 8 questions)
- New: `POST /users/me/tier-selection` (persists tier choice)
- Reuse `/users/me/advance-onboarding-phase` for transition-only screens (tier_intro_shown → plan_tier_selected, payment_stub_acknowledged → onboarding_completed)

**Chunk plan (~12 chunks across multiple sessions; see spec doc for details):**
1. ✅ SQL migration (add 5 new columns) — DONE
2. ✅ Update ONBOARDING_PHASES list with 11 new phases + repurpose account_verified — DONE (also rebuilt CHECK constraint mid-chunk-3 per D-M8-07)
3. ✅ Generic question endpoint (POST /users/me/onboarding-question) — DONE
4. ✅ Tier selection endpoint — DONE
5. ✅ Extend /auth/login to include onboarding_phase — DONE
6. iOS: HomePlaceholderView CTA + locate AccountCreationView
7. iOS: LoginView + Keychain swap
8. iOS: Generic QuestionScreenView component
9. iOS: Wire 8 question instances
10. iOS: TierIntroView + TierSelectionView
11. iOS: PaymentStubView + final routing
12. End-to-end verification

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

**D21: Targeted back buttons in onboarding, NOT general "back from anywhere".** Per product spec, the user can revert two specific transitions only:
1. `goal_selected → cta_tapped` — back from LevelSelectionView to GoalSelectionView
2. `level_selected → goal_selected` — back from transition screen to LevelSelectionView

No other back transitions are allowed in the onboarding flow. Forward-only otherwise. This is intentionally minimal — onboarding is short, and "I picked wrong" is a rare-enough problem that we keep the surface area tiny.

**D22: Backend revert endpoint with EXPLICIT allowed-reverts.** Instead of relaxing `/users/me/advance-onboarding-phase` (which stays strict forward-only-by-one) OR managing back-state iOS-only (which would create state drift), we added a new endpoint `POST /users/me/revert-onboarding-phase` with body `{ "to_phase": "..." }`. The endpoint:
- Validates the `(current_phase, to_phase)` pair against a hardcoded whitelist (the two pairs from D21).
- If the pair is in the whitelist: UPDATE brain_user, return 200 `{ success: true, phase: to_phase, changed: true }`.
- If the pair is NOT in the whitelist: 400 `{ error: "invalid_revert", detail: "..." }`. Helpful detail distinguishes "wrong target from this current_phase" from "no reverts allowed from this current_phase".

Backend stays single source of truth; iOS just calls the right endpoint depending on direction. Strict invariants preserved. Verified working in M4 part 2 piece 3 backend testing (9 tests passed).

**D23: 16th phase `cta_tapped` between `home_first_view` and `goal_selected`.** Originally we collapsed "user is exploring HomeView" and "user tapped CTA" into one phase. Rémi later clarified the intent: `account_checked → home_first_view → cta_tapped` are three distinct moments that all map to the HomeView area but represent different states:
- `account_checked` — user just answered "I'm new"; HomeView starts loading
- `home_first_view` — scene fully loaded, CTA appears
- `cta_tapped` — user tapped CTA, transitioning to GoalSelectionView

This lets us track drop-off in the HomeView experience (loaded but didn't tap? loaded and tapped?). Backend ALLOWED_REVERTS table updated accordingly (back from LevelSelectionView lands at cta_tapped, where GoalSelectionView lives).

**D24: Trigger for `account_checked → home_first_view` advance = scene load completion.** Not a timer, not a gesture. The HomeView (eventually a Parisian video / layered render) takes time to load; when it's ready to be explored, the phase advances. This is deterministic (asset loaded or not), code-detectable, and matches the real product UX. For v1 placeholder (no real video yet), we simulate with a 3-second timer — when real video lands, the trigger becomes the video's `onReady` callback.

**D25: New endpoint `POST /users/me/onboarding-prefs/goal`** — partial form save (goal_id only), separate from the existing onboarding-prefs (which saves both goal_id + initial_level_bucket). Reason: with the form split into two screens (D19), the goal pick happens BEFORE the level pick. If we only save goal_id to backend on form completion (level submit), the resume-flow would break (user quits at LevelSelectionView, reopens at goal_selected phase, but goal_id is NULL in DB). The new endpoint preserves the invariant that **phase advance happens AFTER the data it represents is persisted**.

Endpoint also validates the goal_id exists in `brain_user_goal` (rejects unknown goal_ids with 400 + "Invalid goal_id — no matching goal found"). Defensive against iOS bugs or stale clients.

Existing `/users/me/onboarding-prefs` endpoint is unchanged — it stays the "save both" endpoint, called by LevelSelectionView's submit.

**D26: M5 feedback screen — show genuine data only, no fake CEFR estimates.** Original M5 vision (per pre-existing PLAN.md notes) was a "beautiful, brand-appropriate feedback screen that interprets the user's session_score into a CEFR-aligned verdict, considering what they self-reported at onboarding." Reality check during M5 discovery: the level system isn't wired for initial sessions yet. `brain_user.level` stays at 0 for new users — no performance-derived level is computed at session completion. So we can't honestly say "you're at A2 now" because we never computed that.

Decision: ship a feedback screen that shows what we genuinely have (session_score 0-100 + goal context), with a qualitative label for warmth, and skip the CEFR fakery. When the real level computation is built (regular-session work), M5 can be revisited.

**D27: M5 score persistence via UserDefaults bridge.** `SessionViewModel` is `@StateObject` owned by `SessionView`. When OnboardingView's switch re-renders to FeedbackView (at phase `initial_session_completed`), SessionView is unmounted and SessionViewModel dies with it. The captured `finalSessionScore` (a `@Published` Int?) is gone.

Solution: SessionViewModel persists session_id and session_score to UserDefaults at the moments they're set. FeedbackView reads from UserDefaults. Created `SessionKeys` enum (in `TuJe/Models/SessionKeys.swift`) as a single source of truth for the two key strings, since three classes touch them (SessionViewModel writes, FeedbackView reads, AppState clears on logout). Existing `anonGoalIdKey` pattern (private constants per class) wouldn't have worked for the multi-consumer case.

Future cleanup: when real session-resume logic is needed (e.g., for the regular-session flow), we may add a `GET /api/session/{id}` iOS service method. Not needed for M5's simple case.

**D28: M5 graceful degradation — no score in UserDefaults = generic message.** If a user reaches `initial_session_completed` without UserDefaults having a session_score (e.g., test fixtures, edge cases where SessionViewModel didn't run), FeedbackView shows "Session complete!" as the fallback message instead of "X/100 — [label]". The goal context line still shows (goal_id is on AppState, doesn't depend on UserDefaults). Continue button still works. This is intentional defense — the test path (chunk 5 simulator verification) actually exercised this graceful path and it rendered correctly.

**D29: M5 simulator test shortcut via TablePlus phase jump.** Original M5 verification plan was a full end-to-end test (cold launch → 7 interactions → FeedbackView). Pragmatic shortcut chosen: use an existing user, manually jump their phase to `initial_session_completed` via TablePlus (bypassing strict advance-by-one), force-quit + relaunch → AppState fetches fresh `/users/me` → router lands on FeedbackView. Tests routing, view rendering, graceful degradation, Continue button advance, and HomePlaceholderView terminal state — without requiring an actual 7-interaction session run. Accepted: this doesn't verify SessionViewModel's UserDefaults writes (those are mechanical and trusted by build); the value of running 7 actual interactions just to confirm two UserDefaults.set calls work isn't worth the time.

**D30: Milestone renumbering — insert Airtable CMS work as M6, push comprehensive walkthrough to M7, Phase 2 becomes M8 (2026-06-01).** The original PLAN.md had M6 as "Phase 1 v1 readiness (comprehensive walkthrough test)" and M7+ as Phase 2 (account/tier). After completing M5, Rémi identified a gap: the 18 initial session templates can currently only be populated via raw SQL in TablePlus. Running a comprehensive walkthrough test (M7) without first being able to manage content visually means testing with stale fixtures rather than realistic, intentionally-crafted learning sequences.

Inserting M6 — Airtable as CMS for the 18 templates with webhook sync to PostgreSQL — solves this. M7's comprehensive test then becomes meaningful (can test all 18 templates, multiple goal/level combinations, real content). M8 (Phase 2: account + tier) remains the final pre-launch milestone for v1.

The decoupling also matters for energy management: building Airtable schema + sync is a different mode of work from comprehensive iOS testing (more concrete, faster feedback loop, doesn't require staying in Swift mental model). Sequencing them apart respects how the work actually feels to do.

**D31: `resetTrackingForNewInteraction()` no longer manages `sessionInteractionId` (2026-06-01, M7 bug fix).** The helper was designed for the regular-session flow, where `fetchInteraction()` clears state, then `startInteraction()` later re-sets sessionInteractionId from the server response. But `loadInteractionForPlayback()` (initial-session flow) was also calling `resetTrackingForNewInteraction()` AFTER `startInitialSession()` had already correctly set sessionInteractionId — and there's no later set in this flow because the backend creates the session_interaction row inside startInitialSession itself. Result: sessionInteractionId was silently cleared right before iOS rendered the answer buttons; tapping a button triggered `submitButtonAnswer`, which had a `guard !sessionInteractionId.isEmpty else { return }` — silent early return, no log, no visible failure, just buttons that "didn't work."

Fix:
1. Removed `sessionInteractionId = ""` from `resetTrackingForNewInteraction()`
2. Added it explicitly to `fetchInteraction()` (regular flow) at the same point it used to fire (so regular-flow behavior preserved exactly)
3. Added defensive print logs to BOTH silent-guard sites: `submitButtonAnswer` and `submitSingleButtonTap`. Future silent-failure bugs will at least log a warning.

Lesson: shared helpers used by multiple flows must be careful about what state they clear. Either make the helper flow-agnostic (don't touch state owned by callers) or have each caller manage its own state. Silent guards make debugging much harder — the original guard was correct defensively but should have logged.

**D32: VideoPlayerView Coordinator tracks `playerIsReady` flag (2026-06-01, M7 bug fix).** Bug: consecutive interactions in the test template all used the same brain_interaction_id (INT202505090900), so iOS loaded the same Cloudinary video URL twice in a row. SwiftUI's `updateUIView(_:context:)` had `guard context.coordinator.currentURL != url else { return }` — when same URL, skipped `swapURL` entirely. But `swapURL` was responsible for invalidating the old AVPlayerItem status observation and setting up a new one. The new observation is what fires `onVideoReady` (→ sets `isLoadingVideo = false`). Skipping `swapURL` meant `onVideoReady` never re-fired, so the loading overlay persisted indefinitely on consecutive same-URL interactions.

This isn't only a test-data issue. Real templates may legitimately repeat a video (e.g., retry scenarios, "watch again" features, deliberate slot reuse). The fix must work for all cases.

Fix (Option 2 of 3 considered, chosen because it preserves the "don't unnecessarily reload" optimization):
1. Added `private var playerIsReady: Bool = false` property to Coordinator
2. In both `setupPlayer()` and `swapURL()`: reset `playerIsReady = false` at start; set to `true` inside the `.readyToPlay` branch of the status observation (alongside the existing `onVideoReady` call)
3. In `updateUIView`: when URL matches existing, check `playerIsReady`. If true, fire `onVideoReady` manually so loading state clears. If false, skip — the pending observation will fire when readyToPlay arrives.

Edge cases considered:
- Repeated updateUIView calls with same URL while ready → `onVideoReady` may fire multiple times. The closure sets `isLoadingVideo = false`; idempotent and harmless.
- Memory ordering between observation callback (KVO queue) and updateUIView (main thread) is technically a data race on the Bool. Acceptable: both outcomes (fire or skip) are safe. Worth noting for future refactoring if we encounter weirdness.

Lesson: SwiftUI's UIViewRepresentable lifecycle is subtle. The view representable's `updateUIView` runs whenever SwiftUI re-renders, but the underlying UIKit/AVFoundation state machine has its own lifecycle. Short-circuit guards in updateUIView must consider not just "is this redundant" but also "do downstream consumers expect a callback they only get via this code path." When in doubt, fire the callback.

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

- [x] **Backend:** Update `brain_user.onboarding_phase` CHECK constraint to allow all 15 phase values ✅ 2026-05-30 — dropped pre-existing `check_onboarding_phase`, added `brain_user_onboarding_phase_check`. Migrated 12 rows `phase_1_in_progress` → `level_selected`.
- [x] **Backend:** Define valid phase transitions (forward-only with skip rules) ✅ 2026-05-30 — strict forward-only-by-one for the new endpoint; existing endpoints (form submit, initial-session start/complete) allow forward-skip transitionally per D17/D19 (documented in code comments).
- [x] **Backend:** New endpoint `POST /users/me/advance-onboarding-phase` ✅ 2026-05-30 — all 5 behaviors tested (no-op, valid advance, forward-skip rejection, backward rejection, invalid phase rejection).
- [x] **Backend:** Modify `/api/initial-session/start` to atomically advance phase to `initial_session_started` ✅ 2026-05-30
- [x] **Backend:** Modify `/api/initial-session/complete-interaction` (Case A only) to atomically advance phase to `initial_session_completed` ✅ 2026-05-30
- [x] **Backend bonus:** Fix latent `logger` undefined bug in `user_routes.py` ✅ 2026-05-30 — added `import logging` + module-level logger; file had 6 `logger` references but no logger defined (would have crashed at runtime if hit).
- [x] **iOS Piece 1:** Refactor `TuJeApp.swift` routing — phase-based, not `goalId == nil` ✅ 2026-05-30. Single helper `shouldShowOnboarding(for:)` returns true for 9 Phase 1 phases. End-to-end verified.
- [x] **iOS Piece 1:** Refactor `OnboardingView.swift` to switch on phase, eliminate coordinator ✅ 2026-05-30.
- [x] **iOS Piece 1:** Add `advanceOnboardingPhase` to OnboardingService and `updateOnboardingPhase` to AppState ✅ 2026-05-30.
- [x] **iOS Piece 1:** Fix cold-launch stub (`phase_1_in_progress` → `not_started`) ✅ 2026-05-30.
- [x] **iOS Piece 1:** Delete `OnboardingCoordinator.swift` ✅ 2026-05-30.
- [x] **iOS Piece 2:** Wire each stub's "Next →" button to call `advance-onboarding-phase` + `updateOnboardingPhase` locally ✅ 2026-05-30
- [x] **iOS Piece 2:** Transition stub mic-permission flow (grant advances, deny shows alert with Open Settings deep-link) ✅ 2026-05-30
- [x] **iOS Piece 2:** Re-map: mic_authorized → conditions stub; combined disclaimer_confirmed + initial_session_started case with `.id("initial_session")` ✅ 2026-05-30

- [x] **Backend Piece 3:** New endpoint `POST /users/me/revert-onboarding-phase` with explicit allowed-reverts whitelist (per D22) ✅ 2026-05-30. Whitelist: `goal_selected → cta_tapped`, `level_selected → goal_selected`.
- [x] **Backend Piece 3:** New endpoint `POST /users/me/onboarding-prefs/goal` (saves goal_id + advances to goal_selected with goal-existence validation, per D25) ✅ 2026-05-30.
- [x] **Backend Piece 3:** Add `cta_tapped` phase to lifecycle (16 phases total, per D23) ✅ 2026-05-30. SQL constraint updated, ONBOARDING_PHASES list updated.
- [x] **iOS Piece 3:** Add `submitOnboardingGoal(goalId:token:)` to `OnboardingService.swift` ✅ 2026-05-31 (chunk 1).
- [x] **iOS Piece 3:** Add `revertOnboardingPhase(toPhase:token:)` to `OnboardingService.swift` ✅ 2026-05-31 (chunk 1).
- [x] **iOS Piece 3:** Split `TwoQuestionFormView` into `GoalSelectionView.swift` and `LevelSelectionView.swift` (per D19) ✅ 2026-05-31 (chunk 2). AppState.updateUserFromOnboarding signature updated to accept optional initialLevelBucket.
- [x] **iOS Piece 3:** GoalSelectionView submits via `/onboarding-prefs/goal`; LevelSelectionView submits via existing `/onboarding-prefs` ✅ 2026-05-31 (chunk 2).
- [x] **iOS Piece 3:** AccountCheckView as a real screen with two buttons ("I have an account" / "I'm new"). "I have an account" presents AuthView via `.fullScreenCover` ✅ 2026-05-31 (chunk 3).
- [x] **iOS Piece 3:** HomePlaceholderView shown at `account_checked` + `home_first_view`. 3-second auto-advance from account_checked (D24). Combined switch case preserves view identity, no flicker on transition ✅ 2026-05-31 (chunk 3).
- [x] **iOS Piece 3:** Re-map OnboardingView's switch — cta_tapped → GoalSelectionView; goal_selected → LevelSelectionView. TwoQuestionFormView.swift deleted ✅ 2026-05-31 (chunk 4). `cta_tapped` added to TuJeApp's `shouldShowOnboarding` Set.
- [x] **iOS Piece 3:** Back button on LevelSelectionView → reverts to cta_tapped. Top-left chevron, disabled during call, error message on failure ✅ 2026-05-31 (chunk 5).
- [x] **iOS Piece 3:** Back button on transition stub → reverts to goal_selected. OnboardingStubView extended with optional onBack closure (default nil preserves backwards compat for other stubs) ✅ 2026-05-31 (chunk 5).
- [x] **iOS Piece 3:** End-to-end simulator test ✅ 2026-05-31 (chunk 6). Walked through every phase + both back paths + forward to SessionView. All 14 advances + 2 reverts succeeded. No crashes.

**Deferred TODOs surfaced during piece 3 (next sessions):**
- [ ] **AppState.login():** clean up leftover anonymous token from Keychain when transitioning to .authenticated. Currently both tokens coexist briefly until next launch (not a bug — restoreSession prefers permanent — but worth cleaning up). TODO comment already added inline.
- [ ] **OnboardingService:** refactor candidate — consolidate `attempt`, `attemptAdvance`, `attemptSubmitGoal`, `attemptRevert` into a generic `performPost<Req, Res>` helper. ~95% structural overlap. Not blocking; deferred during chunk 1 to keep scope tight. TODO comment in file.
- [ ] **TwoQuestionFormView cleanup remainder:** GoalSelectionView and LevelSelectionView each have private duplicated `SelectionRow` (and LevelSelectionView additionally duplicates `LevelBucket` + `levelBuckets`). Triplication accepted during chunk 2; could now be extracted to shared file since TwoQuestionFormView is deleted.
- [ ] **HomePlaceholderView advanceFromLoading failure:** no retry button — user must foreground/background. Acceptable for placeholder; replace with proper onPlayerReady callback when real Parisian video lands.
- [ ] **AccountCheckView edge case:** user with `onboarding_phase=not_started` but already `.authenticated` would still see AccountCheckView. Current behavior: hides "I have an account" button via `if case .anonymous` guard. Acceptable.

### M5 — Feedback screen ✅ COMPLETE 2026-05-31

- [x] **iOS:** Build the post-initial-session feedback screen ✅ 2026-05-31. Shows session_score (0-100) + qualitative label (Good effort/Nice job/Excellent) + goal context. Continue advances to `feedback_acknowledged` → HomePlaceholderView terminal state. UserDefaults bridge for session data persistence across SessionView→FeedbackView transition (per D27).

**Deferred TODOs surfaced during M5 (next sessions):**
- [ ] **FeedbackView graceful degradation refinement:** When score is nil in UserDefaults, both the header and the score block show "Session complete!" — slight redundancy. Cleaner: omit the score block entirely when nil (header already conveys the message). Cosmetic, not blocking.
- [ ] **GET /api/session/{id} iOS service method:** Not needed for M5 (UserDefaults bridge is sufficient), but will be needed for resume-aware flows in regular sessions and for analytics. Add when regular-session work begins.
- [ ] **Real CEFR estimation:** When the level system is wired for initial sessions (currently `brain_user.level` stays at 0 — performance never updates it), revisit FeedbackView to show "estimated CEFR" alongside score. Per D26, this is deferred until real level computation exists.

### M6 — Airtable CMS for initial session templates ✅ COMPLETE

Engineering shipped (chunks 1-3, 5). Content work ongoing:
- [ ] Sync remaining 5 User Goal rows (GOAL2-GOAL6) via Airtable button clicks
- [ ] Populate remaining 17 templates × 7 = 119 Initial Interaction rows (your timeline)
- [ ] Consider fixing "carrier" → "career" typo in GOAL5 via Airtable edit

### M7 — Phase 1 v1 readiness (comprehensive walkthrough test) ✅ COMPLETE

End-to-end walkthrough verified for GOAL1 / level 0 template. Two bugs surfaced and fixed (D31, D32). Optional follow-ups:
- [ ] Re-run M7 walkthrough for other (goal, level) combinations once content is populated — verifies the template lookup works for all 18 combinations and not just the one tested
- [ ] Investigate `user_level=250` default in /answers-by-interaction URL when fresh user's level is 0 (not a blocker but worth understanding)
- [ ] Test resume behavior — quit app mid-session, reopen, verify lands at correct phase

### M8+ — Phase 2: account + tier (multi-session, see PLAN section 3)

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

