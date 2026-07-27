# TuJe — Voice Detection & Mistake Analysis

**System reference — how a spoken answer is analysed, and how mistakes and intent are surfaced.**

_Last updated: reflects the state after Tier 1, 2a, 2b, 2c and 3 were all built and verified live._

---

## 1. Purpose & core idea

When a user speaks an answer, TuJe does not simply ask "is this right or wrong?" It runs a **graded escalation**: it tries to understand the utterance at progressively coarser levels, and at each level it extracts whatever signal it can — a diagnosed mistake, an identified intent, or (at the very bottom) a coherence judgment for the content author.

The guiding principle: **as understanding decreases, the system degrades gracefully** rather than falling off a cliff. A perfectly matched answer yields a precise verdict and any authored mistakes; a garbled one still yields "we think you were trying to talk about your job, and your attempt was on-topic."

Two orthogonal concepts run through the whole system and must never be conflated:

- **Match quality** (`similarity_score`) — *did we correctly identify which answer/vocab the user said?* This is internal machinery. 100% similarity means "we are confident we matched this thing." It says nothing about whether that thing is good.
- **Answer quality** (`answer_type`) — *is what they said any good?* `perfect` / `good` are correct; `false good` / `wrong` are not. **This is what drives the verdict.**

A 100% match to a *wrong* answer means "we are 100% sure the user said a known-wrong phrasing" → verdict `wrong`.

---

## 2. The pipeline at a glance

A voice answer flows through this sequence inside `_evaluate_voice` (in `answer_split_orchestrator.py`):

```
Whisper transcript ("j'allais euh blablabla")
        │
        ▼
  ADJUSTMENT  (adjustement_adjuster.py)
   • normalize text (contractions, punctuation, whitespace)
   • find vocabulary matches (against transcription_adjusted)
   • notion matching
   • intent matching  (vocab intents ∩ interaction expected intents)
        │  produces: adjusted_transcript, list_of_vocabulary,
        │             list_of_notion_matches, list_of_intent_matches
        ▼
  TIER 1 — ANSWER MATCHING  (matching_answer_service.py)
   • fuzzy-match adjusted transcript against the interaction's brain_answers
        │
        ├── MATCH ─────────► verdict from answer_type;
        │                    mistakes from the matched join row
        │
        └── NO MATCH ─┐
                      ▼
  TIER 2 — VOCAB LEVEL  (only if Tier 1 did not match)
   2a  vocab-authored mistakes   (brain_vocab.mistake_ids)
   2b  attribute-diff mistakes   (brain_attribute_mistake join)
   2c  vocab-derived intent      (adjuster's list_of_intent_matches)
        │
        ├── intent found in 2c ─► surface it; DO NOT call GPT
        │
        └── no intent from 2c ─┐
                               ▼
  TIER 3 — GPT  (only if Tier 2c produced no intent, and verdict is not_understood)
   • GPT infers intent from the expected-intent list
   • GPT judges makes_sense (relevance to the EXPECTED INTENTS)
   • GPT returns a freeform interpretation
```

Everything the tiers produce is surfaced in the **evaluate response**; nothing here decides scoring or advances the session (those are separate `commit` / `advance` steps).

---

## 3. The verdict — driven by answer quality, not match quality

The verdict a user experiences is derived from `answer_type`, **not** from the similarity score.

| Situation | Verdict |
|---|---|
| Matched a `perfect` answer | `perfect` |
| Matched a `good` answer | `good` |
| Matched a `false good` or `wrong` answer | `wrong` |
| No answer matched (below threshold) or no `answer_type` | `not_understood` |

This mirrors the button model exactly (buttons already derive their verdict from `answer_type`), so voice and buttons are consistent. Similarity's only job is deciding *whether* and *which* answer matched; once matched, `answer_type` takes over.

`makes_sense` and `matched_intents` are **informational** — they never change the verdict.

---

## 4. Tier 1 — answer matching

**Precondition:** always runs first.

The adjusted transcript is fuzzy-matched (rapidfuzz) against the `brain_answer` records linked to this interaction. On a match above threshold, the matcher returns:

- `interaction_answer_id` — the `brain_interaction_answer` **join-row** id
- `answer_id` — the `brain_answer` id (a *different* id — see the warning below)
- `similarity_score`

**Mistakes on a match** come from the join row: `_fetch_answer_type_and_mistakes(interaction_answer_id, db_pool)` reads both `answer_type` (→ verdict) and `mistake_ids` (→ mistakes) from `brain_interaction_answer` in one query, then resolves the mistake ids to full `brain_mistake` records.

