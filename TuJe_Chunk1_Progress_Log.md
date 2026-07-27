# TuJe — Chunk 1 Progress Log

**Chunk 1: decouple evaluate / commit / advance (backend).**
**Status: backend DONE and verified on the mid-cycle happy path + idempotency. Deployed to Render, committed.**

---

## What shipped

Additive only — three new endpoints on `session_router` (`/api/session`), one new file, no existing code paths changed. `submit-answer` + legacy flows untouched.

- **New file:** `answer_split_orchestrator.py` — `evaluate_user_answer`, `commit_answer`, `advance_after_interaction` (+ helpers), reusing existing services (`answer_service`, `interaction_service`, `scoring_service`, `cycle_manager`, `session_service`, `SessionContext`).
- **`routers/session_router.py`:** added request/response models + three endpoints:
  - `POST /api/session/evaluate-answer` → verdict + similarity, **no** completion/advance.
  - `POST /api/session/commit-answer` → completes the interaction, **no** advance.
  - `POST /api/session/advance-interaction` → next interaction / next cycle / session complete. Takes `interaction_id` **and `user_id`** (user column on `session` not assumed).

## Design decisions locked

- **Option 1:** commit at Panel-1 confirm, advance at Panel-2 Continue → 3 endpoints.
- Backend returns an explicit `verdict`. Voice tiers: `perfect` / `good` / `wrong` / `not_understood`.
- GPT fallback fires **only** on `not_understood` (voice). Wrapped so GPT failure ⇒ no interpretation, never breaks evaluate.
- Additive approach (new endpoints, legacy `submit-answer` intact) to avoid the Render auto-deploy window.

## Fixes made during testing (all isolated to `answer_split_orchestrator.py`)

1. Voice adjuster call: pass a typed `TranscriptionAdjustRequest(...)`, not a dict; read `list_of_notion_matches` (not `list_of_notions`).
2. jsonb serialization before `update_answer_with_adjustment`: `json.dumps([v.dict() for v in ...])` for vocab/entities, `json.dumps(...)` for notion strings — matches the routers' working convention. (`import json` added.)
3. `similarity = matching_result.get("similarity_score") or 0` — coerce `None` (key-present-but-null) to 0, which correctly routes a no-match to `not_understood`.

## Verified (curl + TablePlus, interaction `INT202606250709506455`)

- evaluate → interaction stays `active`, attempt incremented, score/final NULL; no-match ⇒ `verdict: not_understood`, `gpt_used: true`.
- commit → interaction `completed`, score + `final_answer_id` set, **no** next interaction created.
- advance → creates next interaction #2 (`active`), `next_interaction_id` matches the new row.
- idempotency → re-advance returns the **same** #2 (no #3); re-commit returns existing recap.

## Not yet exercised (no blockers)

- **Cycle-end / session-end advance branches** (`next_cycle`, `session_summary`, `already_advanced: true`) — only fire at interaction #7 / cycle 3. Will hit naturally during full-session client integration, or force later.
- Placeholder verdict thresholds (95 / 80 / 50) still in place — one-line edit at the top of `answer_split_orchestrator.py` when real cutoffs are decided.
- Button / singleButton verdicts use the **existing linkage check** (known bug, deliberately deferred to Chunk 2).

## Backlog noted

- Shared `update_answer_with_adjustment` casts `::jsonb` but never serializes internally — latent footgun for any caller that forgets to pre-serialize. Cleaner fix (serialize inside the service, callers pass raw lists) belongs in **Chunk 5 cleanup** (shared-service change touching legacy).

---

## Next session — resume here

**Chunk 1 client switch + Chunk 3 two-panel UI (they pair).** Point the adaptive flow at evaluate → commit → advance:
- Voice answer → `evaluate-answer` → **Panel 1** (verdict-driven buttons: perfect = move on; good = keep/retry; wrong & not_understood = retry/move-on).
- Confirm → `commit-answer` → **Panel 2** (locked recap + Continue).
- Continue → `advance-interaction` → load next.

Before writing client instructions, will need the current `APIService` methods (`submitAnswer` etc.) and confirmation of how the adaptive flow should map the four verdicts to Panel 1 buttons. Full-session run is where the cycle-end/session-end advance branches finally get exercised.
