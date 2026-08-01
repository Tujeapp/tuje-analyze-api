# TuJe — Button Generation Engine (Design Spec)

**Status: design. No code yet. This spec harmonizes voice and multiple-button answers into a single answer model, and defines a purpose-driven engine that GENERATES buttons — not merely selects them. Because answers are stored as entity-templated forms (e.g. `j'ai entityNumber entityPet`, not literal sentences), the engine must realize speakable buttons by filling entity slots with user-appropriate vocab, using authored attribute-matching so output is provably grammatical with no GPT. The rescue-legibility purpose is designed first; other purposes are sketched and deferred.**

## 0. STATUS — realization CORE built & verified on live data (2026-07-28)

The hardest piece — `realize_template` — is BUILT and VERIFIED end-to-end against real DB data. It turns a templated answer into grammatical display strings by filling entity slots with attribute-matched vocab. No GPT, no morphology engine — pure authored attribute-matching, exactly as designed.

**File:** `button_realization.py` (backend, repo root, untracked/uncommitted). Pure: `find_entity_tokens(text)` + `async realize_template(conn, template_transcription_fr, template_attribute_ids, user_level, max_fills)`.

**Mechanism (verified):** parse the entity token from `transcription_fr` (regex `entity[A-Z][a-zA-Z]*`) → map token to `brain_entity` by `name` → select `brain_vocab WHERE entity_type_id = entity AND live AND (level_own IS NULL OR level_own <= user_level)`, ranked `commonness DESC NULLS LAST, transcription_fr` → keep vocab where the template's required `attribute_ids` ⊆ (vocab own `attribute_ids` ∪ `pairing_attribute_ids`) → replace the token in `transcription_fr` with the vocab's `transcription_fr` → up to `max_fills` strings. Fails safe (returns [] + logs) on no-token (literal), unknown entity, multi-token (deferred), or no qualifying vocab.

**Verified 5/5 on live data:**
- `J'ai un entityAnimal` [req un] @level100 → `["J'ai un chat", "J'ai un chien", "J'ai un oiseau"]` (âne excluded: level_own 150 > 100).
- `J'ai une entityAnimal` [req une] @100 → `["J'ai une chatte", "J'ai une chienne"]`.
- same @level200 → âne now included (150 ≤ 200), ordered by commonness.
- `J'ai un entityAnimal` @level40 → `[]` (all animals level_own ≥ 50 > 40) — level gate proven.
- literal `Je n'ai pas d'animaux` (no token) → `[]` — literals correctly not realized (caller uses as-is).

Ordering note: equal-commonness ties break alphabetically by `transcription_fr` (chat < chien) — deterministic, acceptable; could later tiebreak on level_own or an authored priority.

**Test data seeded (live DB, hand/Airtable-authored):**
- New `brain_vocab` columns: `pairing_attribute_ids text[]`, `commonness real DEFAULT 0.5`, `level_from int`, `level_own int`.
- New `brain_interaction_answer` columns: `answer_typicality real DEFAULT 0.5`, `never_a_button boolean DEFAULT false`.
- `entityAnimal` (ENTI202408150147) vocab: chien/chat (masc, consonne; pairing un/le; commonness 1.0; level_own 50), oiseau (masc, voyelle; un/l'; 0.6; 100), chatte/chienne (fém, consonne; une/la; 0.4; 100), âne (masc, voyelle; un/l'; 0.3; 150).
- Attributes authored (Airtable): article un/une/le/la/les/des/l'; elision voyelle/consonne; gender masculin/féminin; number singulier/pluriel.
- Three template answers on INT202607041224: `J'ai un entityAnimal` [attr un], `J'ai une entityAnimal` [attr une], `Je n'ai pas d'animaux` [literal]. Article requirement lives on `brain_answer.attribute_ids`; `answer_type`/`answer_typicality` on the join.

**NEXT:** build the rescue-legibility CURATION on top (combine multiple templates + literals into a capped, deduped, coverage-aware button set), then wire to the `answers-by-interaction` endpoint (replacing the empty fetch), closing rescue's no-buttons gap.

---



---

## 1. The problem & the reframe

Today `is_button` is an **exclusive** flag: an answer marked `is_button` is a button and NOT a voice-match target, and vice versa. This splits one conceptual object — *an answer to an interaction* — into two disjoint sets, which is wasteful and rigid.

**The reframe:** an answer is just an answer. "Can it be spoken?" and "can it be a button?" are not separate kinds — they're contextual uses. Almost any answer is a *legitimate* button candidate. The real question is never "is this answer button-worthy" in the abstract — it's:

