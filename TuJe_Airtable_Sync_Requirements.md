# TuJe — Airtable → Postgres Sync Requirements (Button Engine)

**Purpose of this document:** a complete, self-contained handover for the Airtable-sync conversation. It lists every field the button/purpose engine depends on, which already sync, which need adding, and the gotchas that have already bitten.

**Context:** the button engine generates buttons from authored content — it realizes entity-templates into sentences, and picks distractors by grammatical and semantic relations. Every one of those decisions reads a synced column. Where a column is missing, the corresponding purpose returns no buttons.

**Current workaround:** the fields marked NEW below were added directly in TablePlus for testing. They are **not in Airtable and not in the sync**, so they will be lost or unmaintained until the sync supports them.

---

## 1. NEW fields needed in Airtable + sync mapping

### 1a. `brain_interaction.variant_ids text[]` ← Airtable `MatchedAsVariant`
**Exists in Airtable as `MatchedAsVariant`, but is NOT synced.**

A *variant* is another version of the same interaction — same meaning, different phrasing (e.g. `Passeport ?` / `Passeport, s'il vous plaît !` / `Vous avez un passeport ?`). Variants share a very similar answer pool.

**Why the engine needs it:** the story purpose builds distractors by borrowing valid answers from *other* interactions. A variant's answer would be a perfectly **valid** response to the current question — presenting it as WRONG is a correctness bug (a "false-wrong"). Variants must be excluded.

**⚠️ Must be written SYMMETRICALLY.** Each member must list all its siblings. Airtable's `MatchedAsVariant` may only record one direction; an interaction with NULL or partial `variant_ids` excludes nothing.
- *Real incident:* the first manual population was asymmetric — one interaction listed all five siblings, three listed only three, and two were NULL. Story would have borrowed a variant's valid answer and marked it wrong.
- *Code mitigation already in place:* `find_story_distractors` checks both directions (ids the interaction lists, plus any interaction whose `variant_ids` contains it), so imperfect data can't produce false-wrongs. The sync should still write symmetrically.

**Completeness matters pedagogically:** every unflagged near-duplicate is a potential false-wrong. Example: `Vous avez un passeport ?` and `C'est votre passeport ?` had to be added to the passport family because their answers would be valid for `Passeport ?`.

### 1b. `brain_answer.matched_notion_ids text[]` ← NEW in Airtable
**Does not exist in Airtable or Postgres.** Added to Postgres by hand for testing.

Which notions an answer *contains*. Used by the notion purpose to pick VALID answers — an answer qualifies if it contains the cycle's target notion.

### 1c. `brain_notion.mistake_ids text[]` ← NEW in Airtable
**Does not exist in Airtable or Postgres.** Added to Postgres by hand for testing.

Which authored mistakes belong to each notion. A notion is a learning concept, and each notion can be interpreted into several mistakes.

**Why the engine needs it:** notion-purpose WRONG answers are those whose mistakes all belong to the target notion. Without this link there's no way to tell a notion-relevant mistake from an unrelated one.
- `brain_notion` currently has NO mistake link. Columns: `id, name_fr, name_en, description, rank, live, score, level_from, level_owned, airtable_record_id, created_at, update_at, weightiness`.
- The "interaction was selected for the notion, so its mistakes must be about that notion" shortcut does **not** work: an interaction can teach multiple notions (`expected_notion_id` is an array), and an answer can carry mistakes unrelated to any of them.

---

## 2. Fields added to Postgres during the build — confirm they sync

These were added by `ALTER TABLE` as the engine was built. Some were authored in Airtable, some set directly in TablePlus. **All need sync support** or they'll be blank for new content.

### On `brain_vocab`
| Column | Type | What it does |
|---|---|---|
| `pairing_attribute_ids` | `text[]` | **Essential.** The articles/companions the vocab takes (un, le, une, la…). A template's slot requirement is matched against the union of the vocab's OWN `attribute_ids` and this. **Without it, realization returns nothing** — the vocab can't satisfy any template. |
| `commonness` | `real` (default 0.5) | How central/expected the vocab is within its entity (1 = the go-to, 0 = obscure). Ranks realization candidates. |
| `level_from` | `int` | From when the vocab is taught/introduced. |
| `level_own` | `int` | From when it's considered owned (≥ `level_from`). Rescue and realization filter on `level_own ≤ user_level`. |

*Incident:* the frame-mate vocab (clothing/fruit/vegetable) synced from Airtable with **empty** `attribute_ids` and `pairing_attribute_ids`, so no vocab satisfied the `un` requirement and realization returned `[]`. Attributes had to be set by hand in TablePlus.

