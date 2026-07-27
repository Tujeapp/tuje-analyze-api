# TuJe — `brain_hint` Schema Spec (v2, for build)

**Status: schema locked, ready to build in TablePlus + Airtable. The old `brain_hint` (proficiency-range concept: level_from/level_to/value) is discarded — it had no real content. This replaces it entirely.**

This schema supports the full two-button hint model (see `TuJe_Hint_System_Design_Spec.md`). The first feature slice (Understand-L1) uses only a subset, but the schema is built complete so it's authored once and stable.

---

## Design principles baked into this schema

1. **No hardcoded enum values in code.** `button`, `usage`, `type`, `media_kind` are plain author-managed text. Their *values* live in Airtable and can be extended anytime. Code filters by what a request asks for and by the structural fields (`hint_level`, `live`); it must NOT hardcode allowed values like `WHERE type = 'contextual'`.

2. **Malus is a link, not a value.** The score cost lives in a separate `brain_bonus_malus` table (the next feature). `brain_hint` only carries `bonus_malus_id`. Nullable and unused until bonus-malus is built.

3. **One hint = one (button, hint_level) slot.** Discrete slots; reuse via authoring, not multi-slotting.

---

## `brain_hint` columns

| Column | Type | Null? | Notes |
|---|---|---|---|
| `id` | text | no | PK (e.g. `HINT2025...`) |
| `airtable_record_id` | text | yes | Airtable sync |
| `name` | text | yes | Author-facing label (e.g. "cinema-context-L1") |
| `button` | text | yes | Which button serves it: `understand` / `answer` (author-managed; not code-enforced) |
| `hint_level` | integer | yes | Escalation level 1 / 2 / 3 (structural — press count) |
| `usage` | text | yes | Author-managed usage axis (understand_interaction / formulate_first_answer / answer_no_match / improve_matched_answer) |
| `type` | text | yes | Author-managed type axis (contextual / conjugation / …) |
| `media_kind` | text | yes | Author-managed: text / audio / image / gif / video |
| `text_en` | text | yes | English content (e.g. L1 contextual explanation) |
| `text_fr` | text | yes | French content where relevant |
| `text_phonetic` | text | yes | French phonetic (e.g. Answer-L3 options) |
| `media_url` | text | yes | Cloudinary URL for audio/image/gif/video hints |
| `applies_to_tier` | integer | yes | Which answer-tier this hint serves (1/2/3), null = tier-independent |
| `bonus_malus_id` | text | yes | Link → `brain_bonus_malus` (score cost). **Nullable, unused until bonus-malus is built.** |
| `live` | boolean | no | Sync/active flag |
| `created_at` | timestamp | no | |
| `update_at` | timestamp | no | Note: intentionally `update_at` (typo preserved across brain_* sync tables) |

---

## Attachment — how hints link to their source (on OTHER tables)

Hints don't reference their interaction from `brain_hint`; the source tables carry hint-id arrays:

| Table | Column | Serves |
|---|---|---|
| `brain_interaction` | `hint_ids` (exists) | Understand hints (all levels); generic + Tier-3 Answer hints |
| `brain_interaction_answer` | `hint_ids` (exists) | Tier-1 Answer hints (matched-answer-specific) |
| `brain_attribute_mistake` | **needs `hint_ids` added (LATER)** | Tier-2 Answer hints (attribute-mismatch-specific) |

The `brain_attribute_mistake` hint link is NOT needed for Slice 1 (Understand-L1). Add it when building the Answer button's Tier-2 path.

---

## Airtable sync additions required

Per the established pattern for adding brain_* fields, each new column needs:
1. TypeScript body update (sync script)
2. Pydantic model update
3. `SYNC_CONFIGS` columns list
4. `field_mappings` in `prepare_entry_data`

Array/link fields (like `bonus_malus_id` if it becomes a link array) follow the Airtable-returns-arrays pattern (extract first element for single links).

---

## Slice 1 subset (Understand-L1)

The first build only needs these fields populated on one test hint:
- `button = understand`
- `hint_level = 1`
- `type = contextual` (author value)
- `media_kind = text`
- `text_en` = the contextual English explanation
- `live = true`
- linked via the test interaction's `brain_interaction.hint_ids`

Slice 1's endpoint filters structurally: given an interaction id, `button=understand`, `hint_level=1` → return the matching live hint from that interaction's `hint_ids`. It does NOT hardcode `type`/`usage` values.

---

## Build order

1. Recreate `brain_hint` in TablePlus with the columns above (drop the old one — no real content).
2. Add the fields in Airtable + wire the sync (TS body → Pydantic → SYNC_CONFIGS → field_mappings).
3. Author ONE Understand-L1 hint for a test voice interaction; add its id to that interaction's `hint_ids`.
4. Build Slice 1 backend endpoint (serve) — small, against these real columns.
5. Build Slice 1 client (Understand button, enable-after-listen, fetch, pin text top, cooldown, level counter, usage record).
6. Test end to end.

Defer: `brain_attribute_mistake.hint_ids`, all higher levels, both L3 flows, the Answer button, the malus math (needs `brain_bonus_malus`).