> **Given WHY we're showing buttons right now, which answers serve that purpose?**

The app is taking the lead ("you're going to answer this way"), so it must know the *purpose* behind the button set. The same answer can be a great button for one purpose and wrong for another. So button-eligibility is **contextual and computed**, not a fixed per-answer property.

**The single-button-timer answer is carved out entirely.** It's not a content answer — it's a listening-timing probe (tap-while-playing), with its own scoring and purpose. Harmonization is about **voice answers ↔ multiple-button answers only**; the single-button-timer stays its own untouched thing.

---

## 2. Why harmonize (benefits)

- Every answer (except the single-button-timer) becomes useful in both modes → more flexibility, more creative ways for the user to answer.
- Enables more sophisticated hints and rescue (a rich pool to draw curated button sets from).
- Increases the chance the user always answers an interaction → the app follows the session to the end.
- Simpler authoring: author an answer once with all its info; it serves both voice and button.

---

## 3. The engine skeleton — TWO LEVELS (generation, not just selection)

Because answers are entity-templates, the engine works in two levels: pick templates, then realize them into speakable buttons.

```
select_buttons(interaction, context):

  LEVEL 1 — TEMPLATE SELECTION (purpose-driven)
    candidates = interaction's answers minus never_a_button
    determine PURPOSE from context → choose a strategy + profile
    rank/pick templates using: answer_type, answer_typicality,
      answer_optimum_level, intent (dedup), attributes,
      the interaction's expected vocab/notion

  LEVEL 2 — REALIZATION (fill entity slots with vocab)
    for each chosen template:
      parse its entity slots + their RESOLUTION ORDER
        (controlling slots like entityNumber resolved FIRST — they
         constrain the dependent slots)
      resolve controlling slots by their rules
        (entityNumber → singular default, or reuse user metadata)
      for each free slot (e.g. entityPet):
        candidate vocab = vocab where:
          - tagged with the entity (entityPet)
          - the vocab's PAIRING attributes match the template's slot
            attributes (article un/une, number, elision de/d')  ← grammar
          - vocab level ≤ user level (ownable)
          - [prefer] in the user's known vocab (reuse what they learned)
          - [prefer] the interaction's expected/target vocab (teaching)
          - ranked by commonness-within-entity (authored 0–1)
        pick target vocab first, then common vocab, up to the cap
      assemble → a guaranteed-grammatical sentence (one template may
        yield MULTIPLE buttons, e.g. one per pet, for vocab practice)

  CURATE
    dedup (by intent), ensure coverage (e.g. offer a negative option),
    cap (e.g. 4 buttons max)
```

Candidate templates = all of the interaction's answers EXCEPT those marked `never_a_button`.

**Two key properties:**
1. **Discrimination is computed from purpose + properties**, not a per-answer "good button" flag — preserving sophistication for advanced users.
2. **Grammar is guaranteed by attribute-matching, not computed.** The template is pre-written correct French with a slot; the slot carries the grammatical attribute (e.g. `article: un`); only vocab whose *pairing attributes* accept that (masculine nouns) can fill it. So "j'ai un chien" is producible, "j'ai un chatte" is not — the filter forbids it. No morphology engine, no GPT, full authoring control.

---

## 3b. Realization in detail — the attribute-matching that guarantees grammar

**Worked example.** Purpose: practice animal vocab, easy level. Cap: 4 buttons.
- Level 1 picks two templates: `j'ai un entityPet` (attributes: pronoun *je*, verb *avoir*, present, **article un**) and `j'ai une entityPet` (same, but **article une**).
- Level 2, for `j'ai un entityPet`: among entityPet vocab at/below user level and known by the user, keep those whose pairing attributes include **article un** (masculine nouns), rank by commonness → **chien, chat**.
- For `j'ai une entityPet`: same, but pairing attribute **article une** (feminine) → **chatte, chienne**.
- Result: four grammatical buttons — *j'ai un chien, j'ai un chat, j'ai une chatte, j'ai une chienne*.

**Pairing (accompanying) attributes.** Each vocab record carries TWO kinds of attributes:
- **Own attributes** — what it *is* (entity membership, level, gender…).
- **Pairing / accompanying attributes** — what usually *goes with* it. A noun pairs with an article; the specific article (un/une) encodes the gender agreement. Elision (de/d') is encoded by whether the vocab pairs with the vowel-form or consonant-form. Not every vocab has pairing attributes, but nouns typically do (they come with an article).

The template's slot attributes are matched against the vocab's pairing attributes. That match IS the grammar check. (Note: article-pairing may be *derivable* from the vocab's existing `gender` column — template `un` needs `gender: masculine` — reducing new authoring. Elision (de/d') is NOT derivable from gender; it needs first-letter/vowel info, which may need adding. To verify against the real vocab schema.)

