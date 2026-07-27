# TuJe — Airtable Sync To-Do (from the hint system build)

Everything below was created **directly in TablePlus** during the hint build. The app works against it today, but **Airtable doesn't know these fields exist**, so authored content won't sync until each is wired.

For every new column, the established four-step pattern applies:
1. TypeScript sync body update
2. Pydantic model
3. `SYNC_CONFIGS` columns list
4. `field_mappings` in `prepare_entry_data`

Reminder: Airtable lookup/link fields always return **arrays**, even for a single linked record — extract the first element where a scalar is expected.

---

## 1. `brain_hint` — rebuild the table (biggest item)

The old table (`level_from`, `level_to`, `value` — a proficiency-range concept) was **dropped**; it had no real content. The new schema is unrelated to it, so this is a rebuild in Airtable, not a migration.

| Column | Type | Notes |
|---|---|---|
| `id` | text | PK |
| `airtable_record_id` | text | |
| `name` | text | author-facing label, e.g. `cinema-context-L1` |
| `button` | text | `understand` / `answer` |
| `hint_level` | integer | 1 / 2 / 3 |
| `usage` | text | ⚠️ **SQL keyword** — quote as `"usage"` in the sync's INSERT/UPDATE |
| `type` | text | e.g. `contextual`, `conjugation` |
| `media_kind` | text | `text` / `audio` / `vocab_flow` / `image` / `gif` / `video` |
| `text_en` | text | |
| `text_fr` | text | |
| `text_phonetic` | text | |
| `media_url` | text | Cloudinary |
| `applies_to_tier` | integer | 1 / 2 / 3, nullable |
| `bonus_malus_id` | text | link → future `brain_bonus_malus`; **nullable, unused for now** |
| `live` | boolean | |
| `created_at`, `update_at` | timestamp | note the `update_at` typo is intentional, matching the other sync tables |

**No `last_modified_time_ref`** — the sibling `brain_*` tables don't use it.

**Values are author-managed.** `button`, `usage`, `type`, and `media_kind` are plain text whose allowed values live in Airtable. The backend never hardcodes them — it filters structurally on `button` + `hint_level` + `live` only. So new `type` or `usage` values can be introduced without a code change.

### Test rows currently in Postgres
These were inserted by hand and are **not** in Airtable. Either recreate them there or delete them once real content is authored:
- `HINT_TEST_UNDERSTAND_L3_C`, `HINT_TEST_UNDERSTAND_L1_C`, `HINT_TEST_UNDERSTAND_L2_C`
- `HINT_1224_L1`, `HINT_1224_L2`, `HINT_1224_ANSWER_L1`
- plus any earlier `HINT_TEST_UNDERSTAND_L1_B` / `_L2_B` still present

---

## 2. New columns on existing tables

| Table | Column | Type | Purpose |
|---|---|---|---|
| `brain_interaction` | `simplified_audio_url` | text | Understand-L2 — the slowed/simplified audio (Cloudinary). Lives on the interaction, **not** on the hint; the hint is only the trigger to fetch it. |
| `brain_interaction` | `transcription_phonetic` | text | Understand-L3 — the phonetic line in the final FR/phonetic/EN reveal |
| `brain_attribute_mistake` | `hint_ids` | text[] | Tier-2 Answer hints — links to `brain_hint` |
| `brain_answer` | `transcription_phonetic` | text | Answer-L3 — phonetic shown under each French option |

`brain_answer.audio_normal_url` and `audio_slow_url` already existed and are now **used by Answer-L3's listen buttons**, so they matter more than before. Currently sparse — e.g. `ANS202506191243` ("Voilà") has none, so its listen button is silent.

---

## 3. Ordering — `brain_interaction.interaction_vocab_id`

**No schema change**, but this field is now load-bearing and worth protecting.

Understand-L3 plays the interaction's vocab blocks **in the order they're linked in Airtable**. Order must survive three hops: Airtable's linked-record order → the sync's array construction → the app reading the array.

**The rule for the sync:** write `interaction_vocab_id` preserving the exact order the Airtable API returned. No sorting, no set operations, no dedup that reorders. Postgres arrays are ordered, so as long as the sync appends in Airtable's order it holds.

(The app side is already safe — the serve endpoint explicitly re-orders in Python, because `WHERE id = ANY(...)` does not preserve array order.)

**Post-sync verification** — run this after authoring blocks and read it top to bottom:
```sql
SELECT array_position(i.interaction_vocab_id, v.id) AS block_order, v.transcription_fr
FROM brain_interaction i
JOIN brain_vocab v ON v.id = ANY(i.interaction_vocab_id)
WHERE i.id = 'INT...'
ORDER BY block_order;
```
If that reads out of order, the sync broke it — not the app.

A test sync during the build **did** preserve order correctly, so the current implementation looks sound.

---

## 4. Do NOT sync

`session_interaction.not_understood_vocab_ids` (text[]) was added for the Understand-L3 recording. It is **behavioural/session data and must never sync to Airtable**, per the standing rule.

---

## 5. Later (not yet built)

- **`brain_bonus_malus`** — the table holding actual score costs. `brain_hint.bonus_malus_id` already exists as a nullable link waiting for it. Until then the malus is unimplemented and nothing about hint usage is recorded.

---

## 6. Content gaps worth filling while you're in Airtable

- **Answer audio is sparse.** `brain_answer.audio_normal_url` / `audio_slow_url` drive Answer-L3's listen buttons, which are deliberately shown-but-inert when missing.
- **Interactions need ~6 answers each** for the L2/L3 option composition (1 perfect, 3 good, 1 false good, 1 wrong) to work as designed. Test interactions currently have 2, so the panel shows 2 and the "can't spot the perfect answer" property is weak.
- **Phonetics** are newly authorable on both `brain_interaction` and `brain_answer`.
