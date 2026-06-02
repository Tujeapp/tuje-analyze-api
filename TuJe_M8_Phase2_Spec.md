# TuJe M8 — Phase 2 Spec (Account Creation + Onboarding Questions + Tier Selection)

**Status:** Living document. Updated as M8 progresses.
**Last updated:** 2026-06-02 (initial spec)
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

**Progress bar:** Advances proportionally as user answers (questions 1 of 8 = 12.5%, etc.).

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
- Top: back arrow + progress bar (advances 1/8, 2/8, etc.)
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

### Backend chunks (M8.1)

**Chunk 1 — SQL migration + verify legacy columns**
- Discovery: verify `daily_time_commitment` and `date_of_birth` usage in code (read-only)
- Add 5 new columns to brain_user (nullable, no defaults except where sensible)
- No code yet — just migration

**Chunk 2 — Onboarding phase list update**
- Insert 11 new phases into `ONBOARDING_PHASES` list at positions 13-23
- Repurpose `account_verified` → `tier_intro_shown`
- No iOS impact (iOS doesn't enumerate phases; it just reads/sets them via the API)
- Verify advance validation accepts the new transitions via curl

**Chunk 3 — Generic question endpoint**
- New `POST /users/me/onboarding-question` with allowlist + value validation
- Pydantic models for request/response
- 8 question dispatch table (question_key → column + phase)
- Test via curl for all 8 question types

**Chunk 4 — Tier selection endpoint**
- New `POST /users/me/tier-selection`
- Sets subscription_tier + subscription_period
- Test via curl

**Chunk 5 — /auth/login extension (optional)**
- Add `onboarding_phase` to login response
- Saves iOS a round-trip after login
- Tiny change; could also be skipped if iOS finds round-trip acceptable

### iOS chunks (M8.2)

**Chunk 6 — HomePlaceholderView CTA + existing AccountCreationView discovery**
- Read what's there
- Find AccountCreationView, verify it calls /auth/upgrade-anonymous correctly
- Add CTA to HomePlaceholderView
- Wire CTA → AccountCreationView routing

**Chunk 7 — Login screen + Keychain swap**
- Build LoginView (or extend existing AccountCreationView with toggle)
- Wire /auth/login
- Handle Keychain swap (anon_token → auth_token)
- After login: call /users/me, route based on onboarding_phase

**Chunk 8 — Generic question component**
- Build a reusable QuestionScreenView component (since 8 screens share structure)
- Configurable: title, options array, progress %, callback on tap
- Hooks into POST /users/me/onboarding-question

**Chunk 9 — Wire the 8 question screens**
- Configure 8 instances of QuestionScreenView
- Hardcoded option lists (with localization-ready structure for future)
- Routing logic for each question's "next screen"

**Chunk 10 — TierIntroView + TierSelectionView**
- Build both screens
- Wire tier selection endpoint
- Tier card layout (3 horizontal cards)

**Chunk 11 — PaymentStubView + final routing**
- Build the stub screen
- Wire payment_stub_acknowledged → onboarding_completed transitions
- Test full M8 walkthrough end-to-end

**Chunk 12 — Verification**
- Full simulator walkthrough: feedback_acknowledged → onboarding_completed
- Test login flow with mid-questions resume
- Document any bugs surfaced, fix them

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
