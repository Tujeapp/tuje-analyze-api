# TuJe — Button Purpose Engine Reference

**Status: all four purposes BUILT. Quick-help and story are live in production; notion is wired and verified on the deployed backend but content-gated; vocab-review is wired but dormant until intent cycles exist.**

This is the authoritative summary of the purpose system. For the underlying generation machinery (entity realization, attribute matching), see `TuJe_Button_Engine_Reference.md`. For the Airtable fields these depend on, see `TuJe_Airtable_Sync_Requirements.md`.

---

## 1. The core idea

Buttons are **generated, not selected**. Most answers are entity-templates (`J'ai un entityAnimal`) stored for voice-match breadth; they must be *realized* (slot filled with attribute-matched vocab) before they can be shown. `realize_template` does that.

**Any voice answer is buttonable.** An interaction isn't authored as voice-OR-buttons — its answers serve both. So the same interaction can be presented either way, and the engine picks. `answer_mode` is therefore a *presentation decision*, not a property of the interaction.

**The purpose decides how the button set is composed** — which answers become buttons, and critically, what "wrong" means.

---

## 2. The governing rule — one dimension per purpose

**Distractors must differ from the correct answer on the purpose's own dimension, and be correct on every other dimension.**

| Purpose | Wrongness dimension | A wrong answer is… |
|---|---|---|
| **Vocab** (intent) | wrong category | the main vocab isn't the vocabulary being practised |
| **Notion** | notion misuse | contains a mistake, and that mistake relates to the target notion |
| **Story** | off-conversation | the meaning isn't related to the current conversation |
| **Quick-help** (rescue) | plain correctness | any authored wrong — legibility is the goal |

**Never confuse a purpose with the mistake purpose.** Rémi's examples:

- *Vocab* — "Est-ce que tu as un animal ?" ✅ `un chat` / `un chien` / `un lapin` / **`un téléphone`** (wrong category, grammatically perfect). ❌ `un chat` / **`un chienne`** / **`un chatte`** — all valid animals; the fault is *gender agreement*, which is the mistake dimension.
- *Notion* (target: verb *aller*, present) ✅ `Oui, je vais au supermarché` (perfect) / `Oui` (false good — too incomplete) / `Oui, je vais` (good — partial) / `Oui, je suis au supermarché` (wrong verb). Distractors carrying notion-mistakes (`je va`, `je aller`) are also valid notion distractors.
- *Story* — "Est-ce que tu vas au supermarché ?" ✅ `Oui, je vais au supermarché` (perfect) / `Oui` (good) / `Non, je vais pas au supermarché` (perfect — story can have MULTIPLE perfects; conversation has no single right answer) / `Oui, je suis au supermarché` (wrong meaning). ❌ `à la supermarché` variants — article errors, i.e. mistake dimension.

**Consequence for generation:** generated distractors must never introduce grammatical errors. Frame-swap satisfies this by construction (it borrows real authored templates and fills them with attribute-matched vocab, so `un chatte` is impossible).

---

## 3. The dispatcher — a two-stage presentation decision

