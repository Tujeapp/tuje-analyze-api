# TuJe — Interaction & Answering System

**Type:** Current-state + work specification (discovery consolidation)
**Status:** Discovery complete. Decisions locked (§6). Build backbone selected: **Chunk 1 — decouple evaluate / commit / advance.** No Claude Code instructions written yet (call-boundary still to finalize in Chunk 1's own spec).
**Scope:** A single interaction end-to-end — fetch, display, the three answer modes, submission, scoring, server-side advance, and the feedback/rescue surface. Session/cycle orchestration is described only where it touches an interaction.
**Source of truth:** This doc was written against live files read during discovery (client + backend), not project-knowledge copies. Where a claim needs confirmation against live content/DB, it is tagged **[verify]**.

**Decision log (this revision):**
- **#1 confirmed live (not latent):** content already supports perfect / good / false-good / wrong answer types, so distractors *are* linked rows. Severity → Critical, confirmed.
- **#2 scoring formula deferred** behind a clean seam (buttons + singleButton). Voice scoring keeps its existing design (verify, don't redesign).
- **#3 superseded** by a two-panel, verdict-driven feedback model (see §5a).
- **#6 scoped:** GPT interpretation fires on exactly one voice verdict — *Not understood* — and nowhere else.
- **#10:** in-session picker removed entirely (picker now lives on HomeView).
- **Backbone change:** **evaluate / commit / advance are split** (§5a). `submit-answer` stops completing/advancing. Resequenced so this backend work is **Chunk 1**, before the correctness fix.

---

## 1. Purpose

Before we design any change to the answering system, this document fixes a shared, accurate picture of:

1. **What we have already** — the confirmed architecture, both client and backend.
2. **What needs to be done** — a register of confirmed defects and gaps.
3. **How** — a proposed approach and the open decisions for each item.

It deliberately stops short of committing to a build. The intent is that we pick one item from §4, lock its open decisions in §6, and only then write Claude Code instructions.

---

## 2. What we have already (confirmed architecture)

### 2.1 Three session flows share one interaction surface

`SessionView` / `SessionViewModel` render the same interaction UI for three different orchestration flows. They differ mainly in *how an interaction is created* and *how the app advances* after an answer.

| Flow | Setup | Advance mechanism |
|---|---|---|
| **Regular** | `startSession` → `startCycle` → `fetchFirstInteraction` → `fetchInteraction` (creates a `session_interaction` via `startInteraction`) | Separate `completeInteraction` call on Continue |
| **Adaptive** (live focus) | Mood screen pre-creates session + cycle + first interaction; `startAdaptiveSession` → `loadInteractionForPlayback` | **No** separate complete call — `/submit-answer` already advanced server-side; client reads stored `next*` / `cycle*` / `session*` fields |
| **Initial** (onboarding) | `startInitialSession` via `InitialSessionService` | Own `completeInitialInteractionAndAdvance` against dedicated endpoints |

The **adaptive flow is the one to design against**. The regular flow still carries hardcoded placeholders (`INT202505090900`, `SUBT202505100899`) and a `selection_method: random` log line; treat it as a legacy/test harness, not the target.

### 2.2 Single-interaction lifecycle (adaptive)

1. **Fetch** — `getInteraction(id)` → `InteractionResponse` (video URL, `answer_mode`, `selection_mode`, transcriptions). `AnswerMode.from(answerMode:)` selects the mode. Mic is enabled only for voice.
2. **Buttons fetch** (multipleButtons only) — `answers-by-interaction` with `user_level = Int(rescueLevel*500)`, `rescue_triggered`, `session_interaction_id`. Returns selected answers + `selection_mode` + `correct_count`.
3. **Play** — fullscreen video; replays counted; first-play-end starts interaction timing.
4. **Answer** — one of three modes (§2.3) posts to `/api/session/submit-answer` keyed on `session_interaction_id`.
5. **Score + advance (server)** — orchestrator scores, marks final, completes the interaction, checks cycle completion, and auto-advances: next interaction from the persisted `candidate_pool_ids`, or open next cycle, or complete session after cycle 3. All returned in `SubmitAnswerResponse`.
6. **Feedback** — `FeedbackSheetView` shows correct/incorrect + a "mistakes" count; **Continue** → `onFeedbackContinue()` → `advanceAdaptive()` consumes the stored `next*` fields.

Swift `SubmitAnswerResponse` and the backend Pydantic model match field-for-field — the contract is clean.

### 2.3 The three answer modes and their submit pipelines

The orchestrator (`process_user_answer_complete`) routes by `answer_mode_used`:

- **voice** — adjust transcript (entity normalization) → rapidfuzz match (threshold 80) → complete, else `status:"retry"`.
- **multipleButtons** — membership/EXISTS check that the selected `answer_id` is linked to the interaction → 100.0 / 0.0. **(See Issue #1 — this checks linkage, not correctness.)**
- **singleButton** — compares tap time to the first `brain_answer.timer_seconds` (±2s tolerance), similarity scaled by delta.

All three converge on `_complete_interaction`, which applies the mode-specific scoring path, completes the interaction, and performs the server-side advance.

### 2.4 The Answer Selection Engine (buttons)

`answer_selection_service.select_answers` is more capable than a flat fetch:

- Reads `selection_mode` from `brain_interaction` and `cycle_level_direction` from the live cycle.
- Picks difficulty: rescue → easy; direction +1 → hard; −1 → easy; else medium.
- Fills a typed configuration (`SINGLE_SELECT_CONFIGS` / `MULTIPLE_SELECT_CONFIGS`) from `brain_answer` rows that are `live` **and `display_ready = TRUE`** and carry a `bia.answer_type` of perfect / good / false good / wrong, ordered by closeness to user level; shuffles; returns `correct_count = count(perfect + good)`.
- Falls back to ≤4 display-ready answers if no configuration can be satisfied.

So `display_ready` **is** enforced — server-side, here — and the engine already knows the *correct set* semantics (perfect/good). The submit path does not yet use those semantics. This gap is the spine of Issues #1 and #2.

### 2.5 Rescue + silent state machine

`FrustrationTracker` (seeded by `rescue_level`, default 0.50, from `user_behavior`):

- `recordFailedAttempt()` → +0.25 frustration, increments per-interaction fail count.
- Layer 2 threshold: `rescue_level < 0.5` needs **3** fails; otherwise **1**.
- `rescue_level ≥ 0.8` jumps straight to Layer 3 (`buttonsAboveMic`); otherwise Layer 2 is `switchButton`.
- `recordSuccess()` / `reset()` clear state.
- `recordTimerExpired()` (+0.20) and `recordHelpTapped()` (+0.40) exist but are **never called** (no help button; timer expiry doesn't notify the tracker).

**Silent** is separate from rescue: user opts out of speaking (`declareSilentSession` / persistent `always_silent` via `/update-always-silent`), forcing multipleButtons.

### 2.6 Component / file map (anchors for implementation)

**Client (`~/Desktop/TuJe`):**
- `Views/SessionView.swift` — all controls, overlays, the test picker.
- `ViewModels/SessionViewModel.swift` — the three flows, submit methods, rescue wiring.
- `MultipleButtonsAnswerView.swift` — answer buttons + multi-select confirm (**bug site**).
- `FeedbackSheetView.swift` — feedback + the only live advance trigger.
- `FrustrationTracker.swift`, `RescueUIState.swift`, `AnswerMode.swift`, `Models/SessionModels.swift` (`MicState`), `Models/APIModels.swift` (all wire models).

**Backend (`~/Desktop/tuje-analyze-api`):**
- `main.py` — router mounting (`session_router` @ `/api/session`; `data_access_router` no prefix).
- `routers/session_router.py` — `/submit-answer` (L496) + request/response models.
- `answer_processing_orchestrator.py` — `process_user_answer_complete`, the three pipelines, `_complete_interaction` (advance logic).
- `answer_selection_service.py` — the selection engine.
- `data_access_routes.py` — `answers-by-interaction` (L1274).
- `session_management/*` — scoring, answer, interaction, cycle, bonus_malus services.
- `cycle_manager/*` — `advance_to_next_interaction`, `start_new_cycle`, cycle completion/calculations.
- `matching_answer_service.py` (rapidfuzz), `adjustement_adjuster.py`, `gpt_fallback_service.py`.

Legacy/dead for the app: `match_routes.py`, `bubble_integration_router.py`, `mistakes_routes.py` (Bubble-era; not in the live submit path).

---

## 3. How we work (process guardrails for any build)

- Discovery before edits; read live files, never project-knowledge copies.
- One concept at a time; verify each before the next.
- Claude.ai writes architecture + verbatim Claude Code instructions; Claude Code applies edits; Rémi runs SQL in TablePlus.
- Anything touching the **submit contract or scoring** is a backend + client + model change — spec the contract first, change both sides together, test via the picker on a single interaction.
- Reliability and cost are priorities: prefer fixes that remove duplicate/racing network calls over fixes that add calls.

---

## 4. Issue register (what needs to be done)

| # | Issue | Severity | Surface |
|---|---|---|---|
| 0 | **Backbone:** split evaluate / commit / advance (see §5a) | **Critical (backbone)** | Backend + Client + contract |
| 1 | Button correctness = *linkage*, not `answer_type` — accepts wrong answers | **Critical (confirmed)** | Backend |
| 2 | Multi-select fires N sequential submits; first one completes the interaction | **Critical** | Client + Backend + contract |
| 3 | Feedback-sheet soft trap | *Superseded by §5a* | — |
| 4 | Bottom nav chevrons are dead (`action:{}`); no "previous" capability | Medium | Client |
| 5 | Rescue ladder under-wired (Layer 2 vs 3 not honored; timer/help signals unfired; no help button) | Medium | Client |
| 6 | GPT interpretation — keep, scoped to *Not understood* verdict | *Decided* | Client + contract |
| 7 | `mistakeCount` is a cumulative session counter mislabeled "mistakes"; per-answer mistakes not wired | Low–Med | Client (+ backend) |
| 8 | Hint UI absent → `record-hint` malus (−5/hint) input unfed | Medium | Client |
| 9 | Like/dislike UI absent → bonus/malus input unfed | Low–Med | Client (+ backend) |
| 10 | In-session picker — remove (picker now on HomeView) | *Decided* | Client |
| 11 | `selection_mode` has two sources (`InteractionResponse` vs `answers-by-interaction`) | Low | Contract |
| 12 | `singleButton` matches first timed answer (`LIMIT 1`) → content-discipline dependency | Low | Backend + content |
| 13 | `lastMatchFound` conflates matched/complete; regular-flow log uses `Int(similarity)` not `interactionScore` | Low | Client |
| 14 | "for Bubble" comment drift throughout backend | Trivial | Backend cleanup |

---

## 5a. Backbone redesign — split evaluate / commit / advance (Chunk 1)

This is the new spine. Everything else hangs off it, so it is built first.

### The problem being fixed
Today, **submitting an answer and advancing to the next interaction are fused.** On a good voice answer, `_complete_interaction` runs at submit time and, in the same call, commits the advance (moves the `candidate_pool_ids` pointer / opens the next cycle / completes the session). The next interaction is set before the user signals readiness, and a good answer can never be retried-to-improve. This fusion was a deliberate optimization (R30 "Option α", saving a round trip) but it deviates from the session spec, which always said *"End Interaction — trigger after a user presses continue."*

### The three steps, separated
1. **Evaluate** — judge the attempt, return a **verdict tier** + score (+ optional GPT interpretation for one voice tier). **Does not** complete or advance. Retry simply calls evaluate again.
2. **Commit** — mark the chosen attempt final, complete the interaction. Triggered by the user confirming on Panel 1. Returns the locked-interaction recap for Panel 2.
3. **Advance** — move the pool pointer / open next cycle / complete session. Triggered by Continue on Panel 2.

**Open (Chunk-1 spec):** how many calls these become — three endpoints, two (fold advance into commit), or one endpoint with a mode flag. UX is identical either way; this is a cost-vs-clarity call. Cost priority leans toward folding advance into commit (two calls total: evaluate, then commit+advance).

### Two-panel feedback model (voice)
- **Panel 1 — answer feedback** (looks like today's sheet). Buttons depend on the verdict tier (table below).
- **Panel 2 — locked interaction-answer feedback.** Appears after the user confirms on Panel 1. Quick recap of the now-locked interaction; single **Continue → next interaction** at the bottom (this is the advance trigger).

### Voice verdict tiers

| Verdict | Meaning | Panel 1 buttons | GPT fallback |
|---|---|---|---|
| **Perfect** | Top match, nothing to improve | *Move on* only | No |
| **Good** | Accepted, but improvable | *Keep it* / *Retry* | No |
| **Wrong** | Recognized, but with mistakes | *Retry* (strong) / *Move on* (allowed) | No |
| **Not understood** | Speech couldn't be interpreted | *Retry* (strong) / *Move on* (allowed) | **Yes** — interpretation shown |

Retry never advances; it loops back to evaluate. "Move on" / "Keep it" trigger commit → Panel 2.

**Open (Chunk-1/3 spec):** is *Wrong* one tier or several, and are tier cutoffs derived from the similarity score (thresholds supplied later) or returned as an explicit `verdict` field from the backend? Leaning explicit `verdict` field — keeps thresholds server-side and the client dumb.

### Buttons / singleButton
No "retry to improve" notion — a correct button is correct. They likely skip Panel 1's keep/retry choice: submit (correct) → Panel 2; submit (wrong) → retry prompt. Exact panel behaviour defined alongside the #2 scoring reflection. **The evaluate/commit/advance plumbing is shared across all modes** — do not build a voice-only spine.

### Main risk
Chunk 1 changes the orchestrator's completion/advance path that **all three flows** (adaptive, regular, initial) depend on — adaptive most of all, since it was built around the fused behaviour. Once advance is no longer fused into submit, each flow must still advance correctly. Verify on a single interaction via the HomeView picker before trusting it in a full session.

---

## 5. Issue detail (root cause + proposed approach)

### #1 — Button correctness checks linkage, not correctness — **Critical (confirmed live)**
**Where:** `_process_multiple_buttons_answer` (orchestrator).
**Root cause:** `is_correct` comes from an EXISTS check that the selected `answer_id` is attached to the interaction. But the selection engine attaches *all* answer types (perfect/good/false good/wrong) as linked rows. So any displayed button is "linked," and the check can't tell a distractor from a right answer.
**Confirmed:** content already supports setting answers as perfect / good / false-good / wrong, so distractors are linked `brain_interaction_answer` rows today. This is a live bug affecting single-select too, not latent.
**Consequence:** A wrong/false-good button currently completes the interaction as correct.
**Proposed how:** Score by `answer_type`, not linkage. On commit (post-split), fetch the `answer_type` of the selected `answer_id` from `brain_interaction_answer`; treat `perfect`/`good` as correct (mirroring the engine's `correct_count`). Unifies single- and multi-select semantics.
**Open decisions:** none for single-select; multi-select scoring decided in #2.

### #2 — Multi-select submit is broken end-to-end — **Critical**
**Where:** `MultipleButtonsAnswerView` confirm loop (client) + `_process_multiple_buttons_answer` (backend).
**Root cause:** Client loops `for answerId in selectedAnswerIds { await submitButtonAnswer(...) }` — one `/submit-answer` per id. Backend scores one id at a time, and (per #1) the first one completes/advances the interaction; later submits race against a finished/next interaction. There is no representation of "the correct *set*" anywhere.
**Consequence:** Over-counted attempts, a race on `next*`/state, and no actual set evaluation.
**Proposed how (contract change):**
- New request field `selected_answer_ids: [String]` (keep `selected_answer_id` for back-compat or migrate fully).
- Backend evaluates the selected set against the correct set (perfect/good) using `answer_type`; returns one result, one completion, one advance.
- Client sends one submit with all selected ids; remove the loop.
**Open decisions:**
- **Scoring rule:** all-or-nothing (set must exactly equal correct set) vs partial credit (score ∝ overlap). Affects `interaction_score` and feedback copy.
- **Wrong-pick penalty:** does selecting a distractor zero the answer, or just reduce partial credit?
- **`correct_count` exposure:** keep hidden (user must infer how many), or surface ("select 2")? Currently only gates the confirm button.

### #3 — Feedback-sheet dismiss is a soft trap — **Superseded by §5a**
**Original problem:** backdrop tap / drag-down called `dismiss()` without advancing → on a correct answer the user could get stuck (interaction complete server-side, no working forward control).
**Resolution:** the two-panel model in §5a removes the trap structurally. Advance no longer happens at submit, so dismissing Panel 1 just leaves the user on the (not-yet-committed) interaction; the only advance path is Continue on Panel 2. No separate dismiss policy needed. Tracked here for history; folded into Chunk 1/3.

### #4 — Dead navigation chevrons — **Medium**
**Where:** `SessionView.navigationButtons` — both chevrons have `action: {}`. No "previous interaction" exists in the view model.
**Proposed how:** Decide whether the bottom nav is a real control or should be removed. If real: wire Continue to the same path as the feedback Continue (and gate on `continueEnabled`); "Previous" needs a product decision (likely out of scope — server-authoritative advance has no natural "back").
**Open decision:** keep vs remove; is "previous" ever a thing in an adaptive, server-driven session?

### #5 — Rescue ladder under-wired — **Medium**
**Where:** `SessionViewModel` only acts on `rescueNeeded` by calling `switchToMultipleButtons`; it doesn't differentiate `switchButton` (Layer 2) from `buttonsAboveMic` (Layer 3). `recordTimerExpired` / `recordHelpTapped` are never invoked.
**Proposed how:** Honor `rescueUIState` as the source of truth for presentation (offer the switch at Layer 2; show buttons-above-mic at Layer 3) instead of force-swapping mode. Fire `recordTimerExpired()` when the 12s timer hits 0. (Help signal depends on #8.)
**Open decision:** desired UX per layer; whether timer-expiry should count toward rescue at all.

### #6 — GPT interpretation — **Decided: keep, scoped to one verdict**
**Where:** `FeedbackSheetView` renders `gptInterpretation`, but the voice path never sets it.
**Decision:** GPT interpretation stays in the product but fires on exactly one voice verdict — **Not understood** (low/no match where the system can't interpret the speech). Perfect / Good / Wrong and the button modes never call GPT.
**Proposed how:** in the voice evaluate path, when the verdict is *Not understood*, call the existing GPT fallback (cost-gated) and return an `interpretation` field; Panel 1 shows it for that tier only.
**Note:** matches cost priority — GPT only when matching genuinely failed.

### #7 — Misleading mistake count — **Low–Med**
**Where:** `mistakeCount += 1` per failed voice attempt, never reset per interaction; label says "mistakes." Per-answer mistake details (`list_of_mistakes`, `mistakes_routes`) not wired.
**Proposed how:** Either reset per interaction and relabel "attempts," or wire real per-answer mistakes from the adjustment/match result.
**Open decision:** which definition of "mistake" the UI should show.

### #8 — No hint UI — **Medium**
**Where:** Backend `record-hint` exists (−5/hint malus); no hint button in the session UI, so the malus input is unfed and the bonus-malus spec is starved.
**Proposed how:** Add a hint control that calls `record-hint`, increments tiered hints, and feeds `recordHelpTapped()` into the tracker.
**Open decision:** hint content model (tiered depth per the spec), placement, and when it activates.

### #9 — No like/dislike UI — **Low–Med**
**Where:** Bonus-malus spec uses like/dislike (±); no UI or call exists.
**Proposed how:** Add a like/dislike control on the interaction or feedback surface; define the endpoint/field that records it into bonus-malus.
**Open decision:** placement (during interaction vs in feedback), and the backend recording path.

### #10 — In-session picker — **Decided: remove**
**Where:** top-left button in `SessionView`, shown whenever `!isInitialSession`, calling the regular-flow `fetchInteraction(id:)`.
**Decision:** remove the in-session picker entirely. The picker now lives on HomeView, so no flow-awareness is needed — just delete the control and its `showInteractionPicker` sheet from the interaction view.
**Scope:** client-only deletion; trivial.

### #11 — Dual `selection_mode` source — **Low**
**Where:** `InteractionResponse.selectionMode` and `answers-by-interaction.selection_mode` both exist; client uses the latter.
**Proposed how:** Pick one authoritative source (the engine's, since it also returns `correct_count`) and stop populating/consuming the other.

### #12 — `singleButton` first-timer dependency — **Low**
**Where:** Orchestrator selects the first `brain_answer` with non-null `timer_seconds` (`LIMIT 1`).
**Proposed how:** Enforce a content invariant (exactly one timed answer per singleButton interaction) or make the selection explicit. Mostly a content-discipline guardrail.

### #13 — Naming/logging smells — **Low**
`lastMatchFound = result.interactionComplete` conflates "matched" with "interaction done"; the regular-flow log records `Int(lastSimilarityScore)` instead of `result.interactionScore`. Rename/relabel; low risk.

### #14 — "for Bubble" comment drift — **Trivial**
Scrub docstrings that claim the client is Bubble; the client is SwiftUI. Cleanup only.

---

## 6. Open decisions

**Resolved this revision:** #1 (confirmed live), #3 (superseded), #6 (scoped to *Not understood*), #10 (remove), verdict tiers (4: Perfect/Good/Wrong/Not understood), resequencing (backend split first).

**Still open (do not block Chunk 1 plumbing):**
1. **Chunk-1 call boundary:** 3 endpoints, or 2 (fold advance into commit), or 1 with a mode flag. Leaning 2.
2. **Verdict delivery:** explicit `verdict` field from backend vs client-derived from similarity thresholds. Leaning explicit field; *Wrong* one tier or several TBD.
3. **#2 scoring formulas:** multi-select (all-or-nothing vs partial credit, wrong-pick penalty, surface `correct_count`?) and singleButton. Deferred behind a seam — Rémi reflecting.
4. **Voice scoring:** keep existing design; verify, don't redesign.

---

## 7. Sequencing (resequenced — backend backbone first)

Each chunk is one concept, testable on a single interaction via the HomeView picker.

1. **Chunk 1 — Decouple evaluate / commit / advance (§5a).** Backend-first backbone. `submit-answer` stops completing/advancing; commit + advance become separate steps. Highest risk (touches all three flows' advance path) and the foundation for everything else. Lock the §6.1 call-boundary in this chunk's own spec.
2. **Chunk 2 — Button correctness + multi-select (#1 + #2).** `answer_type`-based correctness on the new commit step; set-based multi-select submit. Scoring formula stubbed behind a seam (§6.3).
3. **Chunk 3 — Two-panel feedback UI + verdict tiers.** Panel 1 (verdict-driven buttons) → Panel 2 (locked recap + Continue). Absorbs #3 and #4; wires the four tiers and GPT-on-*Not understood* (#6).
4. **Chunk 4 — Rescue + hint plumbing (#5 + #8).** Honor `rescueUIState`; fire `recordTimerExpired()`; add hint control → `record-hint` + `recordHelpTapped()`. Minimal/placeholder UI; aesthetics deferred to a second phase.
5. **Chunk 5 — Scoring inputs + cleanups (#7, #9, #10 removal, #11, #12, #13, #14).** Like/dislike, honest mistake semantics, picker removal, single `selection_mode` source, singleButton invariant, log/name fixes, comment scrub.

---

## 8. What this document is not

This is a state-and-decisions spec, not an implementation spec. The next step is to write **Chunk 1's own implementation spec** — locking the call boundary (§6.1) and the `verdict` contract (§6.2) — and only then produce Claude Code instructions for Chunk 1 alone. No file edits until that exists.
