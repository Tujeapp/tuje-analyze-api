# TuJe — Regular Session System — Build Specification

**Status:** Phase 1 in progress. Chunks 0, 1a, 1b, 1c, 3 complete. New backend endpoint added: GET /api/session-adaptive/mood-recommendation (returns recommended_mood + available_moods from brain_session_mood; recommendation is placeholder "Effective" pending full algorithm). iOS work for the central-button regular-session entry is the next chunk, scoped: build a new mood-selection screen, rewire central button to open it, relocate picker to a temporary HomeView button, and add an adaptive-mode parameter to SessionView/SessionViewModel so it plays through interactions using the adaptive endpoint responses. Cycle-boundary and session-end UI explicitly deferred to a later iOS conversation. After iOS work: chunk 1d (seen-ratio override §5).
**Last updated:** Conversation of June 2026.
**Scope:** The core plumbing of the everyday adaptive learning session a user gets after onboarding — session setup, the adaptive interaction loop, cycle open/close, and session close. **Phase 1 is story-only.** Out of scope for now: session UI/visual design, extra buttons, nice-to-haves.

> This is a living document. It is updated via a precise Claude Code edit as each chunk completes, so the plan, milestones, and decision log stay captured in one place. Each chunk **opens with its own read-only discovery** (read the relevant code in full before designing against it) — the summaries here are from the initial discovery pass and are not a substitute for reading the actual function bodies at build time.

---

## 1. What a regular session is

- **Entry point:** the HomeView bottom-bar central button, only after onboarding is complete.
- **Structure:** 1 session = 3 cycles; 1 cycle = 7 interactions.
- **Adaptive, not a fixed playlist:** the next interaction is chosen from the user's performance as they go (see Decision 2 — fixed candidate pool, dynamic next pick).
- **Distinct from the initial/onboarding session,** which is template-driven and already built.

### Lifecycle ↔ logic-doc mapping

The six lifecycle phases map onto the seven numbered sections of `Details_of_logic_of_session`:

| Lifecycle phase | Logic-doc section |
|---|---|
| Session setup | §1 (set new session) + §2 first-cycle branch + §3 first interaction |
| Next-interaction calc (adaptive step) | §3 "set next interaction", fed by §4 (interaction score) + §5 (end interaction) |
| Cycle close | §6 (end cycle) |
| Cycle open (cycles 2–3) | §2 not-first-cycle branch + §3 first interaction |
| Session close | §7 (end session) |
| Return to HomeView | frontend |

---

## 2. Current state of the codebase (from discovery)

### The adaptive engine already exists — but is dead code

The full server-authoritative adaptive pipeline is written and wired together, sitting behind an **unmounted router**:

- `session_management_router.py` — adaptive `POST /start-session`, `POST /start-cycle`, `GET /session/{id}`.
- `user_state.py` — `detect_user_state()` (brand_new / early / active / returning).
- `session_init.py` — four initializers (brand_new, early, returning, active).
- `session_calculations.py` — top mood, session boredom, mood recommendation, modulo, seen intents/subtopics.
- `cycle_manager/` — `cycle_creation` (`start_new_cycle`, `advance_to_next_interaction`), `cycle_calculations` (`calculate_cycle_level/boredom/goal`, `interaction_user_level`), `interaction_selection` (`select_cycle_interactions`, `select_first_interaction_story`, `select_next_interaction`), `cycle_completion` (`complete_cycle`, `update_cycle_level_direction`).
- `interaction_search.py` — `find_best_subtopic_with_fallback`, `search_interactions` (filters to interactions whose linked notions the user has mastered).

### Why it's dead

In `main.py`, line 21 (`from routers.session_router import router as session_router`) rebinds the same name used on line 20 for the adaptive router. Both mounts at lines 84–85 therefore point at the **CRUD router** (`routers/session_router.py`); line 85 is a redundant duplicate of line 84. The adaptive `start-session` / `start-cycle` are never mounted.

### What is actually live at `/api/session`

The **CRUD router** (`routers/session_router.py`) — a thin-server design whose `start-cycle` takes `subtopic_id` and `cycle_level` as **client-supplied inputs** and does no adaptive calculation server-side. This is the opposite of what we want (Decision 1). Its genuinely useful non-adaptive endpoints — `start-interaction`, `submit-answer`, `record-hint`, the `GET` reads — we **keep and reuse**. Also live: `complete_interaction_router.py` at `/api/session` (`POST /complete-interaction`) with its own **legacy random next-interaction logic** — a collision risk (see Risks).