Runs where the next interaction is set up (`start_new_cycle` for interaction #1, `advance_to_next_interaction` for #2–7), and **stamps its decision on `session_interaction`**.

**Selection is NOT affected.** Which interactions a cycle serves is already decided at cycle-start by the cycle goal (notion cycles filter `expected_notion_id @> [target_notion]`; story is subtopic-scoped; intent has its own search). The dispatcher only decides *presentation* of already-selected, already-goal-correct interactions.

### Stage 1 — mode (voice vs buttons), by PLAN
```
free / basic → multipleButtons   (buttons by default)
pro          → voice             (voice by default)
unknown      → voice             (safe default)
```
Pro-escalation-to-buttons (slow session / high frustration / level going down) is DRAFT — stubbed, not built.

### Stage 2 — purpose (only when mode is buttons), by CYCLE GOAL
```
intent → "vocab_review"    (dormant: no intent cycles exist yet)
story  → "story"
notion → "notion"
else   → "default"          (authored-button path)
```

**Rescue is a RUNTIME override, not stamped.** Rescue flips a voice interaction to buttons mid-interaction and serves quick-help. So `/answers-by-interaction` resolves: `if rescue_triggered → quick_help; elif stamped button_purpose → that curator; else → authored-button path`.

### Persistence & delivery
- `session_interaction.answer_mode` + `button_purpose` — stamped at both creation sites.
- `session_cycle.target_notion_id` — stamped at cycle-start (returned from the notion search so it's provably the notion that filtered the interactions).
- Delivered to the client in the payloads it already consumes: `StartCycleResponse` (cycle 1), `NextCycle` (cycles 2–3), `AdvanceInteractionResponse` (interactions 2–7). The client prefers the stamped mode over the authored one (`pendingStampedMode ?? response.answerMode`), so unstamped/legacy content is unaffected.

---

## 4. The four purposes as built

All four bucket answers by `answer_type` into `{perfect, good, false good, wrong}`, then let the **existing config engine** (`_select_configuration` / `_can_satisfy` / the `SINGLE_/MULTIPLE_SELECT_CONFIGS` matrices) compose a difficulty-appropriate set. Difficulty comes from `_determine_difficulty(rescue, cycle_level_direction)` — rescue→easy, level up→hard, level down→easy, steady→medium. What differs between purposes is **which answers qualify, and where the wrongs come from**.

### 4a. Quick-help — `curate_quick_help` (rescue's mic substitute)
One clearly-correct answer + clearly-wrong distractors, so the right one is easy to spot.
- Correct = prefer `perfect`, else highest-typicality `good`. Distractors = authored `wrong`.
- Templates realized to ONE common fill (`max_fills=1`) — quick-help wants one obvious correct, not a spread.
- Forces `selection_mode: "single"` (inherently pick-one).
- **Level is DB-authoritative** — ignores the client-sent `user_level` (which for rescue is the frustration floor, often 0) and reads `session_cycle.cycle_level`.

### 4b. Vocab-review — `curate_vocab_review` (intent cycles)
Several structurally-parallel options where **vocab is the only variable**.
- Valid answers = the interaction's own, realized (one template spreads into multiple vocab).
- **Wrongs = frame-swap distractors** (§5a) — same frame, different entity.
- Difficulty lever is **vocab/level** (`level_own`, commonness), not distractor deceptiveness.
- Dormant: no intent cycles exist yet.

### 4c. Story — `curate_story` (story cycles) — LIVE IN PRODUCTION
The interaction's own valid answers + **answers borrowed from other interactions** (§5b).
- Wrongs = valid answers from a *different, non-variant* interaction — valid there, wrong here.
- Distance is the difficulty lever: same-subtopic (subtle) for hard/medium, cross-subtopic (obvious) for easy, with a tier fallback so a miss never dead-ends.

### 4d. Notion — `curate_notion` (notion cycles) — wired, content-gated
Both sides notion-scoped:
- **Valid**: answers whose `brain_answer.matched_notion_ids` contains the cycle's `target_notion_id` — the answer *contains* the notion.
- **Wrong**: answers whose join `mistake_ids` is non-empty AND **⊆ the notion's `brain_notion.mistake_ids`** — every mistake it carries belongs to this notion. An answer carrying a notion-mistake *plus* an unrelated one is excluded (one-dimension rule).
- ⚠️ **Containment is done in Python, not SQL** — `bia.mistake_ids` is `varchar[]` while `brain_notion.mistake_ids` is `text[]`, and `varchar[] <@ text[]` fails at runtime (`operator does not exist`). Verified empirically.
- NULL-guard: if the cycle has no `target_notion_id`, log and fall through to the authored-button path.

### 4e. Mistake — NOT built, and it's a MODE OF STORY
Notion and intent cycles are *forced* practice on an app-chosen target, so mistakes are incidental there. **Story is where the user genuinely produces language**, so it's where real mistakes surface and where practising them belongs. Mistake isn't a fourth peer purpose — it's a mode within story cycles (some interactions continue the conversation, some pivot to a recurring mistake).

---

## 5. The two distractor generators

### 5a. `find_frame_swap_distractors` — for vocab
Reduce the target template to a **frame** (entity token replaced by a sentinel), search all live templates corpus-wide for the same frame with a **different entity**, realize them at the user's level. `J'ai un entityAnimal` → `J'ai un abricot` / `J'ai un kiwi`.
- Distractors come from **real authored templates** — their existence elsewhere guarantees grammatical validity.
- Returns `id: "FRAMESWAP"`.

### 5b. `find_story_distractors` — for story
Borrow **perfect/good answers from other interactions** — valid responses to a different question.
- **Bidirectional variant exclusion**: excludes self, the ids it lists in `variant_ids`, AND any interaction listing it. A variant's answer would be *valid* here, so borrowing it would create a false-wrong. The bidirectional check means imperfect/asymmetric variant data can't cause that.
- Tier by difficulty: same-subtopic (subtle) vs cross-subtopic (obvious).
- Returns `id: "BORROWED"`.

### Shared safeguards
- **Text-collision filter** — a borrowed/swapped distractor whose text matches any of the interaction's *own* answers is dropped (verified case: `Voilà` was being borrowed back as a distractor for an interaction whose perfect answer is `Voilà`).
- **Sentinel scoring** — `_evaluate_multiple_buttons` short-circuits on `selected_answer_id in ("FRAMESWAP", "BORROWED")` → score 30, verdict wrong, `matched_answer_id=None` (keeps the sentinel out of the FK column), no answer lookup. Verified in-app.
- **perfect→good promotion** — `perfect` answers also count toward `good` slots (a perfect IS a valid answer), so a thin pool isn't starved. `_pick_vocab_answers` dedups on text, so nothing is placed twice.

---

## 6. Answer identity (Option A) and the client

**A realized button carries the TEMPLATE's answer id** — tapping submits that id, and scoring treats it as that answer's type. The vocab fill is display-only, which is sound because the vocab was selected to fit, so the sentence inherits the template's type.

Consequence: **`id` is deliberately not unique per button** (multiple fills of one template share it; sentinels repeat). The client therefore separates:
- **`displayKey`** = `"\(id)|\(transcriptionFr)"` — rendering (`ForEach`) and multi-select tracking. Unique because curators dedup on text.
- **`id`** — submission only.

Without this, `ForEach` warns "the ID occurs multiple times… undefined results", and multi-select would mark both duplicates selected while under-counting against `correctCount`, stranding the user at Confirm.

---

## 7. Content rules the engine depends on

1. **Multiple-select interactions need 2+ `good` answers.** Every `MULTIPLE_SELECT_CONFIGS` config requires two goods; a thin pool satisfies nothing and returns empty. **Decision: don't mask this** — the empty result is the correct signal that content needs authoring. (Verified: adding one `good` answer per interaction in a subtopic fixed it, with `selection_mode='multiple'` restored as authored.)
2. **Variants must be complete and symmetric** — every unflagged near-duplicate is a potential false-wrong in story distractors.
3. **Notion answers need annotation** — `matched_notion_ids` on valid answers, and wrong answers whose mistakes fall inside a notion's mistake set.
4. **Vocab needs attributes** — `pairing_attribute_ids` (the articles it takes) is what lets a template's slot requirement match; without it, realization returns nothing.

---

## 8. Deferred

- **Notion content** — `matched_notion_ids` across answers, notion→mistake links, grammar-family mistakes (only `Prononciation` exists today).
- **Intent cycles** — to activate vocab-review.
- **Mistake mode within story.**
- **Session mood** in `_determine_difficulty` (currently rescue + cycle direction only).
- **Pro-escalation to buttons** (slow session / frustration / level-down).
- **Scoring finalisation** — button scoring is a flat placeholder `type_map` (perfect 100 / good 70 / false-good 50 / wrong 30); intended to mirror the voice 3-phase level-based model + bonus-malus. Also: `similarity_score` is overloaded as the carrier for button grades, though buttons have no matching stage — fix as part of that work.
- **Readiness filter** — restrict to notions/vocab the user owns (blocked: no user-owned-notions table).
- **Test data cleanup** — the fake `MIST_TEST_*` / `ANS_TEST_*` / `BIA_TEST_*` rows.
