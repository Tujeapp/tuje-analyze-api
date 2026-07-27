# TuJe — Chunk 1 Progress Log (client phase + diagnostic tool)

**Status: backend split DONE & verified (curl). Client A1+A2 built. Diagnostic picker built & proves the analysis pipeline is healthy. One thing still unverified: A2's evaluate→commit→advance through a LIVE adaptive session in-app.**

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

1. **Per-request `asyncpg.create_pool` on every endpoint (biggest win).** Split tripled it per interaction. Fix: one app-lifetime pool via FastAPI `lifespan`, injected everywhere. Pull forward — improves every request. Diagnostic endpoint folds in.
2. **commit→advance failure window** on flaky mobile networks: commit lands, advance drops → client stalls. Idempotency makes retry safe → add client retry on advance failure. Build into Chunk 3 Continue.
3. **`start-session` runs notion-decay/streak/boredom synchronously** on the user's wait → move persistence to BackgroundTask. Chunk 5.
4. **`HomeView` launch handoff** was a fragile 2-signal `.onChange`; picker redirect simplified the path. Minor.

---

## Chunk map (unchanged)
1. ✅ Backend split (done). Client A1+A2 (built; live-session test pending).
2. Button correctness + multi-select (answer_type-based; replaces linkage check).
3. Two-panel feedback UI + verdict tiers + commit/advance retry.
4. Rescue + hint plumbing.
5. Cleanups incl. **connection-pool lifespan fix (pull forward)**, submit-answer retirement, jsonb-serialize-in-service, etc.

## Resume here
Bank/commit client work. Author minimal voice-answer interaction set in Airtable → run a real adaptive session → verify A2 (compare spoken-correct score vs diagnostic 100). If 0, fix session→brain id resolution in `_evaluate_voice`.
