# TuJe — Chunk 1 Progress Log (client phase + diagnostic tool)

**Status: Chunk 1 VOICE PATH FULLY VERIFIED end-to-end in the live app. Backend split + client A1+A2 + session→brain id fix all confirmed on device: adaptive session, spoken correct answer on INT202607041224 → verdict `perfect`, similarity 100, evaluate→commit→advance advanced through interactions. Diagnostic picker confirmed the analysis pipeline independently (also 100).**

**Fix applied this session (deployed):** `_evaluate_voice` in `answer_split_orchestrator.py` now resolves the session_interaction id → `brain_interaction_id` before calling the adjuster and matcher (they key on brain-id tables). `create_answer`/`update_answer_*` still use the session id. This was THE bug making correct voice answers score 0. Verified: same interaction scored 0 (before) → 100 (after), matching the diagnostic.

**Still-open bugs (surface only on WRONG answers — separate from Chunk 1):**
- ~~`GET /answers-by-interaction/{id}` returns 500 when rescue triggers~~ **FIXED & deployed.** Root cause: schema drift — the answer-selection engine (`_fetch_available_answers` + `_fallback`) filtered on `ba.display_ready`, which doesn't exist on live `brain_answer`; the real column is `ba.is_button`. Swapped both. Also added fail-soft in the `get_answers_by_interaction` route (`.get()` with defaults → returns clean `{answers:[], ...}` instead of raising). Verified 200 via curl on INT202607060926 (returned single "Bonjour" perfect answer, difficulty=fallback). A wrong answer no longer 500s.
- GPT fallback dead: `gpt_fallback_service.py` uses `openai.ChatCompletion` (removed in openai>=1.0). Throws on every `not_understood`, handled gracefully (no flow break). Needs SDK migration. Backlog.
- **Schema-drift audit (Chunk 5):** grep backend for other `display_ready` references — code was written against a schema partially not on live DB. `display_ready`→`is_button` may be assumed elsewhere.

---

## What's proven

- **Backend split (evaluate / commit / advance)** — curl + TablePlus verified end to end incl. idempotency. Deployed on Render. (See earlier Chunk-1 backend log.)
- **Client A1** — `APIService.evaluateAnswer/commitAnswer/advanceInteraction` + response models added. Clean build.
- **Client A2** — adaptive branch of `submitRecording`/`submitButtonAnswer`/`submitSingleButtonTap` now calls `evaluateAnswer`; `advanceAdaptive` does `commit`→`advance`; legacy flows preserved via `applyLegacySubmitResult` gated on `!isAdaptive`. Clean build.
- **Diagnostic tool (dev-only, fully parallel — no session/cycle/scoring):**
  - Backend `POST /api/diagnostic/analyze-answer` (brain_interaction_id + transcript → adjust+match metadata, writes nothing). Deployed.
  - Client `APIService.analyzeAnswer` + `DiagnosticAnalysisResponse` model.
  - `DiagnosticView` (typed text + mic), picker now opens it instead of a session (`HomeView` redirect).
  - **Test results:** spoken "ça va" → similarity **100** (answer optimum_level 50); typed "ça va bien merci" → 47.6 / no match (correctly — different phrase). Mic→Whisper→adjust→match chain works.

### Key conclusion from diagnostic
The **matcher works correctly** given a brain id (100 on a correct answer). So:
- The 47.6 was content/phrasing, not a bug.
- **A2 voice-scoring suspicion is now sharply testable:** `_evaluate_voice` passes the **session_interaction_id** to the adjuster+matcher, but those look up `brain_interaction`/`brain_interaction_answer` (brain-keyed). If, in a real adaptive session, a correct spoken answer scores **0** (not 100 like the diagnostic), we've confirmed a session→brain id resolution bug in `_evaluate_voice` and must resolve session→brain before matching. The diagnostic (brain id, scores 100) is the control case.

---

## Not yet verified

- **A2 through a live adaptive session in-app.** The picker now goes to the diagnostic view (correct), so there's still no in-app path to drive a full adaptive session and confirm evaluate→commit→advance + the two-panel-precursor feedback flow on device.
- **Cycle-end / session-end advance branches** (next_cycle / session_summary / already_advanced) — only fire at interaction #7 / cycle 3; not yet hit.

### Plan to enable A2 testing (Rémi's call)
No way to force a session/cycle onto a specific interaction. Instead: **author a minimum set of proper voice-answer interactions in Airtable** so a real adaptive session naturally serves testable voice interactions end to end. Then run a real adaptive session and compare a correct spoken answer's score against the diagnostic's 100 (settles the id-resolution question).

---

## Standing backlog (reliability / cost — priority)