Because mistakes are authored per-interaction-answer, a `perfect` answer normally carries none, and a matched *wrong* answer carries the diagnosis for that specific wrong phrasing.

> ⚠️ **Critical id distinction.** The matcher returns *both* `interaction_answer_id` (the join row) and `answer_id` (the answer). Mistakes and `answer_type` key on **`interaction_answer_id`**. Passing `answer_id` to the join-row lookup silently finds nothing — the classic "feature looks like it works but always returns empty" bug.

---

## 5. Tier 2 — vocab level (only when Tier 1 did not match)

If no answer matched, we still usually understood *some words*. Tier 2 mines those matched vocab for signal. It has three sub-steps.

### 5a — Direct vocab mistakes

Some `brain_vocab` records carry authored `mistake_ids` (the vocab-level mirror of Tier 1's answer-level mistakes). `_fetch_vocab_mistakes(vocab_ids, db_pool)` reads `mistake_ids` from every matched live vocab, dedupes, and resolves to `brain_mistake` records. Deterministic — no inference.

### 5b — Attribute-diff mistakes (inferred)

Runs only if 2a produced nothing. This is the one **inferred** step, and the most subtle.

**Attributes** are characteristics attached to vocab, interactions, and answers. Each `brain_attribute` has a `name` (e.g. "imparfait"), a `category` (e.g. "tense"), and an `important` boolean.

The mechanism (`_fetch_tier2b_mistakes`):

1. Read the interaction's `expected_attribute_ids` (what a good answer's attributes should look like).
2. For each matched vocab, read its `attribute_ids`.
3. **Filter to `important = true` throughout** — unimportant attributes never contribute.
4. Compute **odd attributes** = `user_attributes − expected_attribute_ids` (asymmetric set difference). An attribute the user's vocab carries that the interaction did **not** expect is "odd." *(Expected attributes the user is missing are ignored — we only diagnose what the user actively got wrong.)*
5. For each `(vocab, odd_attribute)` pair, look up `brain_attribute_mistake` where
   `attribute_matched_id = odd_attribute` **AND** `vocab_matched_id = that vocab` **AND** `attribute_expected_id ∈ expected_attribute_ids`.
6. Resolve any found `mistake_id`s to `brain_mistake` records.

