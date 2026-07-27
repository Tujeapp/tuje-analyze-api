# TuJe — Chunk 1 Implementation Spec
## Decouple evaluate / commit / advance (backend, additive)

**Status:** Spec for validation. No Claude Code instructions until this is approved and the one remaining file (§9) is read.
**Decisions locked:** Option 1 (commit at Panel-1 confirm, advance at Panel-2 Continue) → **3 endpoints**. Backend returns an explicit `verdict`. Approach: **additive new endpoints**, `submit-answer` left intact for legacy.
**Goal:** Stop fusing answer evaluation with interaction completion and advance. Evaluation returns a verdict only; completion happens on confirm; advance happens on Continue.

---

## 1. Why additive (no-break rationale)

- `submit-answer` → `process_user_answer_complete` → `_complete_interaction` currently **scores, completes, and advances in one call.**
- The **regular** flow already calls its own `completeInteraction`; the **initial** flow uses `InitialSessionService`. **Adaptive** is the only flow that relies on `submit-answer`'s fused advance.
- Render auto-deploys on push to `main`. Modifying `submit-answer` in place creates a deploy window where the backend has changed but the adaptive client hasn't — adaptive breaks until the client ships.
- **Therefore:** add three new endpoints that reuse the existing service functions; leave `submit-answer` untouched. Deploying the new endpoints breaks nothing (they're unused until the client switches). We curl-test the full new spine, then switch the adaptive client (separate chunk), then retire `submit-answer` + legacy flows in cleanup.

This makes Chunk 1 a **pure backend addition** — the safest possible shape for surgery on the completion path.

---

## 2. The three new endpoints

All mounted on `session_router` (prefix `/api/session`), beside the existing `submit-answer`.

### 2.1 `POST /api/session/evaluate-answer`
Evaluates one attempt. Creates the answer row, increments the attempt counter, runs the mode pipeline, returns a **verdict + score (provisional, display-only)**. **Does not** mark final, complete, or advance. Retry = call again.

**Request** (same fields as today's `SubmitAnswerRequest`):
```
interaction_id: str            # session_interaction id
user_id: str
answer_mode_used: str          # "voice" | "multipleButtons" | "singleButton"
original_transcript: str?      # voice
selected_answer_id: str?       # multipleButtons
tapped_at_seconds: float?      # singleButton
```

**Response (`EvaluateAnswerResponse`):**
```
answer_id: str                 # client holds this; passes the chosen one to commit
verdict: str                   # voice: perfect|good|wrong|not_understood
                               # buttons/single: correct|incorrect
similarity_score: float
gpt_used: bool                 # true only when verdict=not_understood and GPT ran
interpretation: str?           # present only when verdict=not_understood
status: str                    # "evaluated"
```

### 2.2 `POST /api/session/commit-answer`
Locks the chosen attempt and completes the interaction. Fires on **Panel 1 confirm** (keep it / move on / accept). **Does not** advance.

**Request:**
```
interaction_id: str            # session_interaction id
answer_id: str                 # the attempt to keep (from an evaluate response)
```

**Response (`CommitAnswerResponse` — Panel 2 recap):**
```
interaction_id: str
interaction_score: int         # authoritative committed score
verdict: str                   # echoed from the committed answer
matched_answer_id: str?
attempts_count: int
completed_interactions: int    # cycle progress, e.g. 3
total_interactions: int = 7
interaction_complete: bool = true
```

### 2.3 `POST /api/session/advance-interaction`
Performs only the advance half. Fires on **Panel 2 Continue**.

**Request:**
```
interaction_id: str            # the just-committed session_interaction id
```

**Response (`AdvanceInteractionResponse` — same shape the client already decodes):**
```
cycle_complete: bool
next_interaction_id: str?
next_brain_interaction_id: str?
interaction_number: int?
next_cycle: NextCycle?
cycle_summary: CycleSummary?
session_complete: bool
session_summary: SessionSummary?
```
> These field names match the existing `SubmitAnswerResponse` next*/cycle*/session* fields, so the client's current decoding for advance is reusable.

---

## 3. What moves where (decomposition of `_complete_interaction`)

| Today, inside `_complete_interaction` | Goes to |
|---|---|
| mode-specific score (`calculate_interaction_score` / `calculate_multiple_buttons_score` / `calculate_single_button_score`) | **commit** |
| `answer_service.mark_as_final_answer(...)` | **commit** |
| `interaction_service.complete_interaction(...)` (sets completed, bumps `completed_interactions`) | **commit** |
| read interaction row (cycle_id, interaction_number, session_id, session_level, session_boredom, session_mood) | **advance** (re-fetch from `interaction_id`) |
| `check_cycle_complete(cycle_id)` | **advance** |
| if complete: `complete_cycle` → read `completed_cycles` → calc level/boredom/goal → `SessionContext.load` → `start_new_cycle` **or** `complete_session` + read session row | **advance** |
| else: read `candidate_pool_ids` → `advance_to_next_interaction` | **advance** |

The three `_process_*` functions: keep create/adjust/match/update logic, **remove the `_complete_interaction` call and the success-return**; instead compute `verdict` and return the evaluate payload. Their existing retry branches become `verdict = wrong | not_understood`.

**New orchestrator functions** (additive; existing ones untouched):
- `evaluate_user_answer(...)` — STEP 1 (create answer + increment attempt) + route to `_evaluate_voice` / `_evaluate_multiple_buttons` / `_evaluate_single_button`.
- `commit_answer(interaction_id, answer_id, db_pool)`.
- `advance_after_interaction(interaction_id, db_pool)` — the advance half above.

---

## 4. Verdict logic (voice) — placeholder thresholds

Constants at the top of the evaluate module, clearly marked **PLACEHOLDER — Rémi supplies real cutoffs:**
```
VERDICT_PERFECT_MIN = 95     # placeholder
VERDICT_GOOD_MIN    = 80     # placeholder (== current match threshold)
VERDICT_WRONG_MIN   = 50     # placeholder
# < VERDICT_WRONG_MIN  → not_understood
```
Mapping from `similarity_score`:
- `>= 95` → **perfect**
- `>= 80` → **good**
- `>= 50` → **wrong** (recognized, with mistakes)
- `< 50` → **not_understood** (GPT territory)

**Buttons / singleButton (Chunk 1):** return `correct` / `incorrect` using the **existing** correctness logic unchanged (linkage check for buttons, ±2s for single). The linkage→`answer_type` fix is **Chunk 2**, deliberately not bundled here. Noted so we're not surprised that button verdicts can be wrong until Chunk 2.

---

## 5. GPT on `not_understood` (#6)

When voice evaluation yields `not_understood`, call the existing GPT fallback, set `gpt_used = true`, return `interpretation`. **This one line needs `gpt_fallback_service.py` (its signature) — see §9.** The structural split can be built and tested before this is wired; until then `not_understood` simply returns no interpretation. Clean seam.

---

## 6. Idempotency guards (reliability)

New surface = new double-call risks (double-tap, retried network). Guards:
- **commit:** if the interaction is already `completed`, do **not** re-complete; return its existing recap. (Check `status` first.)
- **advance:** before creating the next interaction, check whether an interaction with `interaction_number = current + 1` already exists for the cycle; if so, return it instead of inserting a duplicate. For the cycle-complete branch, guard against re-running `complete_cycle` if the cycle is already `completed`.
- **evaluate:** no guard needed — every call is a real attempt by design.

---

## 7. Scoring notes (no change to formulas)

- Voice `calculate_interaction_score` reads `current_interaction_score` for its gross score; that stays NULL until commit, so gross = 100 (same as today — the "previous score" branch is currently vestigial because failed attempts never wrote a score). No behavior change.
- Commit reads `similarity_score`, `matched_answer_id`, `answer_mode_used`, `tapped_at_seconds` from the **answer row** (all written at evaluate), plus `cycle_level` as `user_level`, then calls the existing mode-specific scorer. singleButton re-queries `brain_answer.timer_seconds` (as evaluate does).
- `#2` scoring formulas (multi-select set scoring, etc.) remain deferred — Chunk 1 does not touch them.

---

## 8. Deploy & test sequence

1. **Backend add (this chunk):** implement the three endpoints + three orchestrator functions, reusing existing services. `submit-answer` untouched.
2. **Deploy** to Render (safe — new endpoints unused by any client yet).
3. **Curl test** on one interaction via its `session_interaction_id` (use the test user UUID), reading the DB in TablePlus between calls:
   - `evaluate-answer` (voice) → assert: answer row created, `attempts_count` incremented, interaction still `active`, verdict returned.
   - `commit-answer` → assert: interaction `completed`, `interaction_score` written, `final_answer_id` set, `completed_interactions` bumped, **no** next interaction created yet.
   - `advance-interaction` → assert: next interaction created (mid-cycle) / next cycle opened (after #7) / session completed (after cycle 3); payload correct.
   - Re-call each once more → assert guards hold (no duplicate completion/advance).
4. **Client switch + two-panel UI** = later chunks. Not in Chunk 1.

---

## 9. Remaining before Claude Code instructions

1. **Read `gpt_fallback_service.py`** — needed only for the §5 GPT line; everything else can be written now. (Dump command below.)
2. **Optional confirm:** a one-line grep that no live caller other than the adaptive client depends on `submit-answer` completing — reassurance only, since the additive approach makes it moot.

```
Read-only. Do not modify any code. Print the full contents of:
  ~/Desktop/tuje-analyze-api/gpt_fallback_service.py
```

---

## 10. Scope boundary

Chunk 1 is the backend spine only: three additive endpoints, no `submit-answer` change, no client change, no scoring-formula change, no button-correctness change (Chunk 2), no UI (Chunk 3). Validate this spec → read `gpt_fallback_service.py` → then Claude Code instructions for the backend, curl-tested before any Swift.