1. **Per-request `asyncpg.create_pool` — IN PROGRESS.**
   - ✅ **Step 1 (done, deployed):** added app-lifetime pool via FastAPI `lifespan` in `main.py` → `app.state.db_pool` (min 2 / max 10), closed at shutdown. Additive; boots clean; `/health` healthy. NOTE: pool creation is now a BOOT dependency (DB down at startup = app won't boot) — acceptable, but a changed failure mode.
   - ✅ **Step 2 (done, verified live):** the three answer endpoints (`evaluate-answer`/`commit-answer`/`advance-interaction` in `routers/session_router.py`) now use `http_request.app.state.db_pool` instead of per-request `create_pool`/`close`. Added `http_request: Request` param (name `request` was already taken by the Pydantic body). Verified: perfect + wrong button answers advance cleanly, same behavior, no pool churn on the hot path.
   - ✅ **Step 3 / Tier 1 (done, verified live):** the three session-path endpoints migrated to `app.state.db_pool`: `answers-by-interaction` (data_access_routes.py — was a throwaway `create_pool`), `start-cycle` and `start-session` (session_management_router.py — were `create_pool min2/max10`). Pattern: `http_request: Request` param (Pydantic body already named `request`), `pool = http_request.app.state.db_pool`, dropped create/close. `start-session` was fussy (whole-function dedent to remove inner try/finally; done via parse-checked Python transform, not byte-exact edit, due to pervasive trailing whitespace). `/health` also migrated (audit). Verified: fresh adaptive session start→cycle→interaction→evaluate→commit all clean on shared pool.
   - ⏭️ **Remaining (deferred, lower value):** ~25 bare `asyncpg.connect(DATABASE_URL)` calls in data_access_routes.py (unpooled single connections, one per endpoint — WORSE than per-request pools). Plus per-request pools in: mood_recommendation + get_session_status (session_management_router), record-hint + complete_interaction, adjustement_models, matching_answer_router batch, gpt_fallback_service L68, and misc upload/legacy routers. These are Tier 2/3 (occasional or admin/legacy) — migrate the hot data_access read endpoints if latency shows, otherwise leave. Do NOT sweep. `airtable_routes.py` has its own lazy singleton pool (fine).
2. **commit→advance failure window** on flaky mobile networks: `advanceFailed` retry flag wired in Chunk 3 (Panel 2 shows "Retry"), untested in the wild.
3. **`start-session` runs notion-decay/streak/boredom synchronously** on the user's wait → move persistence to BackgroundTask.
4. ✅ **GPT fallback SDK migration — DONE & verified live.** `gpt_fallback_service.py` migrated to openai>=1.0: `from openai import AsyncOpenAI` + module-level `openai_client = AsyncOpenAI(api_key=...)` (replaced `openai.api_key`); `openai.ChatCompletion.acreate(...)` → `openai_client.chat.completions.create(...)`; `response.choices[0].message["content"]` → `.message.content`. Call args unchanged. **Verified live:** `not_understood` voice answer ("Toute petite kikoo", similarity 13) → `gpt_used: true` → Panel 1 rendered the interpretation "L'utilisateur essaie de se présenter malgré la transcription imparfaite". Full path lit: SDK → analyze_intent → _evaluate_voice → response → Panel 1. NOTE: `gpt_fallback_service.py` L68 still creates a per-request pool (create_pool) — left untouched (separate pool-migration concern).
5. **main.py drift audit — DONE.** Read the full live 297-line file. **No duplicate router includes** (the feared double `session_router` mount does NOT exist — project-knowledge fragments were stitched from different historical versions, creating a false impression). Findings, all low-severity: (a) `/api/session` hosts 2 routers (`session_router` + legacy `complete_interaction_router`) and `/api/bubble` hosts 2 (`mistakes_router` + `bubble_router`) — prefix-sharing, not collisions (distinct paths). (b) Legacy/dead surface: `match_router`, `mistakes_router`, `bubble_router` (Bubble-era, still mounted); root endpoints `/`, `/bubble-status`, `/modular-migration-info` are stale Bubble status JSON. (c) `openai.api_key = OPENAI_API_KEY` at main.py L58 is likely dead post-SDK-migration but UNVERIFIED (grep `openai.api_key|import openai` across repo before removing — some file may still use the global). **Fix applied & verified:** `/health` migrated from per-request `create_pool` to `request.app.state.db_pool` (added `Request` to fastapi import); `/health` returns healthy/connected. Decision: leave the legacy/cosmetic messiness alone — no bug, and main.py is fragile; Bubble-router + complete_interaction_router retirement is its own deliberate chunk for when regular/initial flows are removed.

6. ✅ **`display_ready` drift audit — DONE, clean.** `grep -rn "display_ready" --include="*.py"` across the repo returns **nothing** — the stale-column reference was fully contained to `answer_selection_service.py` (already fixed in the rescue-500 work). No other lurking references; no other latent 500. `is_button` (the correct column) is used consistently: `answer_selection_service.py` (L171/178/322, our fix) and `airtable_routes.py` sync (L600 column, L841 `"isButton": "is_button"` mapping). Origin of the drift: the Airtable sync always used `is_button`; only the answer-selection engine had drifted. Closed.

---

## Chunk map
1. ✅ Backend split (done). Client A1+A2 verified live.
2. ✅ **Button correctness + scoring — DONE & verified live.** `_evaluate_multiple_buttons` now derives verdict + score from `bia.answer_type` (not the linkage EXISTS check). Mapping: perfect→(100,"perfect"), good→(70,"good"), false good→(50,"wrong"), wrong→(30,"wrong"); unlinked/unknown→(0,"wrong") + warning. `matched_answer_id` set only for perfect/good. `commit_answer` multipleButtons branch uses the stored score (`int(round(similarity))`) instead of the old attempt-based `calculate_multiple_buttons_score`. Verdict vocab now unified with voice (perfect/good/wrong); client `verdictIsCorrect` already handles it. **Verified in live adaptive session:** perfect button → verdict perfect / 100; wrong button → verdict wrong / 30. Multi-select DEFERRED (no multi-select content yet). Single-select only.
3. ✅ **Two-panel verdict feedback — DONE & verified live.** B1: split `advanceAdaptive` into `commitAdaptive()` (Panel-1 confirm → commit only → `feedbackPanel=.recap`), `retryAnswer()` (dismiss, no commit), `advanceAdaptive()` (Panel-2 Continue → advance only, with `advanceFailed` retry flag). Added `@Published feedbackPanel/committedScore/advanceFailed`; submit methods reset `feedbackPanel=.answer`. B2: `FeedbackSheetView` rebuilt as two panels driven by `lastVerdict` + `feedbackPanel`. Panel 1 verdict-driven buttons: perfect→"Move on"; good→"Keep it"/"Retry"; wrong/not_understood→"Retry"/"Move on"(escape). Panel 2: score recap + Continue (→ `onFeedbackContinue`→advance; label "Retry" if `advanceFailed`). **Both panels non-dismissible** (killed the old swipe-to-dismiss limbo trap). B3 turned out unnecessary — `SessionView` already re-shows mic/buttons when sheet dismisses, so Retry works. Legacy/initial untouched (adaptive-only). **Verified live:** correct → move-on/keep-it → recap → continue → next; wrong → retry re-answers. Client-only.
4. **Rescue + hint — DEFERRED to the mistakes-system work (by design).** Rescue = voice→button mode downgrade when a user keeps failing; it depends on the mistakes design, so it's sequenced with that, not built now. **Left AS-IS (Option 1, untouched).** ⚠️ LATENT: `submitRecording` still calls `switchToMultipleButtons(rescueTriggered: true)` on a wrong voice answer, built pre-Chunk-3; it now fires alongside the two-panel Panel 1 and the two paths have NOT been tested together. Rémi has few wrong answers so far so it hasn't surfaced. If confusing wrong-voice-answer behavior appears (unexpected buttons, Retry ambiguity), the cause is this A2-rescue-trigger × Chunk-3-panel interaction — clean fix is to disable the `switchToMultipleButtons` trigger (Option 2) until rescue is built properly with the mistakes system. FrustrationTracker stays in code, effectively dormant.
5. Cleanups incl. **connection-pool lifespan fix (pull forward)**, submit-answer retirement, jsonb-serialize-in-service, GPT SDK migration (openai>=1.0), **display_ready drift audit**, calculate_multiple_buttons_score now dead for adaptive (attempt-based; legacy only).

**BUTTON GENERATION ENGINE — designed in full; realization CORE built & verified on live data. This is the harmonization of voice + button answers, and arguably the app's central IP.**

**Full design spec:** `/mnt/user-data/outputs/TuJe_Button_Selection_Engine_Spec.md`.

**The reframe:** `is_button` (exclusive: an answer is EITHER voice-match OR button) is being retired. An answer is just an answer; "can it be a button" is CONTEXTUAL/PURPOSEFUL, not a per-answer flag — the same answer can be a great button for one purpose and wrong for another. The engine decides which answers to present, why (purpose), and — crucially — GENERATES the button text, because most answers are entity-templates (e.g. `J'ai entityNumber entityPet`), not literal sentences. So it's a GENERATION engine, not just selection. The single-button-timer answer is carved out (listening-timing probe, its own thing).

**Two-level engine:** (1) pick answer TEMPLATES by purpose; (2) REALIZE each by filling entity slots with attribute-matched vocab → grammatical display strings. Curate (dedup by intent, cap, coverage).

**Grammar by attribute-matching, NOT computation (the key design win):** the template is pre-written correct French with an entity slot; the slot carries the article it requires (e.g. `un`); only vocab whose attributes accept that can fill it. `j'ai un chien` is producible; `j'ai un chatte` is structurally forbidden by the filter. No GPT, no morphology engine — pure authored attribute-matching. Rémi explicitly chose MORE authoring for full control, since this is core IP.

**Two attribute lists on vocab:** `attribute_ids` (OWN — what it is: gender, elision voyelle/consonne) and NEW `pairing_attribute_ids` (COMPANIONS — the articles it can take: un/le/mon...). Template's required attr union-matched against (own ∪ pairing). Elision (de/d') is an OWN attribute (what the word is); article (un/une) is a PAIRING attribute (what it goes with).

**Fractal typicality:** `answer_typicality` (0–1, on the join) = how central an answer is among the interaction's answers; `commonness` (0–1, on vocab) = how central a vocab is among its entity. Same "prefer the default, vary for purpose" idea at both levels.

**Two vocab levels (NEW):** `level_from` (when taught) + `level_own` (when owned, ≥ level_from). Rescue filters on `level_own ≤ user_level` (give strugglers vocab they KNOW); vocab-practice uses `level_from` (words being introduced).

**Controlling slots:** entityNumber resolved FIRST by rules (singular default; later: reuse user metadata like "has 2 dogs"), constraining dependent slots. Most entities are free (filled by vocab-selection). Numbers were historically the hardest case — resolving them first, by rules, is the tractable handling.

**`intent` replaces the planned `same_answer_ids` for dedup** — already authored, semantically principled ("same intent = same button meaning, different wording"). `same_answer_ids` kept in reserve for rare cross-intent lookalikes.

**REALIZATION CORE — BUILT & VERIFIED 5/5 on live data** (`button_realization.py`, backend, UNCOMMITTED). `realize_template(conn, transcription_fr, attribute_ids, user_level, max_fills)`: parse entity token (regex `entity[A-Z][a-zA-Z]*`) → map to `brain_entity` by `name` → select `brain_vocab` by entity + `level_own ≤ user_level`, rank `commonness DESC, transcription_fr` → keep where required attrs ⊆ (own ∪ pairing) → replace token with vocab `transcription_fr`. Fails safe on no-token/unknown-entity/multi-token(deferred)/no-vocab. Verified: `J'ai un entityAnimal`@100 → chat/chien/oiseau (âne excluded @150); `une`@100 → chatte/chienne; @200 → âne included; @40 → [] (level gate); literal → [] (caller uses as-is). Ties break alphabetically (deterministic).

**Test data seeded (live, real content via Airtable + hand-tag):** new cols `brain_vocab.pairing_attribute_ids/commonness/level_from/level_own`, `brain_interaction_answer.answer_typicality/never_a_button`. Six `entityAnimal` vocab tagged (chien/chat/chatte/chienne/âne/oiseau). Grammatical attributes authored (article/elision/gender/number). Three templates on INT202607041224 (`J'ai un/une entityAnimal` + literal negative).