### On `brain_interaction_answer`
| Column | Type | What it does |
|---|---|---|
| `answer_typicality` | `real` (default 0.5) | How central/typical the answer is within THIS interaction's pool (1 = conventional, 0 = distinctive). Orders distractor and borrow selection. **Not** matching similarity. |
| `never_a_button` | `boolean` (default false) | Hard per-interaction exclusion from button generation. |

### On `session_*` (backend-only — NOT synced, listed so they aren't confused for content)
`session_interaction.answer_mode`, `session_interaction.button_purpose`, `session_cycle.target_notion_id`, `user_behavior.rescue_level`. These are written by the backend at runtime and must never be touched by the sync.

---

## 3. Grammatical attributes (authored in `brain_attribute`)

The engine produces grammatical French with **no GPT and no morphology engine** — purely by matching authored attributes. These must exist and be correctly assigned or realization silently produces nothing.

**Categories in use:**
- **article** — un (`ATTR202411120628`), une (`ATTR202411120227`), le (`ATTR202506230331`), la (`ATTR202506240132`), les, des, l'
- **elision** — voyelle (`ATTR202607281138`), consonne (`ATTR202607281139`)
- **gender** — masculin (`ATTR202607281134`), féminin (`ATTR202607281135`)
- **number** — singulier, pluriel

**Where each goes:**
- **Template answer** (`brain_answer.attribute_ids`) — the article the slot REQUIRES. `J'ai un entityAnimal` carries `un`.
- **Vocab OWN** (`brain_vocab.attribute_ids`) — what the word IS: gender, elision.
- **Vocab PAIRING** (`brain_vocab.pairing_attribute_ids`) — what it GOES WITH: the articles it accepts.

The union-match works because the vocabularies don't collide: article values appear only in pairing lists, elision values only in own lists.

**One template form per grammatical variant** — `J'ai un entityAnimal` and `J'ai une entityAnimal` are separate authored templates. This guarantees correctness by construction rather than computing agreement.

---

## 4. Existing conventions to preserve

- **`update_at`** (missing the 'd') is the established column name across the `brain_*` sync tables. `brain_user` uses the correct `updated_at`. Keep the convention rather than "fixing" it.
- **Airtable lookup fields return arrays** even for single entries — extract the first element where a scalar is expected.
- **camelCase → snake_case mappings must be explicit** in `prepare_entry_data`; a missing mapping fails silently as a NULL.
- **VARCHAR widths** — check before designing wire values (past bug: `language_level`, `native_language` needed widening).
- **PostgreSQL CHECK constraints** must be updated whenever an enum-like list changes.
- **`airtable_record_id` is NOT NULL** on `brain_mistake` (and likely others) — hand-inserted test rows need a placeholder value.
- **`is_button` is RETIRED** as an exclusive flag. Button-eligibility is now contextual and computed; every non-`never_a_button` answer is a candidate. The column still exists but the engine no longer partitions on it.

---

## 5. Type gotcha worth knowing

`brain_interaction_answer.mistake_ids` is `character varying[]` while `brain_notion.mistake_ids` (new) is `text[]`. **`varchar[] <@ text[]` fails at runtime** (`operator does not exist`) — verified empirically; it would have caused a 500. The notion curator therefore does the containment check in Python rather than SQL. If the sync creates new array columns, matching the element type of what they'll be compared against avoids this class of problem.

---

## 6. Test data created directly in TablePlus (to be cleaned up)

Not from Airtable; will be deleted once the sync supports the fields:
- Mistakes `MIST_TEST_QSTYLE1`, `MIST_TEST_QSTYLE2` (type `Grammaire`)
- Answers `ANS_TEST_QS1`, `ANS_TEST_QS2`, `ANS_TEST_NEG` + join rows `BIA_TEST_*`
- `brain_notion.mistake_ids` on `NOT202408091129`; `matched_notion_ids` on `ANS202506191243` / `ANS202506191237`
- `variant_ids` on the six-member passport family
- Attribute/level fixes on the clothing/fruit/vegetable vocab

**Real content authored properly in Airtable** (keep): the `entityAnimal` vocab and templates, the `entityClothing`/`entityFruit`/`entityVegetable` entities, vocab and `J'ai un entity…` templates, and the added `good` answers across the immigration subtopic.

---

## 7. Priority for the sync work

1. **`MatchedAsVariant` → `variant_ids`** — correctness issue for the story purpose, which is LIVE in production today. Highest priority.
2. **`brain_vocab` attributes** (`pairing_attribute_ids` especially) — without these, realization silently produces nothing for new vocab.
3. **`answer_typicality` / `never_a_button`** — quality and control, not correctness.
4. **`brain_notion.mistake_ids` + `brain_answer.matched_notion_ids`** — needed before the notion purpose can run on real content.