**Worked example.** Interaction "Est-ce que tu vas au cinéma ?" expects `{present}`. The user says "j'allais…", whose vocab carries `{imparfait}`. Odd = `{imparfait}`. Look up `(matched=imparfait, vocab=j'allais, expected=present)` → the authored row → mistake "wrong tense." The verb and pronoun were right (they're in the expected set, so not odd); only the tense is flagged.

**Why mismatch rows are vocab-specific.** From tutor experience: a wrong tense is not *always* a conjugation mistake — with a different verb it might be a different pedagogical error entirely. Keying the mismatch on the specific vocab lets the same `(expected, actual)` attribute pair map to *different* mistakes for different words. This costs more authoring but preserves pedagogical accuracy.

**When the lookup finds nothing** (an odd attribute exists but no mismatch row is authored for that triple): silently return empty. No invented mistakes, no fallthrough.

### 5c — Vocab-derived intent

Independent of the mistake sub-steps. The adjuster already computes, in its Phase 5 intent-matching stage, the **intersection** of each matched vocab's `expected_intent_id` with the interaction's `intents`. That intersection lives in `adjustment_result.list_of_intent_matches`.

Tier 2c simply exposes it: if `list_of_intent_matches` is non-empty, resolve those ids to `{id, name}` via `brain_intent` and surface them as `matched_intents`. **When 2c produces an intent, GPT is not called at all** — we already know the intent, so there is nothing to ask.

---

## 6. Tier 3 — GPT (last resort)

**Precondition:** Tier 2c produced no intent (`list_of_intent_matches` empty) **and** the verdict is `not_understood`.

By Tier 3 we have given up on diagnosing *mistakes* — understanding is too thin. Tier 3 answers two different questions, both anchored to the interaction's **expected intents**:

1. **Intent match** — does the utterance express one of the expected intents above the confidence threshold? If so, return it in `matched_intents`.
2. **`makes_sense`** — is the utterance a plausible attempt to express *any* of the expected intents (in their thematic domain), even below the match threshold? This is a signal **for the content author**: an on-topic utterance is a candidate to be saved as a new answer later.

`_run_gpt_tier3(...)` returns `(matched_intents, makes_sense, interpretation, gpt_used)` and never raises — on any failure it returns `([], None, None, False)` so evaluate still succeeds.

### `makes_sense` semantics — the important subtlety

`makes_sense` is judged **against the expected intents, not against the interaction itself.** The GPT prompt explicitly forbids interpreting the interaction or imagining how the utterance might relate to it in a roundabout way. It judges only: does this utterance plausibly express one of the *listed* expected intents' domains?

- Expected intent is "talk about your job"; utterance is "a red car in a garage" → **`makes_sense: false`** (unrelated to the expected intent).
- Utterance is on-topic for an expected intent but doesn't precisely match one → **`makes_sense: true`, `matched_intents: []`** (the two are genuinely independent).

This was corrected after a test showed GPT rating an off-topic utterance as `true` because it was creatively relating the phrase to the interaction. The fix anchored the judgment to the expected-intent list and baked the failing case into the prompt as a concrete example.

### GPT is called at most once per evaluate

Because Tier 3 only fires when Tier 2c found no intent, and Tier 2c short-circuits GPT when it *does* find one, there is never more than one GPT call per evaluate. When Tier 2c resolves the intent, `interpretation` is intentionally dropped (GPT was not called) — the client must render `matched_intents` without an interpretation in that case.

---

## 7. The evaluate response

`EvaluateAnswerResponse` (in `routers/session_router.py`) carries:

| Field | Meaning |
|---|---|
| `answer_id` | the attempt record id |
| `verdict` | `perfect` / `good` / `wrong` / `not_understood` — from answer quality |
| `similarity_score` | match quality (internal-ish) |
| `mistakes` | list of `{id, name_fr, name_en, description_fr, description_en, type}` from whichever tier produced them |
| `matched_intents` | list of `{id, name}` — from Tier 2c (vocab) or Tier 3 (GPT) |
| `makes_sense` | `true` / `false` / `null` — GPT relevance signal; `null` when GPT wasn't called |
| `interpretation` | GPT freeform text; `null` when GPT wasn't called |
| `gpt_used` | whether GPT fired (key signal for verifying the Tier 2c short-circuit) |
| `debug` | opt-in (see below) |

`mistakes` is a single flat list regardless of which tier(s) contributed, deduped by id. Consumers don't need to know the source tier.

### Debug field (opt-in, voice-only)

Setting `"debug": true` in the request adds a `debug` object:

```json
"debug": {
  "adjusted_transcript": "jallais vocabnotfound vocabnotfound",
  "vocab_matched": [{"id": "VOCAB...", "transcription_fr": "j'allais"}],
  "notion_matches": [],
  "intent_matches": ["INTENT..."]
}
```

This exposes the intermediate state — what the adjuster produced and what vocab/intent matched — which is otherwise invisible. It is the primary tool for diagnosing whether a "no mistake surfaced" result is a code problem or a content/normalization problem. It earned its place immediately by making the contraction bug (below) diagnosable in a single request.

---

## 8. Data model reference

| Table | Role | Key columns for this system |
|---|---|---|
| `brain_answer` | a possible answer | `transcription_adjusted` (matched against), `mistake_ids` (unused — see note) |
| `brain_interaction_answer` | join: answer ↔ interaction | `answer_type`, `mistake_ids` (**authoritative** for Tier 1) |
| `brain_vocab` | a vocabulary unit | `transcription_adjusted`, `attribute_ids`, `expected_intent_id`, `mistake_ids` (Tier 2a) |
| `brain_mistake` | a named linguistic error | `name_fr/en`, `description_fr/en`, `type`, `rule_code` |
| `brain_attribute` | a characteristic | `name`, `category`, `important` |
| `brain_attribute_mistake` | join for inferred mistakes | `attribute_expected_id`, `attribute_matched_id`, `vocab_matched_id`, `mistake_id` |
| `brain_interaction` | the prompt | `expected_attribute_ids`, `interaction_attribute_ids`, `intents` |
| `brain_intent` | a pragmatic purpose | `id`, `name`, `description` |

Notes:

- Tier 1 mistakes live on the **join row** (`brain_interaction_answer.mistake_ids`), not on `brain_answer.mistake_ids` (which is present but unused). This makes a mistake specific to *using this answer for this interaction*.
- `brain_interaction` has two attribute arrays: `interaction_attribute_ids` (all attributes the interaction *contains*) and `expected_attribute_ids` (attributes a user's answer *might* contain). **Tier 2b compares against `expected_attribute_ids`.**
- `brain_intent.name` is the column (not `name_fr`). Using the wrong column name would make Tier 2c silently return empty and push everything to GPT.

---

## 9. The adjustment pipeline (upstream of everything)

Before any tier runs, the transcript is normalized and vocab-matched. This happens in phases inside `adjustement_adjuster.py`:

1. **Normalization** — `text_cleaner.clean_basic` → `expand_contractions` → `remove_punctuation` → number consolidation → whitespace normalization.
2. **Vocabulary extraction** — `VocabularyFinder.find_matches` scans the normalized text against the cached vocab (all live `brain_vocab`, matched on `transcription_adjusted`, longest-first).
3. **Transcript assembly** — `TranscriptAssembler` fills word positions with matched vocab's `transcription_adjusted`, leaving `vocabnotfound` for unmatched positions.
4. **Notion matching.**
5. **Intent matching** — `IntentMatcher.find_intent_matches` intersects vocab intents with interaction expected intents → `list_of_intent_matches`.

**Contraction handling.** French contractions are collapsed so the vocab can be authored as one token. `j'allais` → `jallais`, `j'ai` → `jai`, `c'est` → `cest`. Vocab is authored against the collapsed form (`transcription_adjusted = "jallais"`). If a previously-working voice interaction suddenly stops matching, the first suspect is a mismatch between the pipeline's collapsed output and how that vocab's `transcription_adjusted` was authored.

---

## 10. Hard-won learnings (do not re-encounter)

- **Match quality ≠ answer quality.** Deriving the verdict from `similarity_score` made a 100%-matched *wrong* answer read as `perfect`. The verdict must come from `answer_type`.
- **`interaction_answer_id` ≠ `answer_id`.** Mistakes and `answer_type` key on the join-row id. Using the answer id silently finds nothing.
- **Contraction collapse must match authoring.** `j'` was expanding to `"j "` (two tokens) while vocab was authored as `"jallais"` (one token) → never matched. Fixed to collapse `j'` → `j`, consistent with `j'ai`/`c'est`. This is systemic — it affects every `j'X` utterance.
- **`makes_sense` anchors to expected intents, not the interaction.** Letting GPT interpret the interaction made it too lenient (rated an off-topic phrase as sensible). Anchor strictly to the expected-intent list and forbid free interpretation.
- **Test each tier in isolation.** Because Tier 2a, 2b, 2c and Tier 1 can all surface into the same `mistakes` / `matched_intents` fields, an ambiguous result can look identical across tiers. Verify a tier by *forcing the others to produce nothing* (e.g. temporarily blanking a vocab's `mistake_ids` to prove Tier 2b fires) and by watching `gpt_used` to prove the Tier 2c short-circuit.
- **The debug field is the diagnostic.** "No mistake surfaced" is ambiguous until you can see `adjusted_transcript` and `vocab_matched`. Turn on `debug` before guessing.
- **Silent-empty over invented output.** Every tier returns empty (never raises, never invents) when its authored content isn't present. A missing mistake is a content gap, not a code failure.

---

## 11. What this system does NOT do (yet)

- **Scoring** — the verdict is correct, but voice *scoring* at commit is still similarity-based, so a `wrong` voice answer may still score high until scoring is aligned to `answer_type`.
- **Consuming mistakes** — mistakes and intents are surfaced into the response but nothing yet acts on them (no bonus-malus, no hints, no rescue, no Panel 1 display). Those are downstream steps.
- **Tier 3 mistakes** — Tier 3 produces intent + coherence, not mistakes. By Tier 3 the system has deliberately given up on diagnosing specific errors.
- **Button modes** — this document covers the **voice** path. Button (multi/single) mistake handling is a separate, simpler mirror not yet built.

---

## 12. Escalation summary (one screen)

```
Tier 1  answer match         → verdict from answer_type + join-row mistakes
Tier 2a vocab match          → vocab-authored mistakes                (deterministic)
Tier 2b attribute diff       → inferred mistakes via brain_attribute_mistake
Tier 2c vocab ∩ expected     → identified intent; GPT skipped
Tier 3  GPT                  → intent (from expected list) + makes_sense + interpretation
                               (only when 2c empty & verdict not_understood; ≤1 GPT call)
```

Each tier only runs when the previous levels didn't already answer the question, and each returns quietly empty when its authored content isn't there.