**NEXT (button engine):** build the rescue-legibility CURATION (combine realized templates + literals → capped, deduped, coverage-aware set — decide max_fills distribution across templates, how literals/coverage count), then wire to `answers-by-interaction` (replacing the empty fetch), closing rescue's no-buttons gap. Then later: cycle-goal / mistake-contrast / inspiration purposes; scoring unification (a button reached via rescue scores through the SAME level-based 3-phase model, keyed off the answer not the mode → could retire split button-scoring); attribute unification; entityNumber user-metadata reuse. Commit `button_realization.py` + `test_realization.py` when ready (safe — nothing calls them yet).

---

**RESCUE SYSTEM — frustration brain BUILT & verified (escalation confirmed live); response-half + view layer + persistence remain.**

**Full design spec:** `/mnt/user-data/outputs/TuJe_Rescue_System_Spec.md` (settled model + deferred questions).

**Purpose:** app-initiated help for a struggling user who is NOT using hints (hints = user-initiated; rescue = app-initiated). Serves two populations with one mechanism: gently helps the sincere-but-stuck learner, and progressively constrains the non-serious mic-gamer into buttons until they show good will. A user who never shows good will stays locked — accepted outcome (TuJe isn't for mic-players).

**The frustration model (FINAL, all numeric):**
- Live frustration [0,1] within an interaction. Bands: 0–0.39 none; 0.4–0.59 `switchButton` (INVITE — toggle offered, mic stays); 0.6–0.79 `buttonsAboveMic` (AUTO-SWITCH); 0.8–1.0 `locked` (buttons only, no mic return).
- Within-interaction increments: Tier3 voice +0.2; Tier2 +0.1; Tier1 −0.1 (if >0); hint used −0.1; buttons-in-invite-band −0.1; buttons-in-autoswitch-band −0.1. All clamp [0,1].
- **Floor carry-over:** each new interaction starts at `previous_ending − 0.1`, clamped [0,1]. This one rule gives progressive-lock-but-recoverable automatically. `rescue_level` in `user_behavior` IS this floor (persists across sessions), **new-user default should be 0** (was 0.5).

**BUILT (client, verified):**
- `RescueUIState` — added `.locked` case (4 total, mapped to the bands).
- `FrustrationTracker` — rewritten to the numeric band model. `init(floor:)`, `recordTier1/2/3()`, `recordHintUsed()`, `recordButtonsAcceptedInInvite()`, `recordButtonsInAutoSwitch()`, `endingFrustration()`, `reset(toFloor:)`. Pure; band computed from live value; NOT monotonic (can fall through bands as good behavior eases). `recordHelpTapped`'s old +0.40 is gone — hint use now EASES (−0.1).
- `SessionViewModel` — marked `@MainActor` (no cascade). Both voice submit paths feed tiers → record calls. **The core fix: INVITE no longer force-swaps** — only `.buttonsAboveMic`/`.locked` auto-switch to buttons; `.switchButton` shows the toggle but keeps the mic. `switchBackToVoice()` guards against `.locked` (no return once locked). Both new-interaction reset blocks carry the floor (`ending − 0.1`) and reset the tracker to it. Both button-submit methods (`submitButtonAnswer`, `submitSingleButtonTap`) ease frustration when answering in a rescue band (adaptive path only; legacy button path unchanged).
- `rescueLevel` VM property repurposed as the carried floor (default 0.0).

**VERIFIED live (Test 1 — escalation):** clean user (floor 0), four not_understood voice answers → frustration 0.00→0.20→0.40→0.60→0.80, bands flipping at exactly 0.4/0.6/0.8 (`switchButton`→`buttonsAboveMic`→`locked`). Math and thresholds correct. Debug `print("🔥 RESCUE ...")` still in `FrustrationTracker.recomputeState()` — REMOVE before committing for real.

**⚠️ Test surfaced the deferred no-buttons gap concretely:** `INT202607041224` has NO authored buttons (`Answers loaded: []`), so when rescue auto-switched at 0.6/0.8 it fetched an empty button set — nothing to switch to. This is exactly the deferred "no buttons authored" case (spec §7c). Rémi is going to work on the button side before continuing rescue.

**WHAT'S LEFT (rescue):**
1. **The no-buttons fallback decision** (spec §7c, DEFERRED) — when an interaction has no authored buttons: auto-trigger Answer-hints (L1/L2/L3 at the 0.4/0.6/0.8 bands)? Or unify everything through the answer-ideas panel and drop authored buttons from rescue entirely? Hinges on whether `multipleButtons` mode is meaningfully different (scoring/UX) from picking in the L2/L3 hint panel. Rémi thinking about it + working the button side.
2. **View layer (Rescue-2, NOT built):** `SessionView` still renders rescue from old two-state assumptions (L620/946), has NO `.locked` affordance, and the switch-toggle component (left/right mic↔buttons with sliding circle) isn't built. The `.locked` return-to-mic is blocked at VM level but not hidden in the UI. Needs: build the toggle component; render invite/auto-switch/lock distinctly; hide switch-back when locked.
3. **Persistence (Rescue-1c, NOT built):** backend defaults `rescue_level = 0.50` in TWO places (`session_router.py:295`, `session_management_router.py:254`) → change to 0.0. And there is NO write-back path — nothing saves the updated floor. Need a write path (at interaction end / commit) to persist `ending − 0.1` to `user_behavior.rescue_level` so the floor survives across sessions. Currently the carry-over only lives in-memory within a session.
4. **Untested (need button-capable interaction or the fallback):** carry-over across interactions (Test 4 — next interaction should open at `ending − 0.1`); de-escalation (Test 3 — matched answer / buttons / hint easing); the actual buttons auto-switch + lock-to-buttons path.
5. **Minor:** the answers fetch sends `user_level = Int(rescueLevel*500)` = 0 (uses persistent floor, not live frustration) — decide whether button-difficulty easing keys off live frustration or the floor. Also: legacy button path gets no easing (accepted — legacy frozen). Also: whether timer expiry should feed frustration (still open; `recordTimerExpired` unfired).

---

**INTERACTION SCORING — WIRED & VERIFIED END-TO-END on clean data.**

Wiring (deployed): commit_answer's voice branch replaced with the 3-phase model, gated on matched_answer_id. matched → score (compute_interaction_score) → complete_interaction; matched but NULL optimum levels → warn + mark_interaction_incomplete (data problem, can't score); no match (forced past) → mark_interaction_incomplete (status='incomplete', interaction_score=NULL). Button paths (multipleButtons/singleButton) UNCHANGED — keep Chunk-2 score-off-similarity_score, always have a match. `mark_interaction_incomplete` added to interaction_service (status='incomplete', null score, still bumps cycle progress). Both complete_interaction and mark_interaction_incomplete count `status IN ('completed','incomplete')` for cycle progress (consistent — incomplete is still "done" from the flow).

**The debugging saga (all resolved — the scoring CODE was correct throughout):**
- 75 on a 50/50/0 interaction looked wrong (module returns 100 for those raw inputs) but was CORRECT: commit_answer had `user_level = interaction["cycle_level"] or 100`, turning the falsy 0 into 100, so scoring used cycle_level=100 → (50/50 + 50/100)/2 = 0.75 → 75. Arithmetically right.
- Re-runs kept returning the same stale score because commit is IDEMPOTENT (status='completed' → returns existing recap, no recompute). Only a never-before-committed interaction tests fresh code.
- **Root cause of cycle_level=0:** `calculate_cycle_level` (cycle_manager/cycle_calculations.py) first-cycle path returns `user_level` when no prior completed session matches — and the test user's `brain_user.level` was 0. Clamps used `max(0, ...)`. FIXED: all return paths + clamps now floor at 50 (`max(50, ...)`), since the app's minimum level is 50 and 0 is invalid. The `or 100` mask in commit_answer REMOVED (it hid this bug).
- **Deeper root cause:** the test user's history was polluted — 23 active + 4 incomplete abandoned test sessions, and the 6 genuine onboarding completed sessions were all level 0 / score 0 (onboarding never set a real level). The adaptive level logic correctly drove the level to the floor from all the abandoned runs. NOT a code bug — corrupted test data.

**Test-data hygiene established:** cleanup SQL deletes all active+incomplete sessions (child-first: session_answer by session_id AND interaction_id, then session_interaction, session_cycle, session) for the test user, preserving completed history. Safe to run repeatedly (idempotent scoped deletes). Run after every test session so the level logic reads only clean completed history. `brain_user.level` set to 100. `SESSION_SEED_LEVEL100` is now LOAD-BEARING (the level-100 completed anchor the first-cycle logic reads) — do NOT delete it.

**Verified:** after floor-fix deploy + data cleanup, a fresh session's first cycle derived level 100 (from the seed), and a perfect voice answer scored 100 end-to-end.

