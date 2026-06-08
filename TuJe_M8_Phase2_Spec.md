# TuJe M8 — Phase 2 Spec (Account Creation + Onboarding Questions + Tier Selection)

**Status:** Living document. Updated as M8 progresses.
**Last updated:** 2026-06-03 (M8 COMPLETE — backend chunks 1-5 + iOS chunks 6-12 + 7b, all verified end-to-end. Open: AuthView/register investigation; progress bar dropped.)
**Owner:** Rémi

---

## 1. Goal

Complete v1's onboarding by enabling users to:
1. Convert their anonymous account to a real account (email + password)
2. Answer 8 onboarding questions (one screen each, same pattern as Phase 1 Goal/Level selection)
3. Pick a subscription tier (Free / Basic / Pro)
4. Acknowledge a payment-gate stub (no real payment yet)

After M8, v1 is feature-complete for launch.

---

## 2. User flow

```
[Phase 1 terminal state — feedback_acknowledged]
   ↓ user taps "Create your account to save your progress"
[account_creation_started]
   ↓ existing account-creation screen (email + password)
   ↓ on submit → /auth/upgrade-anonymous → JWT swap
[account_credentials_entered]                  ← backend sets this directly
   ↓
[8 question screens, one phase each]
   ↓
[tier_intro_shown — "Thank you, pick a tier"]
   ↓ Continue
[plan_tier_selected — user picks Free/Basic/Pro]
   ↓ Continue
[payment_stub_acknowledged — visual stub]
   ↓ Continue
[onboarding_completed — terminal]
```

The 8 questions in order:
1. LevelExpectedSelection — "What level of French conversation do you need?"
2. LastTimeUseFrenchSelection — "When was last time you used French to speak?"
3. NativeLanguageSelection — "What's your native language?"
4. ImportanceSelection — "How much is important for you to speak French?"
5. NbrOfLanguagesSpokenSelection — "How many languages do you speak fluently in total?"
6. UserAgeSelection — "How old are you?"
7. UserSourceSelection — "How did you find TuJe?"
8. TimePerSessionSelection — "How long do you want to commit per day?"

**Resume behavior:** If user closes app mid-questions, on next launch (after login) they resume at the question they were about to answer (based on `onboarding_phase`). Already-answered values stay in the DB.

**Back navigation:** User can go back to revise previous answers.

**Progress bar:** [DROPPED for v1 — revisit post-v1.] Advances proportionally as user answers (questions 1 of 8 = 12.5%, etc.).

**Login path:** Available from the account creation screen via "Already have an account? Log in" link. After login, iOS reads `onboarding_phase` from `/users/me` and routes to the appropriate screen.

---

## 3. Out of scope for M8

- Email verification (the `account_verified` phase is being REPURPOSED to `tier_intro_shown`)
- Apple Sign In / Google Sign In
- Forgot password / password reset
- Profile editing (will be added later in user view / settings)
- Account deletion (will be added later in user view / settings; required for App Store eventually)
- Yearly subscription plans (monthly only for M8)
- Real payment processing (StoreKit 2, receipt validation, App Store Server Notifications V2)
- Real entitlement enforcement (Pro users get visible tier in DB but no actual gated features)
- "Another language" follow-up text entry (just save as "other")

---

## 4. Phase progression — final ONBOARDING_PHASES list

24 phases total. Phase numbers 0-10 unchanged from Phase 1. Phases 11-12 unchanged. **Phase 13 (`account_verified`) being REPURPOSED.** Phases 13-23 are M8 work.

```
0.  not_started
1.  account_checked
2.  home_first_view
3.  cta_tapped
4.  goal_selected
5.  level_selected
6.  mic_authorized
7.  disclaimer_confirmed
8.  initial_session_started
9.  initial_session_completed
10. feedback_acknowledged                ← Phase 1 ends here

11. account_creation_started             (existing, M8 starts here)
12. account_credentials_entered          (existing, set by /auth/upgrade-anonymous)
13. expected_level_selected              (NEW)                     ← was account_verified
14. last_french_usage_selected           (NEW)
15. native_language_selected             (NEW)
16. importance_level_selected            (NEW)
17. languages_count_selected             (NEW)
18. age_bracket_selected                 (NEW)
19. user_source_selected                 (NEW)
20. daily_commitment_selected            (NEW)
21. tier_intro_shown                     (NEW — replaces account_verified semantically)
22. plan_tier_selected                   (existing)
23. payment_stub_acknowledged            (NEW)
24. onboarding_completed                 (existing, terminal)
```

Validation is strict +1 step (per existing `/users/me/advance-onboarding-phase` logic). Inserting new phases into the list automatically registers them as valid transitions.

---

## 5. Data model

### 5.1 Existing columns reused (no schema change)

| Question | Column | Type | Notes |
|---|---|---|---|
| LevelExpectedSelection | `language_level` | varchar, nullable | 5 options (Like a first time tourist, Like a confident tourist, Like an expat, Like a native speaker, Like you Master Rémi) |
| NativeLanguageSelection | `native_language` | varchar, default `'en'` | 9 options (American English, British English, Spanish (Latin America), Spanish (Spain), Russian, Italian, German, Another language). **NOTE:** existing default is `'en'` (assumed-English UI string). M8 overwrites it with the user's actual native language choice. |
| TimePerSessionSelection | `preferred_session_duration_minutes` | smallint, default 15 | 3 options (15, 30, 45) stored as integer |

### 5.2 New columns to add to brain_user

5 new columns. SQL migration TBD in chunk 1.

