# TuJe — Vocab-Review Purpose Reference

**Status: LOGIC COMPLETE, verified standalone — NOT yet wired to an endpoint, NOT yet in-app. This is the authoritative "as-built" reference for the vocab-review button purpose. It is one of the button engine's purposes (see `TuJe_Button_Engine_Reference.md` for the overall engine + the other purposes). The remaining step before it's reachable in-app is the dispatcher ("engine B").**

---

## 1. What vocab-review is

A **button purpose** for interactions that use buttons and where the goal is to **review/practice vocabulary** (the intent-cycle purpose; the mechanism is intended to extend to notion and story purposes later).

Unlike **quick-help** (rescue's mic-substitute: one clearly-correct answer + distractors, "spot the right one"), vocab-review presents **several structurally-parallel options where the vocab is the only variable** — the user practices/discriminates vocab, not structure.

**The vision (achieved):** a set like
`J'ai un chien` · `J'ai un chat` · **`J'ai un abricot`** · **`J'ai un kiwi`**
— all the same frame (`J'ai un ___`), valid animals as correct answers, same-frame *wrong-vocab* (fruit/veg) as distractors. To answer, the user must know a chien is an animal and an abricot isn't. That's real vocab knowledge, not structure recognition.

---

## 2. Two difficulty levers (the key design)

**A. Vocab/level lever (the PRIMARY lever for vocab-review).** How hard the vocab is — driven by `level_own`/`level_from` on the vocab vs. the user/cycle level (common owned vocab = easy; rarer/higher-level = hard), plus template complexity. This is vocab-review's main way to scale difficulty.

**B. Answer-type composition lever (reused, secondary).** The existing config engine's perfect/good/false-good/wrong spread, scaled by difficulty (harder = fewer perfect anchors, more/deceptive distractors). This is the *quiz-discrimination* lever — it suits quick-help/mistake more than vocab-review.

**Insight from testing:** the answer-type lever, pushed hard, pulls vocab-review toward "one right + distractors" (quick-help behavior). Vocab-review wants MULTIPLE valid vocab to choose among, so it leans on lever A + valid-heavy configs, not the wrong-heavy end of lever B.

Both levers take the same difficulty input: cycle level direction now (`_determine_difficulty`), with **session_mood** to be added later.

---

## 3. As-built — the pieces (all in the backend, verified standalone)

### 3a. `curate_vocab_review` (orchestrator) — `answer_selection_service.py`
```
async curate_vocab_review(interaction_id, user_level, db_pool,
                          cycle_level_direction=0, selection_mode="single", count=4) -> Dict
```
Flow: `_determine_difficulty(False, cycle_level_direction)` → `_fetch_answers_for_vocab_review` (builds buckets) → `_select_configuration`/`_can_satisfy` (REUSED unchanged — the config matrices + tier-degradation) → `_pick_vocab_answers` → shuffle → 5-key answer dicts (`id, transcription_fr, transcription_en, image_url, answer_type`) + `selection_mode`/`correct_count`/`config`/`difficulty`. Returns `vocab_review_empty` if no config is satisfiable.

### 3b. `_fetch_answers_for_vocab_review` (the vocab-specific fetch) — new
Like `_fetch_available_answers` but:
- **Drops `is_button=TRUE`** (so entity-TEMPLATES are included; they're `is_button=false`).
- **Adds `attribute_ids`** (realization needs the template's required article).
- **PRE-REALIZES each template while conn is open** — one template expands into up to `count` realized rows, each carrying the template's id + realized `transcription_fr` + the template's `answer_type`. Non-realizable (no vocab at level) and null-fr excluded; literals pass through. Keeps buckets synchronous downstream.
- **`perfect`/`good`/`false good` buckets** = the interaction's realized/literal answers (as above).
- **`wrong` bucket** = NOT authored wrongs. Populated by **frame-swap distractors** (§4) — using the interaction's perfect/good ENTITY-TEMPLATES as frame sources, excluding the interaction's own answer ids, deduped on text, capped at `count`. Authored `wrong` rows are skipped for vocab-review.

### 3c. `_pick_vocab_answers` (the picker) — new
Parallel to `_pick_answers` but **dedups on `transcription_fr`, not `id`** — because vocab-review deliberately produces multiple realized rows sharing one template id (chien + chat both from the un-template), and all should be pickable. (The shared `_pick_answers` stays untouched for the authored-button path.)

### 3d. Frame-swap distractor generation — `button_realization.py`
```
async find_frame_swap_distractors(conn, target_transcription_fr, user_level,
                                  count=3, exclude_answer_ids=None) -> list[dict]
```
Mechanism: `_template_frame(target)` reduces the target to a **frame** (its single entity token replaced by sentinel `\x00`, token captured) → fetch all live `%entity%` templates corpus-wide → keep those whose frame matches the target's AND whose entity token **differs** → realize each via `realize_template` (own attrs, level-gated) → return dicts `{id:"FRAMESWAP", transcription_fr:realized, transcription_en, image_url, answer_type:"wrong"}`, deduped on text, capped. Fails safe (`[]`) if the target isn't single-slot or nothing realizes. Key idea: distractors are **real authored templates from other interactions** (their existence = grammatically valid), borrowed as `wrong` here (a valid sentence elsewhere = a wrong answer for this interaction).

### 3e. FRAMESWAP submit-scoring — `answer_split_orchestrator.py`
`_evaluate_multiple_buttons` has a short-circuit: if `selected_answer_id == "FRAMESWAP"`, set `score=30.0, verdict="wrong"`, call `update_answer_with_matching(matched_answer_id=None)`, return the standard 7-key dict with `mistakes=[]` — skipping the answer lookup (which would miss + log a misleading warning). Placed after the `if not selected_answer_id` guard, before the lookup.
- **Safe:** `session_answer.selected_answer_id` is unconstrained varchar (stores "FRAMESWAP" fine); the FK is only on `matched_answer_id`, which stays `None` for wrongs.
- **Correctness rule:** FRAMESWAP must never yield good/perfect (or `matched_answer_id="FRAMESWAP"` would violate the `brain_answer` FK). It's always wrong, so safe.

---

## 4. How a vocab-review set is assembled (end to end)

1. Fetch the interaction's answers; realize the entity-templates → populate perfect/good/false-good buckets with realized vocab (varied animals from one template).
2. Extract the frame(s) from the valid (perfect/good) entity-templates; generate frame-swap distractors from OTHER entities on the same frame → populate the `wrong` bucket (same-frame wrong-vocab, `id="FRAMESWAP"`).
3. The config engine picks a difficulty-appropriate answer-type composition it can satisfy from those buckets.
4. `_pick_vocab_answers` assembles the buttons (dedup on text), shuffled.
5. Result: a structurally-parallel set — correct vocab (good/perfect) + same-frame wrong vocab (FRAMESWAP wrongs).
6. On tap: a real answer submits its id (scored by type); a FRAMESWAP submits the sentinel → scored wrong (30).

---

## 5. Verified (standalone)

- **Core:** `curate_vocab_review` on INT202607041224 realized `J'ai une chatte` into a `good` slot; three cycle directions gave different configs (easy `[good,wrong]`, medium→`[perfect,good,good,wrong]`, hard `[good,wrong,wrong,wrong]`) — difficulty scaling works.
- **Frame-swap generation:** target `J'ai un entityAnimal` @100 → `J'ai un abricot/avocat/kiwi/brocoli` (fruit/veg frame-mates, NOT animals, id=FRAMESWAP wrong); @40 → `[]` (level gate).
- **Fold:** vocab-review wrong slots now show `id=FRAMESWAP text="J'ai un avocat"/"J'ai un abricot"` — same frame as the animal template, composed alongside good/perfect. Structurally parallel.
- **FRAMESWAP scoring:** branch built (parse-verified); end-to-end tap verification waits for wiring.

---

## 6. Test content (authored for this — see `TuJe_FrameSwap_Test_Content_Authoring.md`)

- Animal templates + vocab (from earlier button-engine work): `entityAnimal`, un/une templates, chien/chat/etc.
- Frame-mate entities: `entityClothing` (pull/manteau/pantalon), `entityFruit` (abricot/avocat/kiwi), `entityVegetable` (brocoli/concombre/poivron) — all masculine, un-taking, `level_own=50`, with templates `J'ai un entityClothing/Fruit/Vegetable` [{un}].
- Note: the frame-mate vocab attributes were set directly in TablePlus (pairing `un`[+le], masculin + elision) because those columns weren't yet in Airtable — a testing shortcut; the Airtable sync would need those columns to author this properly long-term.

---

## 7. NOT done / next

1. **Dispatcher ("engine B")** — the cascade that routes a button request to a purpose: `rescue → quick-help; else mistake; else cycle-type (intent → vocab-review)`. NOW EARNED (two real purposes exist). This is what makes vocab-review reachable.
2. **Wire the dispatcher** into `select_answers`/the endpoint so a non-rescue intent-cycle button interaction reaches `curate_vocab_review`.
3. **In-app test** — a real vocab-review interaction: animals + frame-swap wrongs render, tap a wrong → scores 30, tap a valid → scores by type.
4. **A purpose-built vocab-review interaction** — weighted toward animal-template good answers (so good slots fill with VARIED animals, not competing literals like the negative). The test interaction INT202607041224 isn't authored for vocab-review, which dilutes animal variety — mechanism proven regardless.
5. **session_mood** in `_determine_difficulty` (currently rescue + cycle direction only).
6. **Button scoring unification** — the button `type_map` (perfect 100 / good 70 / false-good 50 / wrong 30) is a PLACEHOLDER; intent is to later score buttons through the richer voice-answer 3-phase level-based model + bonus-malus. FRAMESWAP's 30 is a placeholder within that.
7. **Readiness filter** (restrict to owned notions/vocab) — still blocked on data (no notion field on answers, no user-owned-notions table).

---

## 8. Key files & IDs

- Backend: `answer_selection_service.py` (`curate_vocab_review`, `_fetch_answers_for_vocab_review`, `_pick_vocab_answers`), `button_realization.py` (`find_frame_swap_distractors`, `_template_frame`, `realize_template`), `answer_split_orchestrator.py` (`_evaluate_multiple_buttons` FRAMESWAP branch). All committed 2026-08-01, unwired.
- Config engine reused unchanged: `_select_configuration`, `_can_satisfy`, the `SINGLE_SELECT_CONFIGS`/`MULTIPLE_SELECT_CONFIGS` module-level matrices, `_determine_difficulty`.
- Test: `test_realization.py` (standalone, run in terminal).
- Test IDs: interaction `INT202607041224`; animal templates `ANS202407190616` (un), `ANS202407190614` (une); frame-mate templates `J'ai un entityClothing/Fruit/Vegetable` on `INT202607060926`; article `un` = `ATTR202411120628`, `le` = `ATTR202506230331`, masculin `ATTR202607281134`, voyelle `ATTR202607281138`, consonne `ATTR202607281139`.