**Still open (separate, deeper):** why does onboarding leave `brain_user.level`/completed-session levels at 0? The genuine onboarding sessions are all level 0 — onboarding isn't establishing a real starting level. Worth its own investigation. Also: LISTEN_COUNT malus still needs the client to persist listen_count (only attempts_count populates today); hint-usage recording still deferred.

---

**INTERACTION SCORING — math BUILT & verified standalone; WIRING BLOCKED on a client-behavior question (deliberate stop).**

**Core principle (Rémi's key framing):** matching and scoring are SEPARATE systems. Matching returns *which* saved answer matched + its answer_type (similarity is a tool inside matching only). Scoring is a separate 3-phase calc that takes the match as input and derives its number from LEVELS, never similarity/verdict. This VOIDS the old "similarity vs verdict" concern — score was never meant to come from similarity. It REPLACES the Chunk-2 answer_type→score derivation (which stored score on similarity_score) for the voice/matched path. Button paths (multipleButtons/singleButton) keep their Chunk-2 score-off-similarity_score and are LEFT ALONE.

**Full design doc:** `/mnt/user-data/outputs/TuJe_Interaction_Scoring_Spec.md`.

**Three phases:**
- A. Gross Interaction Score = gross_score × coefficient, capped 100. gross_score = 100 on first SCORED answer (interaction_score IS NULL), else prior interaction_score (compounds). coefficient = ((answer_opt/interaction_opt) + (answer_opt/cycle_level)) / 2.
- B. Bonus-Malus Score = bonus_total − (malus_total × modulo). Modulo = session.modulo (default 0.5), damps maluses only.
- C. Interaction Score = A + B, rounded HALF-UP once at the end, clamped [0,100].

**Rounding:** half-up via `math.floor(raw + 0.5)` (NOT Python round(), which is banker's/half-to-even and would send 88.5→88). Applied once to the final only. NOTE: spec doc's first worked example originally said 87 — that was a hand-calc slip; 87.5 rounds half-up to 88. Corrected in the doc.

**GATING (Rémi's refinement — critical):** scoring runs ONLY when there's a matched answer. A not_understood answer, or a Tier-2 vocab-only match, does NOT score — it only accumulates as malus (via the already-incrementing attempts_count/listen_count), waiting for the user to finally give a matched answer. When they do, gross is still fresh (interaction_score was null) but accumulated maluses pull the final down — so a fumble-then-succeed user scores high gross minus the fumble cost. If the user abandons after not_understood, the interaction is LEFT INCOMPLETE (handled by another system, not scoring). Levels are always ≥50, so no div-by-zero.

**Engine adjustment DONE:** `evaluate_interaction_bonus_malus` now returns `bonus_total` + `malus_total` (positive magnitudes) alongside the existing signed `total_adjustment` (kept so debug endpoint still works). Phase B needs them separate because modulo scales maluses only.

**Scoring module DONE & verified:** `interaction_scoring.py` — pure functions (no DB): `compute_coefficient`, `compute_gross_interaction_score` (cap 100), `compute_bonus_malus_score`, `compute_interaction_score` (assembles, rounds half-up, clamps). Verified via /tmp/test_scoring.py against worked examples: gross ex1 = 88, gross ex2 = 67, full ex1 no-B/M = 88, ex1 with 20 malus @ modulo 0.5 = 78, coeff-2.0 cap test = 100. All consistent under half-up.

**Inputs available at commit** (confirmed): commit_answer already reads `cycle_level` (from session_cycle join). Old scoring_service.calculate_interaction_score shows the queries for `interaction_optimum_level` (brain_interaction) and `answer_optimum_level` (brain_answer by matched_answer_id) — reusable. `session_interaction.interaction_score` is the persistence target (exists).

**⚠️ WIRING BLOCKER — needs a client-behavior fact before writing:**
`interaction_service.complete_interaction` UNCONDITIONALLY sets status='completed' + writes score + bumps cycle progress. `commit_answer` calls it at the end of EVERY commit. The old voice scoring even scored unmatched answers (fell back to answer_opt = interaction_opt when matched_answer_id is None). The new model must NOT score/complete an unmatched answer. Which fix depends on an unknown:
- **Possibility A:** the client only calls /commit-answer once the user has a matched answer they're locking in (not_understood → client just lets them retry, never commits). Then gating already lives client-side; wiring = simply swap the scoring call.
- **Possibility B:** the client can call /commit-answer on a not_understood. Then commit_answer itself must gate: score+complete only on match, else leave the interaction open (active) for another attempt.

**NEXT SESSION — first thing to determine (in Xcode/client):** does the app call `/commit-answer` after a not_understood answer, or only once there's a matched answer to lock? That single fact decides whether gating is already handled (A) or must be added to commit_answer (B). Then: swap the voice branch in commit_answer to gather the 6 inputs (prior interaction_score-or-100, answer_opt, interaction_opt, cycle_level, bonus_total/malus_total from the engine, modulo) and call compute_interaction_score; write result via complete_interaction (A) or a new score-without-complete path (B). Test against 88/67 on real interactions, then with maluses firing + compounding on a 2nd attempt.

**Files (backend, uncommitted — commit when wiring lands, or commit the two done pieces now):** `bonus_malus_engine.py` (split totals), `interaction_scoring.py` (new module).

---

**BONUS-MALUS ENGINE (interaction scope) BUILT & verified standalone — NOT yet wired into scoring (deliberate).**

**Approach settled:** `rule_code` names the metric family (code knows how to compute it); `conditions` jsonb parameterises it (authorable in Airtable). A small, growing vocabulary of rule_codes; new *kinds* of trigger = one code addition, new *variations* = pure authoring. This resolves the rule_code-vs-conditions tension the table's schema hinted at.

**Taxonomy for authoring** (classify by what data a rule reads → determines when it's evaluable):
1. In-interaction behaviour (extra listens/attempts, hints used) — evaluated at interaction commit
2. Answer quality (perfect first try, recovered after wrong) — at commit
3. Cycle/session aggregate (no hints all cycle, all-perfect) — at cycle/session completion
4. User history (sustained improvement, mastered a hard notion, return after absence) — at session start/completion
5. Contextual (Christmas, time of day, streaks) — at session start

**Decisions:** additive points (not %); ALL applicable rules fire and SUM; clamp to [0,100] (caller's job, engine never clamps); `priority` is for later categorisation, not selection; `scope` column added (interaction/cycle/session).

**Schema added (TablePlus, NOT synced this conversation):**
- `brain_bonus_malus.scope varchar(20) DEFAULT 'interaction' CHECK (interaction/cycle/session)`
- `session_interaction.listen_count int DEFAULT 0` — **NEW, and the client does NOT populate it yet.** The app tracks `videoPlayCount` but doesn't persist it server-side. So LISTEN_COUNT can't fire on real data until that plumbing is added (send count at commit or incrementally). ATTEMPT_COUNT works today (`attempts_count` is populated).

**Two seed rules authored:** `BM_ATTEMPT_EXTRA` (ATTEMPT_COUNT, value 5, `{"free_threshold":1,"per_extra":true}`) and `BM_LISTEN_EXTRA` (LISTEN_COUNT, value 5, `{"free_threshold":2,"per_extra":true}`). conditions vocabulary: `free_threshold` (how many are free) + `per_extra` (multiply by count over threshold, vs flat once).

**Engine** (`bonus_malus_engine.py`, standalone): `evaluate_interaction_bonus_malus(session_interaction_id, user_level, db_pool)` → `{total_adjustment (signed, UNCLAMPED), applied:[{id,rule_code,name_en,adjustment}], skipped_rule_codes:[]}`. Loads live interaction-scope rules within `[level_from, level_to]` (null = unbounded), dispatches by rule_code to a handler, sums. **Pure evaluation — never reads or writes a score.** `clamp_score(gross, adjustment)` provided for the caller (one clamp definition). `_count_over_threshold` shared by attempt/listen handlers.

**Hardening (from Claude Code review):**
- **jsonb-as-string:** asyncpg may return `conditions` as a `str` (no codec registered). Loop normalizes: `json.loads` if str, else use as dict. Would have crashed otherwise.
- **Fault isolation:** each rule's eval is try/wrapped — a bad rule logs + joins `skipped_rule_codes` rather than 500-ing the whole score. Matters once dozens are authored.
- **Sign is strict:** `-1 if bonus_malus_type == "malus" else 1` — anything else (null/typo/"bonus") is a bonus. Safe for bonuses, risky for maluses; authored values were checked.
- Unknown rule_code → skipped with warning (fail safe).

**Verified live** via `GET /api/session/debug-bonus-malus?session_interaction_id=&user_level=` (debug-only, touches no score): forced a test row to attempts=3, listen=4 → `total_adjustment: -20` (ATTEMPT −10, LISTEN −10), both in `applied`, math hand-checkable. Row restored after.

**⚠️ SURFACED A PRE-EXISTING RULE:** `brain_bonus_malus` already contained a live row with `rule_code = "rule_BOMA202410021017"` (not authored by us). The engine correctly skipped it (no handler) — fail-safe proven on unexpected real data. **Rémi to check what it is** (`SELECT ... WHERE rule_code = 'rule_BOMA202410021017'`) — either give it a handler + recognizable rule_code, or set `live = false` if stale.

**NEXT — wiring into scoring:** the engine returns an adjustment; the scoring task applies `clamp_score(gross + total_adjustment)` at interaction commit. Entangled with the known voice-scoring defect (verdict is answer_type-based, score still similarity-based) — both belong to the scoring rework.

**Airtable (later):** `brain_bonus_malus` needs sync wiring (scope, rule_code, conditions, priority, level bounds); this conversation did TablePlus only.

**Hint ANSWER-L3 (French options + phonetic + audio) BUILT & verified in-app. THE HINT SYSTEM IS COMPLETE — both ladders, all six levels.**

**Schema:** added `brain_answer.transcription_phonetic`. The `/answer-ideas` endpoint (already serving L2) was widened to also return `text_phonetic`, `audio_normal_url`, `audio_slow_url` — so ONE endpoint serves both L2 (English) and L3 (French + phonetic + audio). Same composition, same randomised order.

**Audio escalation — DIFFERENT from the vocab blocks, deliberately:**
- Understand-L3 vocab blocks: auto-play normal → tap 1 normal → tap 2+ slow (once slow, stays slow). Diagnosing comprehension — someone who needs it slow keeps needing it slow.
- Answer-L3 options: **ALTERNATING** — odd tap = normal, even tap = slow, no auto-play. The learner is rehearsing something they're about to *say*, so toggling between natural and articulated is the useful motion.
- **Counters are PER ROW** (`answerAudioTapCounts[answerId]`), not shared across the panel. The above-mic reminder shares the counter with its panel row (same answerId key) — the count follows the answer, not the UI location.
- `answerIdeaAudioUrl(for:)` MUTATES the tap count, so it must only ever be called from a button action — never from a computed view property, or the alternation desyncs.

**Listen buttons are shown even when a row has no audio** (inert rather than hidden) — Rémi's call: a silent button surfaces a missing-audio content gap during testing, where conditional UI would hide it.

**Client:** `AnswerIdeaItem` widened (textPhonetic, audioNormalUrl, audioSlowUrl). SessionViewModel gained `showAnswerFrenchPanel`, `selectedAnswerIdeaFr` (a full `AnswerIdeaItem`, unlike the L2 reminder which is a bare String), private `answerAudioTapCounts`. `fetchAnswerHint()` routes `nextLevel == 3` → `openAnswerFrenchPanel()`. **L3 reuses L2's cached ideas when present** — same set, same order, so the learner sees the French versions of options they already considered in English.

**UI:** French panel at zIndex 68 (rows = French text + phonetic, tappable to select, plus a per-row speaker button). Selecting one calls `selectAnswerIdeaFrench(_:)` which nils `selectedAnswerIdeaEn` — **French replaces the English reminder** above the mic, per spec. The above-mic reminder branches French-first, and carries its own inline listen button.

Z-order final: 60 hints → 65 L3 vocab flow → 66 gate → 67 L2 ideas panel → 68 L3 French panel → 70 feedback sheet. The gate and vocab flow are modal (`contentShape` + empty `onTapGesture`); the two ideas panels deliberately are NOT (browsable/dismissible, tap-through is acceptable).

Verified in-app on INT202607041224 with a deliberately mixed content state: "Au revoir" had both audio urls (alternation audibly worked), "Voilà" had none (silent button — the visible gap). Selection replaced the English reminder correctly.

---

**Hint ANSWER-L2 (English answer-ideas panel) BUILT & verified in-app.**

**Backend:** `GET /api/session/answer-ideas?interaction_id=` → `{found, ideas:[{answer_id, text_en, text_fr}]}`. Samples the interaction's authored answers by `answer_type` to a **target composition: 1 perfect, 3 good, 1 false good, 1 wrong (6 max)**. The composition is a TARGET, not a requirement — short content returns fewer, and **types are never backfilled from one another** (no substituting extra perfects for missing goods). Randomises *within* each type before slicing (so the same 3 goods don't always appear), then shuffles the final list (so position never signals quality — the learner must not be able to spot the perfect answer by where it sits).

**One endpoint serves both L2 and L3** — it returns `text_en` AND `text_fr` per idea. L2 renders English, L3 will render French + audio. No new backend work needed for L3's list.

**Client:** `AnswerIdeaItem` / `AnswerIdeasResponse` models, `APIService.fetchAnswerIdeas`. SessionViewModel gained `showAnswerIdeasPanel`, `answerIdeas`, `selectedAnswerIdeaEn` (all reset per interaction). `fetchAnswerHint()` now BRANCHES: `nextLevel == 2` → `openAnswerIdeasPanel()` instead of a single text hint. `selectAnswerIdea(_:)` sets the above-mic reminder and closes the panel.

**Cached per interaction** — `openAnswerIdeasPanel()` refetches only when `answerIdeas` is empty, so closing and reopening shows the SAME set rather than a fresh shuffle (losing the option you were considering would be disorienting). Cache clears with the rest of the hint state on a new interaction.

**UI:** bottom sheet at zIndex 67 with a title, the instruction "Pick one, then say it in French yourself.", the idea rows, and a close X. Selecting a row closes the panel and shows that English text in a capsule directly above the mic button.

**Interaction with the reset rule (deliberate):** reaching L2 sets `answerLevel = 2`, and `onAnswerEvaluated` only resets when `answerLevel <= 1` — so once the learner opens the ideas panel, subsequent answers never reset the Answer button back to L0. Matches the spec's "at level 2 or 3, no reset possible, because the user got a clear answer given."

**No reopen path yet** — once at L2, pressing Answer targets L3. The above-mic reminder is the persistent trace. A tap-the-reminder-to-reopen affordance is the natural addition if wanted.

**Content note:** the composition only really shows itself once interactions have ~6 authored answers. INT202607041224 has 2 (1 perfect, 1 wrong), so the panel shows 2 — plumbing proven, composition untested at full size.

---

**Hint ANSWER button — Slice 1 (button + gate + reset rule + tier-routed L1) BUILT & verified in-app.**

**Evaluate response gained routing fields** (`answer_split_orchestrator.py` + `EvaluateAnswerResponse`): `tier` (1/2/3, null when no answer), `interaction_answer_id` (the matched join row — for Tier-1 hint routing), `attribute_mistake_ids` (which `brain_attribute_mistake` rows fired — for Tier-2 routing). `_fetch_tier2b_mistakes` now returns a TUPLE `(mistakes, attr_mistake_ids)` — all its return paths converted.

**Tier assignment rules (order matters):**
- Tier 1 when an answer matched (`answer_type` resolved).
- Tier 2 when mistakes surfaced without an answer match (2a or 2b).
- Tier 2c claims tier 2 only `if tier is None` (a match or mistake outranks "vocab implied an intent").
- Tier 3 claims only `if gpt_used and tier is None` — **a concrete mistake diagnosis outranks a GPT guess for hint routing.** (Initially written unguarded; corrected — otherwise 2b mistakes would be overwritten by tier 3 and the router would serve generic help while holding a specific diagnosis.)
- GPT failure (`gpt_used=False`) never claims a tier.
- 2a vs 2b is distinguished only by `attribute_mistake_ids` being non-empty (2b only runs when 2a found nothing). Deliberate — the ids carry the fine routing; the tier stays coarse (int).
- Button paths return `tier: null` → Answer hints fall back to interaction-level. Correct: buttons have no voice tier system.

**Backend:** `GET /api/session/answer-hint?interaction_id=&hint_level=&tier=&interaction_answer_id=&attribute_mistake_ids=` (comma-separated). Routes: T1 → `brain_interaction_answer.hint_ids`; T2 → `brain_attribute_mistake.hint_ids` (new column added); T3 + no-answer-yet → `brain_interaction.hint_ids`. **T3 and no-answer-yet are NOT distinguished yet** (deliberate — `applies_to_tier`/type filtering comes when content needs it). Tier-specific lookups FALL BACK to the interaction's hints when nothing authored — some help beats none, and avoids per-answer authoring before the button is useful.

**Client:** routing data passed BY THE CLIENT (it already holds it from evaluate; no server-side session lookup). `EvaluateAnswerResponse` Swift model was badly drifted — had none of `mistakes`/`matchedIntents`/`makesSense`; brought up to date plus the three new fields (all optional). New `MistakeItem`, `MatchedIntent` models. `APIService.fetchAnswerHint` (omits absent optional query items; joins attr ids with commas).

**State (SessionViewModel):** `answerLevel`, `answerHintText`, `showAnswerUnderstandGate`, `isFetchingAnswerHint`; private `lastAnswerTier`, `lastInteractionAnswerId`, `lastAttributeMistakeIds`. All reset per interaction.
- **GATE:** shows when `answerLevel == 0 && !understood`. Skipped ONLY by completing Understand-L3 (`understood == true`) — **partial Understand use (L1/L2) does NOT skip it.** (First implementation wrongly also skipped on any Understand press; corrected.) Both gate buttons proceed to L1 — informational, not branching.
- **RESET RULE:** `onAnswerEvaluated(tier:interactionAnswerId:attributeMistakeIds:)` is called from ALL THREE evaluate call sites (voice, multipleButtons, singleButton) inside their `MainActor.run` fan-out blocks — the reset must apply to button answers too. Stores routing data, then: `answerLevel <= 1` → reset to 0 (and clear shown text); `>= 2` → untouched.

**UI:** Answer button (text.bubble icon) stacked below Understand in a `VStack(spacing: 12)` on the right edge (trailing padding moved to the VStack so both align). Not engagement-gated — tappable from the start; the gate prompt is the soft check. Gate layer at zIndex 66. Pinned Answer-L1 text sits after the Understand elements. **Both the gate and the L3 flow overlays made modal** with `.contentShape(Rectangle())` + empty `.onTapGesture` — previously their dark backgrounds let taps fall through to the mic/nav controls beneath.

Z-order: 60 hints → 65 L3 flow → 66 gate → 70 feedback sheet.

**Remaining in hint system:** Answer-L2 (English ideas panel from `brain_answer.transcription_en`, select → write above mic), Answer-L3 (French options + phonetic + audio, reuse HintAudioPlayer, replaces the L2 reminder). Note `brain_answer` has `transcription_en/fr` + `audio_normal_url`/`audio_slow_url` but **no phonetic column** — L3 needs one added or ships without phonetic. Then the malus (needs `brain_bonus_malus`).

**Hint Understand-L3b (not-understood recording) DONE & verified live. THE ENTIRE UNDERSTAND LADDER IS COMPLETE (L1 → L2 → L3 + recording).**

Backend (deployed): `POST /api/session/record-not-understood-vocab` with `{session_interaction_id, vocab_ids[]}` → writes `session_interaction.not_understood_vocab_ids`. REPLACES rather than appends (L3 runs once per interaction — idempotent). Empty array is valid and meaningful ("ran the flow, understood everything") and distinct from never running it. A no-match id logs a warning rather than erroring.

Client: `APIService.recordNotUnderstoodVocab`. Fired from the completion branch of `l3AnswerCurrentBlock` — **completion-only** (an abandoned mid-flow is not recorded; accepted tradeoff for one call instead of N). Fire-and-forget in a Task with the error swallowed to a log: a recording failure must never disrupt the learning flow. Guarded on `sessionInteractionId.isEmpty` — so **L3b does NOT record when testing via the diagnostic picker**; a real session is required.

**ID SEAM (important):** the POST sends `sessionInteractionId` (session-scoped), NOT `currentInteractionId` (which holds the BRAIN id despite the generic name). Sending the wrong one writes nothing silently.

Verified live: real session on INT202607041224, marked the "passeport" block "I don't", completed the flow → `session_interaction.not_understood_vocab_ids = {VOCAB202506200544}`.

---

**Hint Understand-L3a (vocab-block comprehension flow) BUILT & verified in-app.**

Content model — mostly already existed: `brain_interaction.interaction_vocab_id` (_text, ORDERED array authored in Airtable, order verified preserved through sync) holds the vocab blocks; `brain_vocab` supplies `audio_normal_url` + `audio_slow_url` + `transcription_fr/en` per block. Added `brain_interaction.transcription_phonetic` (for the reveal) and `session_interaction.not_understood_vocab_ids text[]` (for L3b recording).

**ORDERING — critical:** blocks must play in authored order. `WHERE id = ANY(...)` does NOT preserve array order, so the serve endpoint fetches vocab rows then **re-orders in Python** against `interaction_vocab_id`'s array order. This is the single place ordering could silently break. Verification query for future authoring: `SELECT array_position(i.interaction_vocab_id, v.id) AS block_order, v.transcription_fr FROM brain_interaction i JOIN brain_vocab v ON v.id = ANY(i.interaction_vocab_id) WHERE i.id = '...' ORDER BY block_order;`

Backend (deployed): `GET /api/session/interaction-hint-l3?interaction_id=` → `{found, blocks:[{vocab_id, audio_normal_url, audio_slow_url, text_fr, text_en}], reveal:{transcription_fr, transcription_phonetic, transcription_en}}`. Own endpoint (not the single-hint one) since it returns a list. Gates on an authored live understand/level-3 hint. Skips missing/non-live vocab while preserving order of the rest — note this can yield `found=true, blocks=[]`, which the client treats as "don't start the flow."

Client (L3a):
- Models: HintVocabBlock (Identifiable), HintL3Reveal, InteractionHintL3. APIService.fetchInteractionHintL3.
- SessionViewModel: isInL3Flow, l3Blocks, l3CurrentBlockIndex, l3Reveal, understood, l3ShouldAutoplayBlock (@Published); private l3CurrentBlockTapCount, l3NotUnderstoodVocabIds. All reset per interaction. Methods: startUnderstandL3() (guarded on understandLevel==2), l3TapCurrentBlock() (tap escalation), l3CurrentBlockAutoplayUrl(), l3AnswerCurrentBlock(understoodThisBlock:).
- **Tap escalation per block:** auto-play = normal; tap 1 = normal; tap 2+ = slow. Tap count resets each block.
- SessionView: Understand button action BRANCHES — `understandLevel == 2` → startUnderstandL3(), else fetchUnderstandHint(). L3 overlay (zIndex 65) with title "Do you understand that vocab?", progress dots, 100pt dark-grey rounded square + 40pt speaker icon (both darken while hintAudioPlayer.isPlaying), horizontal red "I don't" / green "I do" buttons. Pinned translation reveal (fr/phonetic/en) shown only after completion (`!isInL3Flow && understood`).
- Completion: exits flow, sets `understood = true` (skips the future Answer-button gate), leaves l3Reveal for the pinned display.

Verified in-app on INT202607041224 (2 blocks: passeport, s'il vous plait, both with normal+slow audio): pressed L1→L2→L3, advanced through both blocks via "I do", flow closed into the pinned translation.

**L3b (remaining):** persist `l3NotUnderstoodVocabIds` to `session_interaction.not_understood_vocab_ids` on completion — the array already accumulates in memory; only the POST + endpoint remain.

Model A confirmed: the simplified audio lives on `brain_interaction` (new column `simplified_audio_url text`), and the L2 hint record is just the TRIGGER to look it up. Backend uses Option B: the hint endpoint joins to brain_interaction and returns `interaction_audio_url` in InteractionHintResponse alongside hint fields (returned for every hint, client uses it only for audio-kind). No change to the central interaction-load endpoint.

Content: `simplified_audio_url` set on INT202607041224 (a Cloudinary .mp3 under /video/upload/ path — Cloudinary serves audio there, normal). L2 hint `HINT_TEST_UNDERSTAND_L2_B` (button=understand, hint_level=2, media_kind=audio, own media_url empty since audio comes from interaction) linked via hint_ids.

Client — first audio-only playback infrastructure in the app (none existed before):
- New `TuJe/Services/HintAudioPlayer.swift`: @MainActor ObservableObject wrapping AVPlayer. play(urlString:) seeks-to-zero + plays (handles both autoplay and replay), sets AVAudioSession .playback category (audible regardless of ringer), @Published isPlaying resets via AVPlayerItemDidPlayToEndTime observer. deinit removes observer inline (can't call @MainActor cleanupObserver from nonisolated deinit). Reusable for future audio hints (Answer-L3).
- InteractionHint model gained `interactionAudioUrl` (CodingKey interaction_audio_url).
- SessionViewModel: @Published understandAudioUrl, shouldAutoplayHintAudio (set-true-once, view consumes+resets); both reset per interaction. fetchUnderstandHint() now switches on media_kind: text→pin text, audio→set URL + trigger autoplay.
- SessionView: @StateObject hintAudioPlayer; replay button (top-right below top bar, speaker/play icon toggles on isPlaying) shown when understandAudioUrl != nil, stacks with L1 text; onChange(shouldAutoplayHintAudio) plays once + resets flag.

Verified in-app: reach INT202607041224, Understand press 1 → L1 text pins; press 2 → simplified audio auto-plays + replay button appears; replay works multiple times.

**Audio-session caveat (watch, not yet solved):** HintAudioPlayer sets global .playback session shared with the video AVPlayer. If video is still playing when L2 fires, both could sound — but the listen-gate means video is normally done. Coordinate pausing video if overlap appears.

**Still ahead in hint system:** Understand-L3 (vocab-block comprehension flow — the hard one), Answer button + L1 (tier-routed) + gate + reset rule, Answer-L2 (English ideas panel), Answer-L3 (French options + audio — can reuse HintAudioPlayer), then malus math (needs brain_bonus_malus). brain_attribute_mistake still needs hint_ids for Tier-2 answer hints.

`brain_hint` recreated in TablePlus with the v2 schema (see TuJe_brain_hint_Schema_Spec.md): id, airtable_record_id, name, button, hint_level, "usage" (quoted — SQL keyword), type, media_kind, text_en, text_fr, text_phonetic, media_url, applies_to_tier, bonus_malus_id (nullable, unused until bonus-malus built), live, created_at, update_at. Old proficiency-range table (level_from/level_to/value) dropped — no real content. No last_modified_time_ref (siblings don't use it). All categorical fields (button/usage/type/media_kind) are plain author-managed text — code never hardcodes their values.

Test content: hint `HINT_TEST_UNDERSTAND_L1` (button=understand, hint_level=1, type=contextual, media_kind=text, placeholder text_en) linked via `brain_interaction.hint_ids` on INT202501300888.

Backend (deployed): `GET /api/session/interaction-hint?interaction_id=&button=&hint_level=` → resolves through brain_interaction.hint_ids, filters button+hint_level+live, returns `{found, hint_id, button, hint_level, type, media_kind, text_en, text_fr, text_phonetic, media_url}`. Returns found=false (200, not 404) when nothing authored. Uses shared pool. Takes brain interaction id directly. Verified via curl: L1→found=true, L2→found=false.

Client (builds clean, in-app test pending):
- APIService.fetchInteractionHint + InteractionHint model (APIModels.swift, snake_case CodingKeys).
- SessionViewModel: @Published hasListenedOnce/understandLevel/understandHintText/isFetchingHint; hasListenedOnce set true in onVideoFirstPlayEnded() (fires when first playback FINISHES, not on tap — corrected during build), reset per interaction in resetTrackingForNewInteraction(); fetchUnderstandHint() increments level only on found=true (caps at 3).
- SessionView: Understand button (right edge, lightbulb, dimmed+disabled until hasListenedOnce), pinned hint text banner below top bar. zIndex 60 (shares with debug error overlay — harmless, different regions).

**Design notes / deferred:** level increments only on found=true (won't run past authored content). No cooldown timer yet (isFetchingHint guards double-fetch; deliberate cooldown matters at L2/L3). No usage recording yet (deferred with bonus-malus). Button visible-but-dimmed pre-listen (not hidden). Placeholder styling/placement — restyle later (spec wants TikTok-style).

**Next hint slices (per TuJe_Hint_System_Design_Spec.md):** Understand-L2 (simplified audio + persistent replay button), Answer button + L1 (tier-routed) + gate + reset rule, Answer-L2 (English ideas panel), Answer-L3 (French options + audio), Understand-L3 (vocab-block flow), then malus math (needs brain_bonus_malus). brain_attribute_mistake needs hint_ids added for Tier-2 answer hints.

**The rule (Rémi):** Tier 3 fires ONLY when Tier 2 produced no intent match. Simplifies to: Tier 3 fires when `adjustment_result.list_of_intent_matches` is empty. At most ONE GPT call per evaluate.

**Tier 2c** = exposing what the adjuster already computes. `IntentMatcher.find_intent_matches` (adjustement_intent_matcher.py) already intersects each matched vocab's `expected_intent_id` with the interaction's `intents`, stored in `adjustment_result.list_of_intent_matches`. New helper `_fetch_intents_by_ids(intent_ids, db_pool)` resolves those ids to `{id, name}` via `brain_intent` (column is `name`, NOT name_fr — verified). If non-empty → surface as `matched_intents`, skip GPT entirely (`gpt_used: false`, `makes_sense: null`, `interpretation: null`).

**Tier 3** = `_run_gpt_tier3(brain_interaction_id, original_transcript, db_pool)` (replaced old `_run_gpt_interpretation`). Fires only when Tier 2c empty AND verdict not_understood. Returns `(matched_intents: list, makes_sense: bool|None, interpretation: str|None, gpt_used: bool)`. GPT prompt extended to also return `makes_sense`. All four GPT result-dict builders carry `makes_sense` through (`_create_success/no_match` = gpt value; `_create_no_candidates/error` = None).

**`makes_sense` semantics (Rémi, corrected via Test 3):** = relevance to the interaction's EXPECTED INTENTS, NOT to the interaction itself. Critical prompt fix: GPT was interpreting the interaction freely and rating an off-topic utterance as makes_sense:true. Reworded the prompt rule to "juge UNIQUEMENT par rapport aux intentions attendues; n'interprète PAS l'interaction elle-même," with the car-in-garage-vs-talk_about_job example baked in as a concrete false case. makes_sense = true if utterance plausibly expresses ANY expected intent's domain (even below match threshold); false if unrelated to ALL expected intents. Independent of matched_intents.

**Response fields added:** `matched_intents: list = []`, `makes_sense: Optional[bool] = None` on `EvaluateAnswerResponse` (also threaded through `_evaluate_voice` return). Both informational — verdict still determined by answer_type / no-match only.

**Design choice locked:** when Tier 2c resolves the intent, `interpretation` is dropped (GPT not called) — single-GPT-call model. Client Panel 1 (future) must render matched_intents without interpretation in that case.

**Verified live (3 curl tests):**
1. "j'allais euh blablabla" vs INT202501300888 (vocab VOCAB202607140844 + interaction both carry INTENT202508011004 talk_about_job) → `matched_intents: [talk_about_job]`, `gpt_used: false`, `makes_sense: null`. Tier 2c short-circuit confirmed.
2. "je m'appelle euh comment dire" (no vocab intent) → Tier 3: `gpt_used: true`, `makes_sense: true`, `matched_intents: []` (relevant but no exact expected-intent match — proves makes_sense/matched_intents independence).
3. "euh la voiture rouge dans le garage" (off-topic) → after prompt fix: `makes_sense: false`, `matched_intents: []`, `gpt_used: true`. Confirmed the expected-intents anchor.

**THE FULL VOICE MISTAKE + INTENT ESCALATION IS COMPLETE:** Tier 1 (answer match → answer mistakes) → Tier 2a (vocab match → vocab mistakes) → Tier 2b (attribute-diff → inferred mistakes) → Tier 2c (vocab intents ∩ expected intents) → Tier 3 (GPT intent + makes_sense, only if 2c empty). Every path individually verified live.

 New helper `_fetch_tier2b_mistakes(vocab_ids, brain_interaction_id, db_pool)` runs when Tier 1 didn't match AND Tier 2a returned nothing. Five internal steps: (1) fetch `brain_interaction.expected_attribute_ids`; (2) fetch `attribute_ids` for each matched vocab; (3) fetch `brain_attribute.important` per attribute — filter throughout, only important=true attrs are considered; (4) collect (vocab_id, odd_attr_id) pairs where odd = user's attribute NOT in expected_attribute_ids; (5) look up `brain_attribute_mistake` for each pair (attribute_matched_id=odd, vocab_matched_id=vocab, attribute_expected_id ∈ expected). Resolve mistake_ids → brain_mistake records. Silent on empty lookup (no fallthrough). Never raises: failure returns [].

Design decisions locked (per Rémi):
- Set-difference semantics (asymmetric): odd = user_attrs − expected_attrs. Missing-from-user, expected-but-absent: IGNORED.
- Vocab-specific mismatch rows: same odd attribute + same expected on different vocab = different pedagogical mistake. Rémi's tutor insight (wrong tense ≠ always conjugation).
- Return ALL mistakes on multi-mismatch.
- Silent empty on unfound triple; no Tier 3 fallthrough.
- `important=true` filter applied to attributes THROUGHOUT (not a gate, a filter): unimportant attrs never contribute to odd set.
- 2b gated on 2a returning nothing (`if not mistakes`): if 2a fired, 2a is authoritative — no double-fire.

**Verified live via isolated content control:** temporarily set `VOCAB202607140844.mistake_ids = '{}'` (silenced 2a), curl "j'allais euh blablabla" against interaction `INT202501300888` (`expected_attribute_ids = {ATTR202407190511 present}`). j'allais carries `{ATTR202407190510 imparfait}` (important=true). Response returned `MIST202407271502` — only 2b path could produce this since 2a was empty. All five steps exercised end-to-end. Vocab mistake_ids restored to `{MIST202407271502}` after test.

**Observability note:** couldn't distinguish 2a vs 2b results by response inspection alone (both surface into same `mistakes` array with no source tag). Confirmation required TablePlus check on `vocab.mistake_ids`. If further tier work / debugging becomes ambiguous, add `debug.mistakes_by_tier` field — deferred.

**The full voice mistakes escalation is now real:** Tier 1 (match → answer's mistake_ids) → Tier 2a (no match → vocab's mistake_ids) → Tier 2b (no vocab-direct mistake → attribute-diff lookup) → Tier 3 (GPT interpretation only; mistake extraction from GPT NOT built). Each path individually verified. This is the mistakes-detection foundation. Next in dependency chain: bonus-malus (first consumer of mistakes).



**Tier 2a (voice mistakes from matched vocab):** On a voice evaluate, if Tier 1 didn't match (no answer match), read `mistake_ids` from any matched vocab (via adjuster's `list_of_vocabulary`), resolve to `brain_mistake` records, and append to the `mistakes` array. New helper `_fetch_vocab_mistakes(vocab_ids, db_pool)` mirrors Tier 1's pattern but reads `brain_vocab.mistake_ids`. Same `mistakes` field as Tier 1 (no source tag; dedup by id in case both fire).

**Adjuster contraction bug FIXED (pre-existing, surfaced by 2a):** `adjustement_french_contractions.py` had `\bj'` → `"j "` (with space, splitting into two tokens), inconsistent with `j'ai`→`jai` and `c'est`→`cest` (which collapse). Vocab authored as `transcription_adjusted="jallais"` never matched because the pipeline produced `"j allais"` (split). Rémi's principled decision: `j'` should collapse like the other fixed-expression contractions; vocab is/will be authored as `jallais/jaime/jétais/...`. Fix: `\bj'` → `"j"` (no space). SYSTEMIC — affects every voice utterance containing `j'X`. Safety net: if a previously-working interaction fails, it's a signal to update that vocab's `transcription_adjusted` to the collapsed form.

**Debug observability added (opt-in, voice-only):** `EvaluateAnswerRequest` gained `debug: bool = False`; response gained `debug: Optional[dict]`. When set, response includes `{adjusted_transcript, vocab_matched: [{id, transcription_fr}], notion_matches, intent_matches}`. Voice-only (buttons don't have adjustment). Immediately paid off: made the contraction bug diagnosable in one curl cycle.

**Verified live:** curl "j'allais euh blablabla" with `debug:true` → `adjusted_transcript: "jallais vocabnotfound vocabnotfound"`, `vocab_matched: [{VOCAB202607140844}]`, `verdict: not_understood`, `mistakes: [{MIST202407271502 "Le placement du son (É)"}]`. Full pipeline lit end-to-end.

**Still-unbuilt (deferred to future sessions):**
- **Tier 2b (attribute-diff inferred mistakes):** the "right verb, wrong tense" path via `brain_attribute_mistake` join table (Rémi has already set the table in db). Needs attribute-per-category comparison, `useful_for_tier_2` boolean on `brain_attribute`, vocab-specific mismatch rows per Rémi's tutor logic. Real design effort — separate session.
- **Tier 3 mistake extraction from GPT fallback.** GPT itself is wired (interpretations flow); tier-3 mistake extraction not built.
- Button tier-1 mistakes (mechanical mirror of voice tier-1, deferred by Rémi's earlier scoping).
- Panel 1 display of mistakes (client-side UI, deferred to Chunk 3 enrichment).
- Scoring alignment (voice still scores by similarity, not answer_type; mismatch tolerated until "adjust scoring" step in chain).



**Voice verdict now derives from answer_type (quality), NOT similarity (match confidence).** Root concept (Rémi): match quality = "did we identify which answer they said" (internal); answer quality = answer_type (what the user cares about). Old `_voice_verdict(similarity)` conflated them — a 100% match to a *wrong* answer read as "perfect". Fixed: `_evaluate_voice` now fetches the matched join row's `answer_type` + `mistake_ids` in one query (`_fetch_answer_type_and_mistakes`), and verdict = `_answer_type_to_verdict(answer_type)` (perfect→perfect, good→good, false good/wrong→wrong); no match/NULL type → not_understood. Now consistent with the Chunk 2 button model. Old `_voice_verdict` left in as dead code (cleanup later). **Verified live:** "Au revoir!" (matched WRONG answer, 100% sim) → verdict `wrong` + mistake attached; "Voilà!" (matched perfect) → verdict `perfect`, no mistake.

**Tier-1 voice mistakes:** on a voice match, the matched `interaction_answer_id` (join row) → read its `mistake_ids` → resolve to `brain_mistake` records → return `mistakes: [{id, name_fr, name_en, description_fr, description_en, type}]` in the evaluate response. `EvaluateAnswerResponse` model got `mistakes: list = []`. **Verified via curl:** wrong-answer match returns `mistakes: [MIST202407271502 "Le placement du son (É)", type "Prononciation"]`. CRITICAL id note: the matcher returns BOTH `interaction_answer_id` (join row — used for mistakes/answer_type) AND `answer_id` (the answer) — they're different; mistakes key on `interaction_answer_id`.

**Scope line held:** mistakes are surfaced into the response only. NOT yet: Panel 1 display (client `🎤 ANSWER` log doesn't even print mistakes yet), NOT bonus-malus, NOT voice scoring-by-answer_type (voice still scores via similarity-based `calculate_interaction_score` at commit — so a wrong voice answer currently reads verdict `wrong` but may still SCORE high; scoring alignment is the later "adjust scoring" step). Tiers 2 (vocab-level mistakes, no answer match) and 3 (GPT fallback, no vocab) NOT built — tier-1 (match found) only.

## Mistakes system — three analysis tiers (Rémi's model, for the arc)
Voice mistake detection escalates through the existing pipeline:
1. **Match found** (DONE) — mistakes from the matched brain_interaction_answer join row.
2. **No match but vocab understood** — infer intent from vocabulary; mistakes from vocab marked with a mistake for this interaction. NOT built.
3. **Nothing coherent** (little/no vocab) — GPT fallback for rope/intent. GPT wired (not_understood), but tier-3 mistake extraction NOT built.



**Build order (strict dependency chain):** mistakes → bonus-malus → hints → scoring adjustment → rescue. Rescue is LAST — can only be designed once the rest is known.

**Core split: "mistake" means different things per answer mode.** Handle all three: voice (hard/central), multipleButtons, singleButton.

**Voice mistake detection — Rémi's key design (reuses existing matcher):** attach mistakes to the BRAIN ANSWERS, not to transcript analysis. Rémi will add *good* and *wrong* answers to `brain_answer`, each with mistakes pre-attached. When a voice transcript matches a *wrong* answer more than a correct one, the mistakes are already known = whatever's attached to that matched wrong answer. Mistake detection = "which answer matched + what mistakes it carries" — a content-authoring problem, not NLP.

**Schema already partially supports this:** `brain_answer.mistake_ids` (ARRAY) and `brain_interaction_answer.mistake_ids` (ARRAY) exist; `bia.answer_type` (perfect/good/false good/wrong) already used by Chunk 2.

**Open questions to resolve BEFORE building:**
- singleButton mistakes: a mistimed tap isn't a matched wrong answer — timing error, separate category, or N/A? Decide early — determines if "mistake" is uniform or mode-specific.
- multipleButtons: wrong pick = wrong-`answer_type` answer with its own `mistake_ids` → maps onto voice model. Confirm.
- Shape of a "mistake" record? (`brain_mistake` table? fields?) — discovery needed.
- How mistakes surface to the user (feedback panel enrichment — deferred Chunk 3 item).

**Approach:** design-first (70% is design). Start with discovery: `mistakes_routes.py`, the mistake schema/table, how the adjuster produces `list_of_mistakes`, `mistake_ids` usage. THEN design per-mode, THEN build.

## Resume here
Bank/commit client work. Author minimal voice-answer interaction set in Airtable → run a real adaptive session → verify A2 (compare spoken-correct score vs diagnostic 100). If 0, fix session→brain id resolution in `_evaluate_voice`.