### Scoring already matches the logic doc

`session_management/scoring_service.py` `calculate_interaction_score()` implements §4A (gross score = 100 first attempt else prior; coefficient `((answer_optimum/interaction_optimum) + (answer_optimum/cycle_level)) / 2`), plus button/timing variants and `bonus_malus_service`. Phase 1 **consumes** this; it is not rebuilt.

### Schema (live, confirmed) — and the gaps

Present and rich: `session` has `session_mood`, `session_level`, `session_boredom`, `streak7/30`, `modulo`, `top_session_mood`, `mood_recommendation`; `session_cycle` has `cycle_goal`, `cycle_level`, `cycle_boredom`, plus `template_interaction_ids VARCHAR[]` (initial-session pattern). Gaps that phase 1 must close:

- `session_cycle` — no `cycle_level_direction`, no `cycle_rate`, no persisted **candidate pool**.
- `session_interaction` — no `interaction_user_level`, no `interaction_boredom`.
- **Notion data model** — `brain_notion` NOT FOUND; `session_notion` has only `notion_rate` (no passive/active rate, weightiness, introduction date). This blocks the notion **goal** (phase 2) *and* the notion-rate **update** calcs in §1G and §5A. See Risk R3.

---

## 3. Architecture decisions (see full Decision Log, §6)

1. **Server-authoritative.** All session state in Postgres; iOS renders. (Confirmed by the build; matches intent.)
2. **Fixed candidate pool, dynamic next pick (Option B).** One heavy search at cycle open; persist the pool; pick the next interaction from it using freshly-updated state. No mid-cycle re-search.
3. **Phase 1 is story-only.** Cycle goal hardcoded to `'story'`; goal selection (§2B), list-of-notions sort (§1 H–J), and intents-seen are skipped until later phases.
4. **Wiring: Option 1 (surgical).** Mount the adaptive router at a distinct prefix; leave CRUD where it is. Promote to canonical `/api/session` later (chunk 6), only once the lifecycle is proven.

---

## 4. Phase 1 build plan — chunk by chunk

Each chunk is independently testable and ordered by dependency. **Schema changes are deliberately spread across chunks 2–4, not front-loaded** — each chunk adds only the columns it needs, run section-by-section in TablePlus. Every chunk begins by reading the relevant code in full (discovery), then builds, then tests before moving on.

### Chunk 0 — Make the adaptive flow reachable
- Rename the adaptive import (e.g. `adaptive_session_router`); mount at `/api/session-adaptive`. Remove the duplicate CRUD mount (line 85).
- Discovery within this chunk: confirm whether CRUD `submit-answer` / scoring assumes the CRUD `start-cycle` ran (sets `subtopic_id` / `cycle_level` a particular way). The answer may pull chunk 6 forward.
- **Test:** adaptive `POST /api/session-adaptive/start-session` returns 200 (was 404); CRUD endpoints unchanged.

### Chunk 1 — Session setup runs end-to-end (story-only) — *highest risk*
- First real execution of `detect_user_state` → `session_init` → §1 calculations (mood, streaks, session boredom, modulo, mood recommendation). Skip §1 H–J (notion sort) and intents-seen.
- Resolve Risk R3 here (notion-rate updates): confirm what `notion_management.py` does and whether it touches the missing fields; default is to **defer notion-rate writes to phase 2** (mastery filter still reads existing rates).
- **Test:** a real user with history hits `start-session`; inspect the `session` row — every computed field populated and sane.
- **Natural stopping point to reassess** before continuing.

### Chunk 2 — Cycle open, first cycle (story)
- `start_new_cycle` → `find_best_subtopic_with_fallback` → `calculate_cycle_level/boredom`; goal hardcoded `'story'`.
- **Schema:** persist the candidate pool. Proposed: `session_cycle.candidate_pool_ids VARCHAR[]` (parallels existing `template_interaction_ids`). This is the Option B persistence + the resumability fix in one.
- **Test:** `start-cycle` returns a first interaction; pool is in the DB; cycle-row fields correct.