**Controlling slots & resolution order.** Some entities constrain others and must be resolved first:
- **entityNumber is controlling.** Rule: default to **singular** ("un") when there's no metadata. If the app has user metadata (e.g. it knows the user "has 2 dogs"), it may temporarily reuse it → "deux". Once entityNumber is fixed, it constrains dependent slots (deux → the noun slot must be plural).
- Most entities are **free** (filled purely by the vocab-selection logic).
- So a template defines, per slot: whether it's controlling or free, its resolution order, and its required attributes.

*(Numbers were historically the hardest case in the answer-matching adjustment process. Resolving entityNumber FIRST, by explicit rules, and letting it set context for the rest, is the tractable handling. The "reuse user metadata" part — the app remembering facts about the user's life — is a richer LATER enhancement; the first build just uses the singular default.)*

**The vocab-practice spread.** When the purpose is vocab practice, ONE template yields SEVERAL buttons (multiple pets). The spread = the interaction's expected/target vocab first (the vocab being taught), filled out with common vocab for variety, capped. This is where the interaction's expected vocab/notion does its work.

---

## 4. The authored signals

### 4a. Answer / template signals (interaction-answer join)

| Signal | Type | Meaning |
|---|---|---|
| **`answer_typicality`** | float 0–1 | How **central/typical** this answer is within THIS interaction's pool. 1 = very typical (conventional, expected shape); 0 = distinctive/creative. NOT matching similarity — a typical↔distinctive axis. Yes/no interaction → answers near 1; open interaction → spread toward 0. Optional, neutral default 0.5. |
| **`intent`** | (existing) | The answer's intent — used as the **dedup key**. Answers sharing an intent ("pay by cash") are the same button-meaning, different wording → show one representative. Preferred over a manual `same_answer_ids` grouping because it's already authored and semantically principled. (to verify it exists) |
| **`never_a_button`** | boolean | Hard exclusion — never a button for this interaction (too long, deliberately-tricky wrong answer, etc.). Per-interaction. |
| **template slot attributes** | (via the answer's attributes) | The grammatical requirements the template imposes (e.g. `article: un`), matched against vocab pairing attributes (§3b). Plus per-slot resolution order (controlling vs free). |
| *(existing)* `answer_type`, `answer_optimum_level`, `attribute_ids`, `mistake_ids`, expected vocab/notion | — | Property vectors + teaching targets used by Level-1 selection and Level-2 vocab-targeting. |

**Note — `same_answer_ids` deprecated in favor of `intent`.** Originally we planned an explicit `same_answer_ids` grouping for dedup. But **intent** already encodes "same meaning, different wording" and is authored + principled → use it as the dedup key instead. Keep `same_answer_ids` in reserve only if intent-dedup later misses rare cross-intent lookalikes.

**`is_button` is REPLACED** — the exclusive flag goes away. Every non-`never_a_button` answer is a template candidate; the engine decides.

### 4b. Vocab signals (`brain_vocab`, per record and per vocab-entity pairing)

| Signal | Type | Meaning |
|---|---|---|
| **entity membership** | (existing/to verify) | Which entity/entities this vocab can fill (entityPet, etc.). |
| **own attributes** (gender, plural…) | (existing) | What the vocab is. `gender` may double as the article-pairing source (masculine → un). |
| **pairing / accompanying attributes** | (new concept) | What grammatically accompanies this vocab — the article it takes (un/une), number behavior, elision (de/d'). Matched against the template's slot attributes to guarantee grammar. May be partly derivable from `gender`; elision needs first-letter/vowel info (may need adding). |
| **vocab level** | `level_from` + `level_own` (new, authored) | Two levels: **`level_from`** = from when the vocab is taught/introduced; **`level_own`** = from when it's considered owned (≥ level_from). Different purposes use different ones: **rescue filters on `level_own ≤ user_level`** (give struggling users vocab they KNOW); **vocab-practice** uses `level_from ≈ user_level` (words being introduced). A single level couldn't express "known" vs "being learned." |
| **commonness-within-entity** | **new, authored 0–1, PER vocab-entity pairing** | How default/expected this vocab is for THIS entity. 1 = the go-to (e.g. "chat"/"chien" for entityPet); 0 = obscure. Per-pairing because a vocab can belong to multiple entities with different commonness. The vocab-level analogue of `answer_typicality`. |
| **user-known status** | (from user vocab history) | Prefer vocab the user has already learned — personalizes buttons, reinforces their real vocabulary. |

**The system is fractal:** `answer_typicality` picks central answers among the interaction's answers; `commonness-within-entity` picks central vocab among the entity's vocab. Same "prefer the default, vary when purpose wants variety" idea, one level down.

### 4c. Entity rules
Controlling entities (like **entityNumber**) carry **rules**: e.g. default singular when no metadata; optionally reuse user metadata (LATER). Resolved first; set constraints for dependent slots.

---

## 5. The property vectors (mostly existing) each strategy scores against

- **`answer_type`** — perfect / good / false-good / wrong.
- **`answer_optimum_level`** — for level-fit to the user/cycle.
- **`attribute_ids`** — linguistic features (conjugation, tense, sentence type…).
- **`vocab_ids`** — vocabulary used.
- **`mistake_ids`** — which mistakes this answer represents or contrasts.
- **length / richness** — derivable from the text.
- **`answer_typicality`** — the new central↔distinctive axis (§4).

Each strategy weights these differently. The same pool, sampled by different objectives, yields different button sets.

---

## 6. Context → purpose

**Context inputs** (why we're here / what the app wants):
- **Cycle goal** — story / notion / intent (vocab).
- **How the cycle is going** — progress, recent performance.
- **User frustration** — the rescue state (the frustration brain we built).
- **Interaction purpose** — what this interaction expects: a specific conjugation, vocab, sentence type, speed, or creativity.

**Purposes** (each → a strategy):
1. **Rescue / struggling** → clear, legible, easy answers with one obvious perfect; drop near-variants. *Maximize legibility.* (Designed in full below.)
2. **Mistake-correction** → show near-variants that highlight the *specific* recurring error. *Maximize contrast on the error dimension.* (Deferred.)
3. **Inspiration** → several valid answers of varying length/typicality, to expand what the user thinks possible. *Maximize range.* (Deferred.)
4. **Cycle-goal default** → the normal button set for the cycle's goal. (Deferred.)

**Note on purpose-relative distinctness:** "too similar to show together" depends on purpose. Rescue → near-variants are noise, drop them. Mistake-correction → near-variants are the whole point, keep them. So dedup is applied *within each strategy*, not as a global rule. `same_answer_ids` marks *identical* answers (always dedup-able); typicality-proximity marks *stylistically close* answers (drop only when the strategy wants legibility).

---

## 7. Strategy #1 — Rescue / legibility (BUILD FIRST)

**When:** user frustration has reached a rescue band (0.4+) on a voice interaction and the app is presenting buttons (auto-switch/lock, or the invite toggle's target set).

**Goal:** give a struggling user a small, clear, unambiguous set with one obviously-correct answer — so they can succeed and move on.

**Profile / selection rules:**
- **Include exactly one clear perfect answer** (`answer_type = perfect`), preferring **high `answer_typicality`** (the most conventional, easiest-to-recognize correct answer — not a clever/distinctive one).
- **Fill the rest with legible, distinct options:** prefer **high-typicality** answers (central, easy to parse), spread so no two are near-duplicates.
- **Level:** prefer answers at or below the user's level (eased) — don't hand a struggling user a high-level distinctive phrasing.
- **Dedup hard:** never include two answers from the same `same_answer_ids` group; also avoid two answers at near-identical typicality that read as clones (legibility > variety here).
- **Small cap:** a handful (e.g. 3–4), not the full pool — cognitive load matters for a frustrated user.
- **Exclude** `never_a_button` and, for rescue, likely exclude confusing false-good answers (a struggling user shouldn't be tricked) — TBD in build.

**Why typicality drives this:** rescue wants the *opposite* of sophistication — the clearest, most expected answers. High typicality = exactly that. (Contrast: the inspiration strategy would deliberately pull LOW-typicality answers for creativity.)

**This closes the rescue no-buttons gap.** The deferred "what if an interaction has no authored buttons" question (rescue spec §7c) dissolves: with harmonization, a voice interaction's own answers ARE the button pool, curated by this strategy. Rescue no longer needs separately-authored buttons — it selects legible buttons from the answers that already exist for voice matching.

---

## 8. Scoring a harmonized answer (voice → buttons mid-interaction)

**Decision:** if a user starts on the mic, struggles, and finally answers via buttons (through rescue/hints), the interaction **scores as a button answer**, with bonus-malus reflecting the journey (the accumulated maluses from the failed voice attempts pull the score down).

**This falls out naturally from the level-based scoring model:** the 3-phase Interaction Score keys off the **matched answer's level** (coefficient from `answer_optimum_level` vs interaction/cycle level) — it does NOT care *how* the answer was reached. So a button answer scores through the *same* model as a voice answer, using that answer's level, and bonus-malus expresses the struggle. This means harmonization can **retire the separate Chunk-2 button-scoring path** — one level-based model for all matched answers, voice or button. (Bigger change; sequence after the selection engine works.)

---

## 9. Schema changes (to VERIFY + author test data directly in DB first; Airtable sync later)

**On `brain_interaction_answer` (the join):**
- `answer_typicality float` default 0.5.
- `never_a_button boolean` default false.
- Confirm `intent` is present (for dedup) and how the answer's grammatical attributes (article un/une) are represented — via the existing `attribute_ids`, or elsewhere.
- Retire `is_button` (lives on `brain_answer`) as an exclusive partition.

**On `brain_vocab`:**
- Confirm existing: entity membership, `gender`, `plural`, level.
- Add if missing: **pairing/accompanying attributes** (article, elision/first-letter) — some derivable from `gender`, elision likely not.
- Add: **commonness-within-entity** (float 0–1) — but this is PER vocab-entity pairing, so it may belong on a vocab-entity join table rather than a single column on `brain_vocab`. Verify how vocab↔entity is modeled (a join table would be the natural home for both entity membership AND per-pairing commonness).

**Entity model:** verify how entities are defined and how a template's `entityPet` token maps to the vocab that can fill it. Controlling-entity rules (entityNumber) need a home.

**Attribute unification (Open 4):** grammatical attributes (gender/article/number/elision) are NOT currently in the unified `attribute_ids` system. Decide during DB verification whether to unify now (so one matching primitive works for template-slot ↔ vocab-pairing) or bridge with a mapping. Unifying is cleaner long-term.

Conventions when these later sync from Airtable: lookup arrays extract `[0]`; camelCase→snake_case mapping must be explicit; floats need numeric casts; `update_at` (no 'd') is the preserved column name on `brain_*` sync tables.

---

## 10. Build order

1. **DB verification** (next step, this conversation): confirm the vocab/entity/attribute schema against this design — how vocab↔entity is modeled, what grammatical metadata vocab carries (gender/plural/elision), whether `intent` exists on answers, how template attributes are stored. This grounds everything.
2. **Schema + hand-authored test data** (directly in DB, NOT Airtable yet): add the new columns; author a test interaction end-to-end — a template like `j'ai un entityPet` with attributes, and entityPet vocab with pairing attributes + commonness + level — enough to realize buttons.
3. **The realization function** — given a template + context, fill entity slots with attribute-matched vocab → grammatical sentences. Core new machinery; build + test in isolation first (does `j'ai un entityPet` → `j'ai un chien`?).
4. **The engine + rescue-legibility purpose** — Level-1 template selection + Level-2 realization, wired to a rescue context.
5. **Wire rescue → the engine** — replaces the current empty-button fetch; closes the no-buttons gap.
6. **Test** on the rich interaction: rescue gets a small, legible, grammatical, deduped, personalized button set.
7. **Later arcs:** cycle-goal default; mistake-contrast; inspiration; vocab-practice spread; entityNumber user-metadata reuse; scoring unification (retire split button-scoring); attribute unification.

---

## 11. Open questions / honest hard parts

- **Grammatical assembly** — solved by authored attribute-matching (template slot attributes ↔ vocab pairing attributes); no morphology engine, no GPT. Cost is more authoring, accepted deliberately (core IP; control > convenience). Feasibility hinges on the DB carrying (or being able to carry) the pairing attributes, esp. elision (de/d'), which isn't derivable from gender.
- **entityNumber / controlling slots** — resolved first, by rules, setting constraints for dependent slots. First build: singular default. User-metadata reuse ("has 2 dogs") is a later enhancement.
- **Attribute unification (Open 4)** — grammatical attributes not yet in the unified `attribute_ids` system. Unify now or bridge — decide at DB verification.
- **Commonness / typicality authoring burden** — mitigated by neutral defaults; a tool used where it matters. Commonness is per vocab-entity pairing (more precise, more authoring).
- **`intent` as dedup key** — replaces the planned `same_answer_ids`; already authored + principled. Keep `same_answer_ids` in reserve only for rare cross-intent lookalikes.
- **Context → purpose mapping** when purposes overlap — needs a priority rule later. Only rescue exists now, so no conflict yet.
- **Over-engineering risk** — build realization + rescue-legibility only; add purposes as real needs arise.
- **Personalization payoff** — reusing the user's known vocab to build buttons is a real pedagogical edge. Depends on user-vocab-history being queryable at button-generation time.