| Column | Type | Possible values | Question |
|---|---|---|---|
| `last_french_usage` | varchar, nullable | "today", "few_days", "month_or_two", "year_or_last", "never" | LastTimeUseFrenchSelection |
| `french_importance` | varchar, nullable | "cool_but_not_priority", "might_need", "need_pretending_not", "5_stars_but_wont", "life_or_death" | ImportanceSelection |
| `languages_spoken_count` | smallint, nullable | 1, 2, 3, 4 (where 4 = "more than 3") | NbrOfLanguagesSpokenSelection |
| `age_bracket` | varchar, nullable | "under_20", "20_plus", "30_plus", "40_plus", "50_plus", "60_plus" | UserAgeSelection |
| `user_source` | varchar, nullable | "instagram", "youtube", "tiktok", "online_ads", "google", "news_article_blog", "app_store", "family_friends", "other" | UserSourceSelection |

All new columns: nullable (so existing rows aren't broken; populated as user answers each question).

### 5.3 Tier-related columns (existing, no schema change)

- `subscription_tier` (varchar, NOT NULL, default `'free'`): values `'free'`, `'basic'`, `'pro'`
- `subscription_status` (varchar, NOT NULL, default `'never_subscribed'`): values `'never_subscribed'`, `'active'`, `'grace_period'`, `'expired'`
- `subscription_period` (varchar, nullable): for future yearly support; M8 sets to `'monthly'` for paid tiers, NULL for free
- `subscription_expires_at` (timestamp, nullable): not set by M8 (payment is a stub)

### 5.4 Schema follow-up

Before writing the migration, verify in chunk 1 discovery:
- Is `daily_time_commitment` (varchar, nullable) used anywhere in code, or is it legacy? If unused, leave it for now (don't break things), but use `preferred_session_duration_minutes` for M8.
- Is `date_of_birth` (date, nullable) used anywhere? Probably not — M8 will leave it untouched and use `age_bracket` instead.

---

## 6. Backend API design

### 6.1 New endpoints

**`POST /users/me/onboarding-question`** — generic dispatcher

Request:
```json
{
  "question_key": "last_french_usage",
  "value": "today"
}
```

Response (200):
```json
{
  "success": true,
  "question_key": "last_french_usage",
  "value": "today",
  "phase": "last_french_usage_selected",
  "changed": true
}
```

Behavior:
- Validates `question_key` against an allowlist of 8 questions
- Validates `value` against the question's allowed values (server-side enum check)
- UPDATEs the corresponding column
- Advances `onboarding_phase` to the question's "selected" phase IF current phase is the one immediately before (otherwise leaves it; this allows revisits without phase chaos)

**`POST /users/me/tier-selection`** — tier persistence

Request:
```json
{
  "tier": "basic"
}
```

Response (200):
```json
{
  "success": true,
  "tier": "basic",
  "phase": "plan_tier_selected",
  "changed": true
}
```

Behavior:
- Validates tier in `["free", "basic", "pro"]`
- UPDATEs `subscription_tier`, sets `subscription_period = 'monthly'` if non-free
- Does NOT set `subscription_status` (stays `'never_subscribed'` until real payment)
- Advances phase to `plan_tier_selected`

### 6.2 Endpoints reused (no change needed)

- `POST /auth/upgrade-anonymous` — already exists, fully functional. iOS calls this with email + password + username from the existing account creation screen.
- `POST /auth/login` — already exists. **Gap:** doesn't return `onboarding_phase`. M8 iOS will need to call `GET /users/me` after login to read the phase. (Alternative: extend the login endpoint to include `onboarding_phase` in the response. Decision deferred to chunk 2.)
- `GET /users/me` — already returns `onboarding_phase`.
- `POST /users/me/advance-onboarding-phase` — used for `tier_intro_shown` → `plan_tier_selected` is NOT done here (that's the tier-selection endpoint). Used for `payment_stub_acknowledged` and `onboarding_completed` transitions.

---

## 7. iOS screens

### 7.1 Modified screens

**HomePlaceholderView terminal state** (currently shows "Welcome back to Paris" with no CTA):
- Add CTA: "Create your account to save your progress"
- Tapping it advances `feedback_acknowledged` → `account_creation_started` and routes to AccountCreationView.

### 7.2 Existing screen — needs locating and verification

**AccountCreationView (or whatever the existing screen is called):**
- Built weeks ago, per Rémi's note.
- Discovery task in chunk 2: find it, verify it calls `/auth/upgrade-anonymous` correctly, verify it handles the response (new JWT, Keychain swap).
- Needs a "Already have an account? Log in" link added (if not present).

### 7.3 Existing or new — login screen

**LoginView:**
- Accessible from AccountCreationView's "Log in" link.
- Email + password.
- Calls `POST /auth/login`.
- After success: swap Keychain to `auth_token`, call `GET /users/me` to read `onboarding_phase`, route accordingly.

### 7.4 New screens — 8 question screens

All follow the same pattern as GoalSelectionView / LevelSelectionView:
- Top: back arrow + progress bar (advances 1/8, 2/8, etc.) [DROPPED for v1 — revisit post-v1.]
- Title (the question)
- Vertical list of tappable rows
- Tap row → auto-advance (no Continue button)
- EXCEPTION: the 8th question (TimePerSessionSelection) has a "Continue" button at the bottom — UI per screenshot

### 7.5 New screen — tier intro

**TierIntroView:**
- "Thank you for creating your account."
- "To enjoy TuJe, pick a tier plan."
- Continue button → routes to TierSelectionView, advances phase to `tier_intro_shown` (already there, just confirms).

### 7.6 New screen — tier selection

**TierSelectionView:**
- 3 horizontal cards (Free / Basic / Pro)
- Each card has: tier name, price, feature bullets, "Choose" button
- Tapping Choose → calls `/users/me/tier-selection`, advances to `plan_tier_selected`, routes to PaymentStubView

Feature bullets (placeholder for M8, refine later):
- **Free**: Ad-supported, limited daily sessions, basic interactions
- **Basic ($11.99/mo)**: Ad-free, higher daily limit, all interaction types
- **Pro ($29.99/mo)**: Everything in Basic + anti-burnout mode + priority support

### 7.7 New screen — payment stub

**PaymentStubView:**
- "Payment will be added soon. For now, you're set up with [tier name]."
- Continue button → advances to `payment_stub_acknowledged`, then immediately to `onboarding_completed`, routes to true terminal home view.

### 7.8 Final terminal state

After `onboarding_completed`, the user lands on HomePlaceholderView's NEXT iteration (post-onboarding). For M8, this can be the same placeholder text or a slightly different message ("You're all set. More content coming soon."). True home view is future work.

---

## 8. Chunk plan

Estimated 8-12 chunks across multiple sessions. Order is bottom-up: backend first, then iOS bottom-up.

### Backend chunks (M8.1) ✅ COMPLETE (2026-06-02)

**Chunk 1 — SQL migration ✅ COMPLETE**
- Discovery confirmed `daily_time_commitment` and `date_of_birth` are dead schema (no code references); safe to ignore for M8
- Pre-migration baseline captured: 27 users, no NULLs on the 3 reused columns (`language_level`, `native_language`, `preferred_session_duration_minutes`)
- Added 5 new nullable columns to brain_user: `last_french_usage`, `french_importance`, `languages_spoken_count` (smallint), `age_bracket`, `user_source`
- All 4 tier columns verified present (`subscription_tier`, `subscription_status`, `subscription_period`, `subscription_expires_at`)

**Chunk 2 — Onboarding phase list update ✅ COMPLETE**
- Updated `ONBOARDING_PHASES` in user_routes.py: 16 → 25 entries
- Inserted 11 new Phase 2 phases at positions 13-23
- Repurposed `account_verified` slot (index 13) → `expected_level_selected`
- `tier_intro_shown` now sits at index 21 (semantically replacing the old account_verified meaning)
- **Bug found mid-flight (chunk 3 testing surfaced it):** the existing `brain_user_onboarding_phase_check` CHECK constraint in PostgreSQL also enforced the old 16-phase list. Dropped and recreated the constraint with all 25 phases. See D-M8-07.

**Chunk 3 — Generic question endpoint ✅ COMPLETE**
- New `POST /users/me/onboarding-question` with dispatch table mapping 8 question_keys → (column, expected_phase, value_map)
- Pydantic `OnboardingQuestionRequest` model; raw dict response matching house style
- Strict-phase rule: advance only when at expected_phase; UPDATE column only on revisit; reject (400) when out-of-order
- Numeric coercion working (e.g., wire value `"4_or_more"` → DB integer `4`)
- All 12 test cases passed (8 happy paths, 1 revisit, 1 out-of-order, 1 unknown key, 1 invalid value)
- **Bug found mid-flight:** `language_level` was `VARCHAR(10)` — too short for values like `"first_time_tourist"` (18 chars). Widened `language_level` and `native_language` to `VARCHAR(50)`. See D-M8-08.

**Chunk 4 — Tier selection endpoint ✅ COMPLETE**
- New `POST /users/me/tier-selection` with same strict-phase pattern as chunk 3
- Atomic UPDATE: `subscription_tier` + `subscription_period` (monthly for paid, NULL for free)
- `subscription_status` explicitly untouched (stays `'never_subscribed'` until real payment)
- Verified: free downgrade correctly writes NULL to `subscription_period` (asyncpg `None → NULL` mapping works)
- All 5 test cases passed (happy path, upgrade revisit, downgrade revisit, out-of-order, invalid tier)

**Chunk 5 — /auth/login extension ✅ COMPLETE**
- Added `onboarding_phase` to login SELECT statement and response `user` dict
- Saves iOS a follow-up GET /users/me round-trip after login
- Risk-free additive change (Swift Codable ignores unknown keys)
- Verified end-to-end: anonymous → upgrade → login → response contains `user.onboarding_phase`

### iOS chunks (M8.2)

**Chunk 6 — HomePlaceholderView CTA + AccountCreationView routing ✅ COMPLETE (2026-06-02)**
- DEVIATION: No pre-existing AccountCreationView was found. AuthView exists but is wired to /auth/register (creates a NEW row, no anonymous-data preservation) and was deliberately NOT used. Built a minimal AccountCreationView shell (TuJe/Views/Onboarding/AccountCreationView.swift) as the routing target instead.
- Upgrade plumbing (AuthAPIService.upgradeAnonymousUser + AppState.upgradeToPermanent, including the anon_token → auth_token Keychain swap) confirmed present and correct — but has NO UI caller yet. Chunk 7 wires the real form to AppState.upgradeToPermanent.
- Routing extended to include account_creation_started: OnboardingView switch (new case → AccountCreationView) + TuJeApp.shouldShowOnboarding set. Both previously stopped at feedback_acknowledged, which would have ejected the user to ContentView the instant the phase advanced.
- CTA "Create your account to save your progress" added to the feedback_acknowledged terminal state in HomePlaceholderView; advances feedback_acknowledged → account_creation_started via the existing advanceOnboardingPhase pattern.
- Verified end-to-end against Render (HTTP 200, changed=true): real CTA tap → endpoint → local state update → routes to shell.
- Carried into Chunk 7: (a) the Keychain swap is delete-then-save, not atomic — worth hardening when invoked under a real upgrade; (b) the "Already have an account? Log in" link (per §2 Login path) is still to build.

**Chunk 7 — Account-upgrade form + post-upgrade routing ✅ COMPLETE (2026-06-02)**
- SCOPE NOTE: chunk re-scoped from the original "login screen" framing. The primary Phase 2 path is the anonymous→permanent UPGRADE (not login), so chunk 7 built that. The login path ("Already have an account?" link) is deferred to chunk 7b — see Carried forward.
- Built the real 3-field upgrade form in AccountCreationView (username/email/password), replacing the chunk-6 shell. Client-side validation mirrors backend validate_username / validate_password_strength (ASCII checks, stricter-not-looser; server stays authority). Wired to AppState.upgradeToPermanent → POST /auth/upgrade-anonymous.
- DECISION: form is email + password + username (3 fields), NOT the spec §2 "email + password only". The upgrade endpoint REQUIRES username (typed str, no default; validates format + 409 on collision) and sets display_name = username. Showing the field is the zero-risk path vs. auto-generating a handle. Spec §2's 2-field preference is a future UX revisit, not a hard constraint.
- AuthView deliberately NOT reused for routing — its signup path calls /auth/register (creates a NEW row, orphans anonymous data). Only its form/validation/error-mapping PATTERN was lifted into AccountCreationView. AuthView stays as the .unauthenticated login root, untouched.
- Routing gap fixed (same pattern as chunk 6): account_credentials_entered was absent from BOTH TuJeApp.shouldShowOnboarding AND the OnboardingView switch, which would have ejected the upgraded user to ContentView the instant the upgrade succeeded — silently skipping all 8 questions. Added account_credentials_entered to the Set, plus a temporary holding shell (AccountCredentialsEnteredView) as the switch target. Chunk 8 replaces the shell with the first real question screen (expected_level).
- RELIABILITY: hardened the Keychain swap in upgradeToPermanent to save-then-delete (new auth_token saved BEFORE anon_token deleted), so a crash mid-swap leaves the new token present (recoverable) rather than neither.
- Verified end-to-end (real anonymous user, against Render): happy path → upgrade → holding shell, SAME user_id preserved (is_anonymous false, auth_provider email, phase account_credentials_entered, account_created_at set); error path → real 409 surfaces backend detail cleanly, state untouched, retryable; restore-on-relaunch → upgraded user rehydrates to holding shell from the permanent token.

**Carried forward into later chunks (from chunk 7):**
- Chunk 7b — ✅ COMPLETE (2026-06-02). In-onboarding login link. Added an isLoginMode toggle to AccountCreationView (one view, two modes — mirrors AuthView's toggle; AuthView itself untouched). Login mode hides the username field, swaps copy/button/validation, and calls a NEW AppState.loginFromOnboarding(email:password:) — distinct from the shared bare login(token:user:) so the cold-launch path is untouched. loginFromOnboarding mirrors upgradeToPermanent's cleanup: save auth_token → delete anon_token → clear anon UserDefaults, so the abandoned anonymous user leaves no stale client state. 401 error message is mode-aware ("Incorrect email or password" in login vs "session expired" in upgrade). Routing is purely via the root router on the returned user.onboarding_phase — no manual navigation. SCOPE: strictly the in-onboarding login link; the cold-launch returning-user path remains AuthView at the .unauthenticated root (separate, untouched). Verified end-to-end: anonymous user → login as existing account → routes to holding shell; abandoned anon row untouched server-side (reaped by 30-day retention); wrong-password and mode-toggle paths both clean. NOTE: login routes correctly only for phases whose iOS routing already exists (≤ account_credentials_entered today); returning users deeper in onboarding (question/tier/payment phases) will route correctly as chunks 8-11 add those screens to shouldShowOnboarding + the OnboardingView switch.
- Cleanup pass — investigate whether AuthView's signup branch + /auth/register are still reachable. ✅ RESOLVED 2026-06-03 (see the "AuthView/register investigation: ✅ RESOLVED" bullet below — register is reachable + intentionally kept; the anon_token leak it surfaced is fixed). [Original open-item text retained for history.]
- iOS Simulator Keychain quirk confirmed again during chunk 7 testing: Keychain survives app deletion (clears only on Erase All Content and Settings). Re-test of the upgrade form requires erasing the simulator Keychain or it restores the prior permanent token instead of showing the form.
- Cleanup — orphaned holding shells: ✅ DONE (2026-06-02). Deleted all 7 orphaned shell views (AccountCredentialsEnteredView, ExpectedLevelSelectedView, ImportanceLevelSelectedView, UserSourceSelectedView, DailyCommitmentSelectedView, TierIntroShownView, PlanTierSelectedView) via Xcode Move-to-Trash (updates pbxproj). Build clean. Each was zero-reference dead code from the chunk-6→11 shell-then-replace pattern. NOTE: this resolves the "orphaned-shell removal" mentions in the STILL DEFERRED bullets of chunks 8–11 — those are now done, even though their bullet text still lists them.
- Cleanup — SelectionRow dedupe: CONSCIOUSLY SKIPPED for v1 (resolves the "SelectionRow dedupe" mentions in chunks 8–11). Goal/Level's private SelectionRow (×2 identical) and QuestionScreenView's QuestionOptionRow are near-identical (~39 lines, file-private); duplication is harmless cosmetic debt, not a bug risk. Unifying would edit 4 files with a small layout-regression surface — not worth it now. TierCard stays separate (distinct layout). Revisit only if the row component needs a real change. (The AuthView/register investigation above remains genuinely open and is unrelated to this.)
- Back button (Q2–Q8): ✅ DONE (2026-06-02). BACKEND: added 7 pairs to ALLOWED_REVERTS in user_routes.py — consecutive *_selected phases, each (current_phase_user_is_viewing → predecessor), e.g. (expected_level_selected → account_credentials_entered) = Q2→Q1, through (user_source_selected → age_bracket_selected) = Q8→Q7. Deployed via Render. iOS: added optional `backToPhase: String?` to QuestionScreenView — nil = no back button (Q1), set = a chevron.left overlay (ZStack top-leading, mirrors LevelSelectionView) that calls revertOnboardingPhase(toPhase: predecessor) then updateOnboardingPhase. The 8 OnboardingView configs pass nil (Q1) / their predecessor *_selected phase (Q2–Q8). SCOPE: Q2–Q8 only; tier/payment screens stay forward-only (decision). NO PRE-SELECTION (decision): revert leaves the answer column intact server-side but the screen re-renders unselected and the user re-picks; the question endpoint's re-advance overwrites the column cleanly. Verified end-to-end against Render: walked Q1→Q3, reverted step-by-step all the way back to Q1 (each revert 200/changed=true, bottoming out at account_credentials_entered with no further back), then re-advanced forward with different answers that overwrote cleanly. Q1 correctly shows no chevron; reverted questions render empty.
- DOC NOTE: QuestionScreenView.swift's header comment still says "Back button: deferred to the next chunk" — now stale (back button is implemented). Harmless; strike on a future doc-touch.
- AuthView/register investigation: ✅ RESOLVED (2026-06-03). VERDICT: /auth/register is NOT vestigial — it's reachable (AccountCheckView "I have an account" → AuthView → "Sign up" toggle, or post-logout .unauthenticated root → AuthView → toggle) and INTENTIONALLY KEPT (decision): a logged-out user creating a brand-new account is a valid flow; an abandoned anonymous row is acceptable (server reaps after 30 days). So NO removal. BUT the investigation surfaced a real latent account-loss bug and fixed it: AuthView's bare AppState.login(token:user:) wrote auth_token but never deleted the leftover anon_token (its own TODO). Coexisting tokens were harmless while auth_token was valid (both currentToken + attachAuthHeader prefer auth_token), but once the permanent token expired (7-day JWT) or was rejected, restoreSession PRIORITY 1 would delete it and FALL THROUGH to PRIORITY 2, reading the stale anon_token and silently resurrecting the abandoned anonymous identity (wrong user_id, lost real-account access). FIX (option B): resolved login()'s TODO — it now deletes anon_token + the 3 stale anon UserDefaults keys (anonGoalIdKey, lastInitialSessionId, lastInitialSessionScore) on transition to .authenticated, byte-for-byte mirroring loginFromOnboarding. This fixes BOTH AuthView login and register paths at the source; with no stale anon_token to fall through to, a later auth_token rejection degrades to PRIORITY 3 (fresh anonymous user), not a resurrected ghost. Verified: fresh anonymous launch → "I have an account" → login as titi → landed correctly as permanent user in MainTabView. Side effect: AccountCheckView's AuthView-login and the chunk-7b in-onboarding loginFromOnboarding now behave identically on cleanup (the prior "two divergent login UIs" concern is now cosmetic, not a bug).
- OPEN (from AuthView investigation): GAP-2 — restoreSession PRIORITY 1 uses fetchCurrentUser, which throws on ANY non-200 including transient network errors, so a network blip at cold launch could delete a still-valid auth_token and fall through (now to a fresh anonymous user, since the token leak is fixed — so no ghost, but an unnecessary logout). Lower severity post-fix. Own hardening task: distinguish 401 from network error before deleting the token in PRIORITY 1.

**Chunk 8 — Generic question component + question 1 wired ✅ COMPLETE (2026-06-02)**
- Built reusable QuestionScreenView (TuJe/Views/Onboarding/QuestionScreenView.swift): configurable with questionKey + title + [QuestionOption(wireValue, label)]. One component drives all 8 questions; chunk 9 adds the other 7 as config + a routing case each.
- INTERACTION (decision, overrides spec §7.4's auto-submit-on-tap): tap-to-select + Continue button, matching GoalSelectionView/LevelSelectionView for consistency. Extracted the option row visual (QuestionOptionRow) to match the Goal/Level SelectionRow look (checkmark.circle.fill / tinted bg / accent border on select). NOTE: Goal/Level still carry their own duplicate private SelectionRow — deduplication CONSCIOUSLY SKIPPED for v1 (2026-06-03, harmless cosmetic debt — see Carried-forward block).
- Self-contained like Goal/Level: owns its OnboardingService.submitOnboardingQuestion call and updates appState via updateOnboardingPhase(response.phase) — server's returned phase is source of truth, no hardcoded string, no manual navigation. Uses updateOnboardingPhase (not updateUserFromOnboarding) because the answer column (e.g. language_level) isn't carried on the iOS User object — only the phase changes locally.
- CRITICAL contract honored: /users/me/onboarding-question advances the phase ITSELF (atomic write of answer column + onboarding_phase). The client calls ONLY that endpoint — NOT a separate advance-onboarding-phase — else the next question 400s out-of-order.
- Service: added OnboardingService.submitOnboardingQuestion(questionKey:value:token:) + OnboardingQuestionRequest/Response DTOs, mirroring submitOnboardingGoal (5xx-retry-once). value is String on the wire for all 8 (backend coerces the numeric ones — languages_count, daily_commitment).
- Routing: added expected_level_selected to shouldShowOnboarding + a temporary holding shell (ExpectedLevelSelectedView) as its switch target, so question 1's advance doesn't eject to ContentView. Replaced the account_credentials_entered case (was the chunk-7 holding shell) to render QuestionScreenView configured for question 1 (expected_level). AccountCredentialsEnteredView is now orphaned (✅ REMOVED 2026-06-03 in the orphaned-shell cleanup — see Carried-forward block).
- Question 1 (expected_level) wired + verified end-to-end against Render: tap an option → Continue → language_level written (e.g. 'expat'), phase advanced to expected_level_selected (changed=true), routed to the holding shell. 5 option wire values match the backend value_map exactly.
- DEFERRED to next steps: (a) back button on questions 2-8 — needs backend ALLOWED_REVERTS entries for the 7 question reverts + an answer read-back/pre-selection design (so a revisited question shows the prior choice); (b) progress bar (spec §7.4); (c) questions 2-8 wiring (chunk 9); (d) SelectionRow dedupe + AccountCredentialsEnteredView removal (cleanup). [STATUS as of 2026-06-03 — see chunk-7 Carried-forward block for authoritative record: (a) back button ✅ DONE (Q2-Q8; no pre-selection — empty-and-re-pick instead); (b) progress bar DROPPED for v1, revisit post-v1; (c) ✅ DONE chunk 9; (d) AccountCredentialsEnteredView removal ✅ DONE, SelectionRow dedupe CONSCIOUSLY SKIPPED.]

**Chunk 9 — Wire the 8 question screens ✅ COMPLETE (2026-06-02)**
- All 8 questions wired as QuestionScreenView configs in OnboardingView's switch, each rendering at its expected_phase and advancing to its *_selected phase via the chunk-8 self-advance contract (no separate advance call). Built in 3 tested batches: Q2-Q4, Q5-Q7, Q8.
- Phase→question mapping (renders AT → questionKey): account_credentials_entered → expected_level; expected_level_selected → last_french_usage; last_french_usage_selected → native_language; native_language_selected → french_importance; importance_level_selected → languages_count; languages_count_selected → age_bracket; age_bracket_selected → user_source; user_source_selected → daily_commitment (advances to daily_commitment_selected, the questions→tiers handoff).
- All 8 *_selected phases added to shouldShowOnboarding so no advance ejects to ContentView.
- Option labels authored (hardcoded in the configs). DECISION on age_bracket: wire values (20_plus etc.) are labeled as non-overlapping decade bands (Under 20 / 20–29 / 30–39 / 40–49 / 50–59 / 60 or older). Analytics caveat: 20_plus = the 20s decade, NOT "20 and up" — the wire code-name is misleading but the user-facing buckets are mutually exclusive. No backend change made.
- Both string→int coercion questions verified through the full stack: languages_count ("4_or_more"→4 etc.) writes integer languages_spoken_count; daily_commitment ("15"/"30"/"45") writes integer preferred_session_duration_minutes.
- Verified end-to-end against Render: full Q1→Q8 walk in one continuous run, all 8 columns written (incl. both ints), phase stepped cleanly to daily_commitment_selected, zero out-of-order 400s, zero ejections.
- Each batch left a temporary holding shell as its exit, replaced by the next batch's first question; the final one (DailyCommitmentSelectedView, "All set") is the live handoff to chunk 10. Orphaned shells (ExpectedLevelSelectedView, ImportanceLevelSelectedView, UserSourceSelectedView, plus AccountCredentialsEnteredView from chunk 7) left in place — batched into the cleanup, ✅ DONE 2026-06-03 (orphaned shells removed — see Carried-forward block).
- STILL DEFERRED (unchanged from chunk 8): back button on Q2-Q8 (needs backend ALLOWED_REVERTS for the 7 question reverts + answer pre-selection read-back); progress bar (spec §7.4); SelectionRow dedupe; orphaned-shell removal. [RESOLVED as of 2026-06-03 — see Carried-forward block: back button ✅ DONE (no pre-selection); progress bar DROPPED for v1, revisit post-v1; SelectionRow dedupe CONSCIOUSLY SKIPPED; orphaned-shell removal ✅ DONE.]

**Chunk 10 — TierIntroView + TierSelectionView ✅ COMPLETE (2026-06-02)**
- Built TierIntroView (renders at daily_commitment_selected) + TierSelectionView (renders at tier_intro_shown). Service: added OnboardingService.submitTierSelection(tier:token:) + TierSelectionRequest/Response DTOs, mirroring submitOnboardingQuestion.
- CHOREOGRAPHY (corrects spec §7.5, which wrongly said the user is "already at tier_intro_shown"): after Q8 the user is at daily_commitment_selected, NOT tier_intro_shown. So TierIntro's Continue performs a PLAIN advanceOnboardingPhase (daily_commitment_selected → tier_intro_shown) — there's no answer to persist, so it mirrors the mic/disclaimer stub pattern, not the self-advance pattern. Then TierSelection's Continue calls /users/me/tier-selection, which SELF-advances (tier_intro_shown → plan_tier_selected). Nothing in the backend produces tier_intro_shown; the client advance is the only way in.
- LAYOUT (decision, overrides spec §7.6's "3 horizontal cards"): 3 VERTICAL stacked cards, tap-to-select + Continue — horizontal would be unreadable on iPhone SE, and vertical matches the question screens' interaction. TierCard selected-state matches the question option rows (checkmark / tint / border). Prices ($11.99/$29.99) and feature bullets are spec §7.6 placeholders, hardcoded, non-load-bearing.
- Tier wire values (free/basic/pro) match backend ALLOWED_TIERS. subscription_period is server-derived (monthly for paid, NULL for free) — client sends only {tier}.
- Routing: added tier_intro_shown + plan_tier_selected to shouldShowOnboarding + switch. daily_commitment_selected now renders TierIntroView; tier_intro_shown renders TierSelectionView; plan_tier_selected → temporary holding shell (PlanTierSelectedView, replaced by PaymentStubView in chunk 11). Orphaned shells DailyCommitmentSelectedView, TierIntroShownView left in place (cleanup batch).
- Verified end-to-end against Render: TierIntro Continue advances to tier_intro_shown (changed=true); tier pick writes subscription_tier + period and self-advances to plan_tier_selected. Both period branches confirmed: paid (basic) → monthly; free → NULL (and free correctly OVERWRITES a stale monthly from a prior paid pick — the downgrade-revisit path). subscription_status stays never_subscribed throughout.
- STILL DEFERRED (unchanged): back button on Q2-Q8 + tier screens; progress bar; SelectionRow dedupe; orphaned-shell removal (now also DailyCommitmentSelectedView, TierIntroShownView). [RESOLVED as of 2026-06-03 — see Carried-forward block: back button ✅ DONE for Q2-Q8 (tier/payment screens intentionally forward-only, NOT given back buttons — decision); progress bar DROPPED for v1, revisit post-v1; SelectionRow dedupe CONSCIOUSLY SKIPPED; orphaned-shell removal ✅ DONE.]

**Chunk 11 — PaymentStubView + final routing ✅ COMPLETE (2026-06-02)**
- Built PaymentStubView (renders at plan_tier_selected), the final onboarding screen. Copy: "You're all set… set up with the [Tier] plan", button "Start learning". Real payment out of scope (no StoreKit) per spec §3.
- TIER NAME DATA-FLOW FIX: TierSelectionView only updated the phase, leaving the cached User.subscriptionTier stale, so PaymentStub couldn't read the just-chosen tier. Fixed at the source: added AppState.updateOnboardingPhaseAndTier(_:tier:) (sibling of updateOnboardingPhase, mirrors its exact User initializer, also sets subscriptionTier); TierSelectionView now calls it with response.tier. PaymentStub maps the wire value (free/basic/pro) → display name (Free/Basic/Pro), fallback "your plan".
- TWO STRICT +1 ADVANCES, PHASE-AWARE: Continue runs plan_tier_selected → payment_stub_acknowledged → onboarding_completed as two separate advanceOnboardingPhase calls (backend rejects skips). finishOnboarding() guards each step on the current phase, so a partial failure (step 1 ok, step 2 fails) leaves the user at payment_stub_acknowledged and a retry resumes at step 2 instead of re-running step 1 (which would 400 out-of-order).
- ROUTING: combined case "plan_tier_selected", "payment_stub_acknowledged" → PaymentStubView (normal entry + partial-failure re-entry render the same screen). Added payment_stub_acknowledged to shouldShowOnboarding. onboarding_completed intentionally NOT added — its absence routes the completed user to ContentView → MainTabView, the terminal (spec §7.8 "true terminal home"; no dedicated post-onboarding screen for M8 — MainTabView is it).
- DECISION (spec §7.8): no separate "You're all set / more coming soon" terminal screen built — PaymentStub itself carries the "You're all set" beat, then the user drops into the real MainTabView. Adding completion-specific messaging to MainTabView was rejected as mixing onboarding concerns into the main app surface.
- Verified end-to-end against Render: full uninterrupted walk Q1→Q8 → tier intro → tier (pro) → payment stub → onboarding_completed → MainTabView; DB pro/monthly/onboarding_completed. Partial-failure resume verified (staged at payment_stub_acknowledged: Continue fired ONLY the onboarding_completed advance, not the payment_stub one). Restore-after-completion verified (cold launch → MainTabView, not onboarding).
- ORPHANED SHELL added to cleanup batch: PlanTierSelectedView.

**Chunk 12 — Verification ✅ COMPLETE (2026-06-03)**
- Both end-to-end flows verified against Render with NO SQL staging of the path under test:
- TEST 1 — genuine cold-start full walk: erased simulator → fresh anonymous user created at launch → walked all of Phase 1 (account_checked → home_first_view → cta_tapped → goal/level → mic/disclaimer → real initial session, 7 interactions → feedback_acknowledged) → tapped account-creation CTA → REAL /auth/upgrade-anonymous with new credentials (titi@gmail.com) → Q1–Q8 (exercised a back button mid-questions) → tier intro → tier (pro) → payment stub → onboarding_completed → MainTabView. Single DB row confirmed: same user_id held the upgrade AND all 8 answer columns AND tier — is_anonymous=false, auth_provider=email, language_level/last_french_usage/native_language/french_importance/languages_spoken_count/age_bracket/user_source/preferred_session_duration_minutes all populated, subscription_tier+period set, onboarding_phase=onboarding_completed. Proves the chunk-6/7 → chunk-8 seam (real upgrade delivers to Q1) and the whole journey as one continuous user. Phase-1 entry (CTA, upgrade form) — untouched recently — had no staleness.
- TEST 2 — login-mid-onboarding resume: staged titi to native_language_selected (mid-questions) → erased simulator → fresh launch → entry screen "I have an account" → logged in as titi → landed EXACTLY on Q5 (french_importance, the screen that renders at native_language_selected), NOT at start, NOT MainTabView. Back chevron present + question rendered empty (consistent with Q2–Q8 back + no-pre-selection). Walked forward Q5→Q8 → tiers (basic, overwrote the leftover pro) → payment → onboarding_completed → MainTabView. Proves loginFromOnboarding (chunk 7b) routes correctly into deep question phases — which only became reachable once chunks 8–11 added those screens to shouldShowOnboarding + the switch.
- RESULT: M8 iOS onboarding is functionally complete and verified end-to-end. No bugs surfaced during verification.

---

## 9. Open questions / future work

- **Profile editing later:** Will add a Settings view with email/password/display_name editing, account deletion. Required for App Store submission eventually.
- **Forgot password:** Needs email service integration (e.g., SES). Future work.
- **Apple Sign In:** Required by App Store if any social auth is offered. Future work.
- **Real payment:** StoreKit 2, App Store Server Notifications V2, receipt validation, entitlement gating. Major piece of work.
- **Yearly plans + discount:** Currently `subscription_period` exists for this; M8 only sets `'monthly'`.
- **i18n:** All option labels are English-only in M8. Future work to localize.
- **Question data to Airtable:** The 8 question option lists are hardcoded in iOS for M8. Future work to drive them from Airtable like User Goal, IF the option lists ever need editing.
- **Analytics on `user_source`:** Once data accumulates, this is gold for marketing channel attribution. M8 just captures it.

---

## 10. Decisions log

(M8-specific decisions; will be ported to PLAN.md's main decision log on milestone completion.)

**D-M8-01:** Reuse existing columns where semantic overlap exists. Specifically `language_level`, `native_language`, `preferred_session_duration_minutes` absorb three of the eight questions. Reduces new column count from 8 to 5.

**D-M8-02:** Repurpose `account_verified` phase as `tier_intro_shown`. Email verification is out of scope for M8; the phase slot is reused for the "thank you, pick a tier" transition screen. Future email verification work would need a new phase elsewhere.

**D-M8-03:** Generic question endpoint over 8 separate endpoints. One handler with a dispatch table. Less code, easier to add a 9th question later, but loses some explicit per-question semantics.

**D-M8-04:** Use `age_bracket` (varchar with 6 options) instead of `date_of_birth` (date). User selects a bracket; we don't ask for exact birth date. Simpler UX, sufficient for M8's needs.

**D-M8-05:** Login response gap — `/auth/login` doesn't currently return `onboarding_phase`. M8 will likely extend the response to include it (chunk 5, optional). If skipped, iOS makes a follow-up `GET /users/me` call. Both work; extending the login response saves a round-trip.

**D-M8-06:** Resume mid-questions uses `onboarding_phase` as source of truth. User who closes app at question 4 returns to question 5 on next launch. Previously-answered values stay in DB; iOS doesn't re-show those screens. Matches Phase 1's resume behavior.

**D-M8-07: When updating `ONBOARDING_PHASES`, also update the corresponding CHECK constraint on `brain_user.onboarding_phase` (2026-06-02).** Chunk 2 added 11 new phases to the Python `ONBOARDING_PHASES` list. The list change alone was thought to be sufficient because the advance-onboarding-phase endpoint's validation is index-derived from the Python list. But the PostgreSQL table has its own enforcement layer — a CHECK constraint named `brain_user_onboarding_phase_check` that hardcoded the original 16 phase values. Updates that tried to write any of the new 11 phase strings (e.g., `expected_level_selected`) were rejected by the DB even though the Python code accepted them. Surfaced during chunk 3 testing (curl returned: "violates check constraint").

Fix: dropped the old constraint, recreated it with all 25 phases. The constraint is a useful defensive layer — keeps the DB self-validating even if Python code has bugs — so it's worth maintaining alongside the Python list.

**Lesson — discovery template gap:** When modifying any enum-like list referenced by a database column, discovery must search BOTH:
- Python code references (string literals, list entries, conditional checks)
- Database schema-level enforcement: CHECK constraints, ENUM types, triggers, default-value expressions

Code-only grep is insufficient. Add `pg_constraint` queries to the discovery template for any future enum-like list changes.

**D-M8-08: When designing wire values for an existing column, check `character_maximum_length` (2026-06-02).** Chunk 3 designed 5-char-or-longer wire values for `language_level` (e.g., `first_time_tourist` at 18 chars). The column was `VARCHAR(10)` — too short. asyncpg rejected the INSERT with "value too long for type character varying(10)". Surfaced during chunk 3's Test 1.

Fix: ALTERed `language_level` to `VARCHAR(50)`. Also defensively widened `native_language` (same `VARCHAR(10)` legacy cap, technically fit our values at 8 chars but tight against future additions).

**Lesson — discovery template gap:** When designing string-typed wire values for an existing column, discovery must verify the column's `character_maximum_length` constraint, not just its `data_type`. The 5 new columns we ADDED in chunk 1 were created as plain `VARCHAR` (no limit), so they're fine — but reused columns (`language_level`, `native_language`) carried legacy length caps from before the sync framework was even built. The check is:

```sql
SELECT column_name, data_type, character_maximum_length
FROM information_schema.columns 
WHERE table_name = 'X' 
  AND column_name IN ('reused_col1', 'reused_col2', ...);
```

Add this to the discovery template for any future "reuse existing column" decision.