### Chunk 3 — The interaction loop (the adaptive heart)
- `submit-answer` → score (existing) → complete interaction → **pick next from the persisted pool using fresh state** (`select_next_interaction`, combination sequencing).
- **Schema:** `session_interaction.interaction_user_level INTEGER`, `interaction_boredom NUMERIC`.
- Decide here how deep to take §5 end-interaction (speaking/comprehension/accuracy rates feed `interaction_user_level`); keep minimal for first pass if the inputs aren't all available.
- **Test:** answer 7 interactions; each next pick reflects the prior score; cycle flags complete at 7.

### Chunk 4 — Cycle close + auto-open next cycle
- §6: `cycle_rate`, cycle boredom average, `cycle_level_direction`; then auto-open cycles 2 and 3. Fixes the "orchestrator never opens the next cycle" gap.
- **Schema:** `session_cycle.cycle_level_direction VARCHAR`, `cycle_rate NUMERIC`.
- **Test:** completing cycle 1 closes it and opens cycle 2 with recalculated level/boredom.

### Chunk 5 — Session close + return to HomeView
- §7: session score, session level, session level direction; auto-fire after cycle 3. Fixes the "no session-level auto-completion" gap.
- **Test:** completing cycle 3 closes the session and returns the HomeView signal.

### Chunk 6 (late, optional) — Promote adaptive router to canonical `/api/session`
- Mount adaptive at `/api/session`; retire CRUD **lifecycle** endpoints (`create-session`, CRUD `start-cycle`, `complete-cycle`, `complete-session`) while **keeping** the reused non-adaptive ones. Removes the iOS prefix seam from Decision 4.
- Done only once the lifecycle is proven end-to-end.

---

## 5. Risks & open items

- **R1 — Cold code, first run (high).** The adaptive pipeline has never executed end-to-end. Chunk 1 is where failures will concentrate. Treat reaching the end of chunk 1 cleanly as the first reassessment gate.
- **R2 — Legacy completion collision (medium).** `complete_interaction_router.py` is live at `/api/session` with its own random next-interaction and 3-cycle completion logic. Chunks 3–5 must ensure iOS calls the adaptive completion path and the legacy one cannot interfere. Candidate for retirement in chunk 6.
- **R3 — Notion data-model gap (medium, scoping).** Missing `brain_notion` and `session_notion` fields block notion-rate updates in §1G and §5A, not just the notion goal. **Recommended default:** defer all notion-rate *writes* to phase 2 alongside the data model; phase 1 reads existing rates for the story mastery filter. Confirm in chunk 1.
- **R4 — Pool persistence schema choice.** Array column on `session_cycle` vs. a separate pool table. Recommended: array column (consistency with `template_interaction_ids`). Revisit only if the pool needs per-item metadata.
- **R5 — iOS prefix seam.** Until chunk 6, iOS calls `/api/session-adaptive/*` for lifecycle and `/api/session/*` for `submit-answer` etc. Document this for the frontend work.
- **R6 — user_id type mismatch (medium, latent).** `brain_user.id` is `uuid`; `session.user_id` (and likely session_cycle/session_interaction user_id columns) are `varchar`. UUIDs written as varchar aren't normalized, so casing differences (observed: same UUID stored both upper- and lower-case) can cause silent user-history join misses — a returning user could be mis-detected as brand_new. Audit and normalize before chunk 1c's history-dependent queries rely on user_id joins.
- **R7 — chunk 1 routing now load-bearing for crash-safety.** Per the Option A decision, the first regular session must route to the seed path. Because we write ONLY session_level at initial close (not session_nbr_cycle etc.), the initial session row still has NULL columns that the early/active calculators would crash on (None * 7 * 100). Fix 1 routing is therefore the sole protection against those crashes — chunk 1b testing must explicitly verify the calculators are never reached for an initial-only user.
- **R8 — Notion pipeline column mismatches (medium, latent for session 2+).** The G/H/I/J notion pipeline (`notion_management.py` lines 99, 116, 299, 430–432, 447, 451–452) references `notion_name`, `notion_level_from`, `notion_weightiness` — none of which exist on the live `brain_notion` table (correct names: `name_fr`/`name_en`, `level_from`, `weightiness`). The brand_new (is_new_user=True) branch short-circuits before reaching this code, so chunk 1b doesn't hit it. Will surface when a user starts their second regular session (is_new_user=False) and the pipeline runs. Same fix pattern as chunk 1b — column renames.
- **R9 — Cold-code-vs-live-schema drift (general, applies to remaining chunks).** Chunks 1a/1b surfaced ~10 separate code-vs-schema mismatches: missing columns (`created_at` on session), wrong column names in `brain_notion` reads, function signature mismatches, and multiple unhandled NOT NULL constraints (`session_type`, `expected_cycles`, etc.). The pattern: cold code was written against an imagined schema looser than what's deployed. Expect similar density in chunks 1c–5. Tactic established: when a function accumulates many small fixes (≥3), surgical rewrite using the live schema is faster than continued patching.
- **R10 — iOS central button currently triggers a subtopic/interaction picker panel, not a regular session.** Migration needed once chunk 1 is complete: central button should call adaptive `start-session`. The picker panel should be preserved (it's useful for content-specific testing) but relocated, e.g. to a developer/debug area. Constraint on chunk 6: if/when CRUD lifecycle endpoints are retired, verify the picker panel's CRUD endpoint calls (which already exist) still resolve, or migrate them too.
- **R15 — Decimal × float arithmetic drift (general).** Postgres `numeric` columns return as Python `Decimal` via asyncpg; multiplying by a Python `float` raises `TypeError`. Surfaced in chunk 3 at `cycle_calculations.py:150` (`cycle_boredom * coefficient`) — fixed with `float()` conversion at the use site. Latent risk anywhere code does arithmetic on a value pulled from a numeric column without converting at the read site. Future hardening: standardize on `float()` conversion at all `fetchrow`/`fetchval` reads of numeric columns, rather than at use sites.
- **R16 — Cycle-goal rotation is a placeholder for session_rank ≥ 2.** The current `calculate_cycle_goal` falls through to a hardcoded `{1: story, 2: notion, 3: story, ...}` rotation for sessions beyond the first. Per ramp-up doc §6, the real algorithm involves cycle-boredom bands, the last cycle's goal, and three goal-usage scores over a 7-day window — none of which are implemented yet. Affects session_rank ≥ 2 only; safe for the current scope.
- **R17 — Half B's cycle-completion + next-cycle-open is not atomic.**
- **R18 — Casing inconsistency for session_mood strings.** brain_session_mood.name stores capitalized strings ("Effective", "Cultural", etc.). helpers.py:get_mood_types uses lowercase keys and calls .lower() on the input, papering over the mismatch. StartSessionRequest.session_mood is unvalidated str. The system currently works because iOS will pass whatever it received from the mood-recommendation endpoint (capitalized) and helpers lowercases it. Deferred consistency pass should pick a canonical casing across DB, helpers, and request validation. Until then, treat capitalized strings (matching brain_session_mood.name) as the canonical wire format for session_mood. The richer `complete_cycle` commits cycle-N's state, then the auto-open of cycle-(N+1) runs as a separate sequence. If the auto-open fails (e.g., `InsufficientInteractionsError`, or another bug surfacing), cycle-N stays committed but cycle-(N+1) is not created — iOS sees a 500 with no recovery path. Recovery today is a manual `start-cycle` call. Production hardening should either wrap Half B in a single transaction or build an idempotent "session is mid-progress, last cycle done, open the next if not done" recovery in `start-cycle`.

### Reliability & cost notes
- Per-cycle search (Decision 2) keeps heavy DB work to ~3 searches/session, not ~21.
- Whisper/GPT cost is unchanged by this work: scoring already runs on `submit-answer`; the adaptive "next pick" piggybacks on a round-trip we already make.
- Persisting the candidate pool (chunk 2) makes a dropped mid-cycle connection resumable.

---

## 6. Decision log

| # | Decision | Rationale |
|---|---|---|
| 1 | Server-authoritative; state in Postgres | Matches existing build; keeps adaptive IP in Python, changeable without app updates |
| 2 | Fixed candidate pool, dynamic next pick (Option B) | Honors "adaptive as they go" + the doc's "set next interaction"; same cost as pre-commit; resumable when persisted |
| 3 | Phase 1 story-only | Sidesteps notion data-model gap and undesignable intent work while exercising the full lifecycle + adaptive engine |
| 4 | Wiring Option 1 (surgical), promote later | Smallest change to get adaptive flow reachable; isolates "does it run" from router reorg |
| 5 | Surgical rewrite over continued patching when fixes accumulate (≥3 small fixes in one function) | `initialize_brand_new_user` was rewritten in chunk 1b after hitting 2 NOT NULL constraints in a row; rewrite produced cleaner code and pre-empted ≥2 more latent NOT NULL bugs the original would have hit. Establishes the tactic for future chunks. |
| 6 | Level-aware notion seeding for brand_new users, located in the brand_new initializer (not at initial-session close-out) | Replaces the current `initialize_notions_for_new_user` which writes all notions at rate 0.0 regardless of level — the bug that produced Issue 1's "no mastered notions" content gap. New behavior: all `brain_notion` rows with `level_from < user_level` seeded at `notion_rate = 1.0` (treated as owned); top 3 notions with `level_from = user_level` (exact match) by `rank` seeded at `notion_rate = 0.0` (in-play). Location decision (b, not a): notions belong to the session that uses them, not to the session that just ended — and elapsed time between initial completion and first regular session may be days/weeks, so seeding at first-regular-session-start is the honest model. Seed count of 3 is a placeholder for the first regular session; future selection algorithm (deferred) will compute it from priority/complexity rates. |
| 7 | First-regular-session cycle-goal override lives inside `calculate_cycle_goal`, not at call sites. Function reads `session.session_rank` and returns `"story"` directly when rank == 1. Falls through to the rotation pattern for rank ≥ 2. | Function-level enforcement means every caller (the adaptive `/start-cycle` handler too) inherits the correct behavior automatically; call-site logic would require every caller to remember the rule. Per ramp-up doc §4: "Cycle-goal selection (§6) does not run in this session — it begins at the second regular session." |

### Deferred to later phases
- **Phase 2 — notion goal:** notion data model (`brain_notion`, `session_notion` fields), §1 H–J notion sort, notion-rate updates (§1G, §5A), notion-goal interaction selection.
- **Phase 3 — intent goal:** requires the "list of intents" design (undefined in the logic doc).
- Bonus/malus rule definitions beyond what `bonus_malus_service` already supports.
- Full §5 depth (speaking/comprehension/accuracy) if trimmed in chunk 3.
- **Pin Render's Python version** (currently unpinned in render.yaml; local dev is 3.9.6, Render defaults to ~3.11). Add a runtime.txt or .python-version before launch so prod is reproducible.
- **Create a `.env.example`** listing required env var names with blank values (DATABASE_URL, OPENAI_API_KEY, AIRTABLE_API_KEY, AIRTABLE_BASE_ID, AIRTABLE_TOKEN, AIRTABLE_TABLE_NAME, JWT_SECRET, CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET) to document local setup without committing secrets.
- **Bucket→level mapping is a placeholder.** initial_level_bucket (0/1/2) → session_level (0/100/200), intentionally conservative (under-estimates; the regular session adapts upward). Loses granularity: onboarding has 5 level answers (A0–B2 = 0–400) collapsed into 3 buckets, so advanced beginners start under-leveled. Revisit when level semantics are finalized.
- **Initial→regular transition calc (future).** A richer close-out could read initial-session performance + elapsed-time-since-onboarding to set smarter opening values (not just level). Bounded in influence to ~the first cycle. Open question: compute at initial-session-end vs. first-regular-session-start. For now, only session_level is written at close-out; behavioral signal (mood, boredom, direction) is deliberately NOT inferred from the tutorial.
- **Verify `expected_total_score` formula.** Chunk 1b's rewrite extrapolated `expected_total_score = session_nbr_cycle * 700` from the initial-session convention (initial: 1 cycle, expected_total_score = 700). The formula isn't documented; revisit when defining the regular-session scoring model in chunks 4–5 to confirm it's right.
- **Numeric column → float standardization.** Per R15, convert at the read site rather than the use site, across all numeric column reads in the codebase. One coordinated pass, not mid-build.
- **Full cycle-goal algorithm (§6 of ramp-up doc).** Per R16, the boredom-band + goal-usage-score algorithm. Required when intent-goal cycles are built.
- **Atomic cycle-boundary in Half B.** Per R17. Lower-priority hardening for production.

---

## 7. Recommended next concrete step

Start **Chunk 0**: the surgical wiring fix plus its embedded discovery (does CRUD `submit-answer`/scoring depend on the CRUD `start-cycle`?). It's low-risk, unblocks everything, and its discovery answer may reorder chunk 6. Once chunk 0 is green, proceed to Chunk 1 — and stop there to reassess, since it's the first real run of cold adaptive code.
