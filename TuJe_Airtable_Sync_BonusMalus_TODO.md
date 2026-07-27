# TuJe — Airtable Sync To-Do: Bonus-Malus

Everything below was created **directly in TablePlus** during the bonus-malus build. The engine works against it today, but **Airtable doesn't know these fields exist**, so authored rules won't sync until wired.

Standard four-step pattern for each new column:
1. TypeScript sync body update
2. Pydantic model
3. `SYNC_CONFIGS` columns list
4. `field_mappings` in `prepare_entry_data`

Reminder: Airtable lookup/link fields return **arrays** even for a single entry — extract the first element for scalars.

---

## 1. `brain_bonus_malus` — wire the whole table for sync

The table exists in Postgres and predates this work, but several columns are what make a rule *mean* something and must all sync. Confirm each is in the sync config:

| Column | Type | Notes |
|---|---|---|
| `id` | text | PK |
| `name_fr`, `name_en` | text | |
| `description` | text | author notes |
| `value` | int | points magnitude |
| `bonus_malus_type` | varchar(20) | **CHECK: must be exactly `bonus` or `malus`.** Casing/typos matter — the engine treats anything that isn't exactly `"malus"` as a bonus, so a mistyped malus silently becomes a bonus. Consider an Airtable single-select (not free text) to prevent this. |
| `rule_code` | varchar(50) | names the metric family; must match a backend handler to fire. Free text, but effectively a controlled vocabulary — a single-select in Airtable would prevent typos that silently disable a rule. |
| `conditions` | jsonb | ⚠️ **see the jsonb note below** |
| `scope` | varchar(20) | **NEW this build.** CHECK: `interaction` / `cycle` / `session`. Default `interaction`. Single-select in Airtable. |
| `priority` | int | default 100 |
| `level_from`, `level_to` | int | nullable (null = unbounded) |
| `live` | bool | |
| `created_at`, `update_at` | timestamp | note the intentional `update_at` typo, consistent with sibling sync tables |
| `airtable_record_id` | text | |

### The `conditions` jsonb — the one tricky field
`conditions` is a **jsonb** column. Two things to get right in the sync:

1. **Authoring in Airtable:** Airtable has no JSON type, so this will be a **long-text field holding raw JSON** (e.g. `{"free_threshold": 2, "per_extra": true}`). The author types valid JSON. Consider documenting the allowed keys per `rule_code` somewhere in the base so authors don't guess.
2. **Writing to Postgres:** the sync must insert it as valid jsonb. If the sync passes the text through, cast/validate it (`::jsonb`) so a malformed payload fails at sync time (loud) rather than at scoring time (where the engine now tolerates it but the rule silently won't work as intended). Malformed JSON should be caught here.

The engine already tolerates `conditions` arriving as a string at read time (asyncpg jsonb quirk), so the *read* side is safe — but authoring valid JSON is on the sync/author.

### Controlled-vocabulary fields worth locking down in Airtable
Because these silently change behaviour when mistyped, prefer **single-selects** over free text:
- `bonus_malus_type` → `bonus` / `malus`
- `scope` → `interaction` / `cycle` / `session`
- `rule_code` → the known handler names (currently `ATTEMPT_COUNT`, `LISTEN_COUNT`; grows as handlers are added)

---

## 2. New column on `session_interaction` — DO NOT SYNC

`session_interaction.listen_count int DEFAULT 0` was added this build. Like all `session_*` behavioural data, it is **backend-only and must never sync to Airtable.**

It also has a **client prerequisite** (not an Airtable item, but related): the app must start *persisting* the listen count to this column (it currently only tracks `videoPlayCount` client-side). Until that happens, `LISTEN_COUNT` rules evaluate against 0.

---

## 3. Seed rules already in Postgres (not in Airtable)

Two rules were inserted by hand for testing. Recreate them in Airtable (so they sync properly) or leave as-is:
- `BM_ATTEMPT_EXTRA` — ATTEMPT_COUNT, malus 5, `{"free_threshold":1,"per_extra":true}`, interaction
- `BM_LISTEN_EXTRA` — LISTEN_COUNT, malus 5, `{"free_threshold":2,"per_extra":true}`, interaction

---

## 4. Pre-existing rule to resolve (not a sync item, but decide it)

The engine surfaced a live row `rule_code = "rule_BOMA202410021017"` already in the table, with no matching handler. Decide whether to give it a handler + proper `rule_code`, or set `live = false`. If it originated in Airtable, whatever you decide should be made there so the sync doesn't reintroduce it.

---

## 5. Cross-reference: `brain_hint.bonus_malus_id`

From the hint build, `brain_hint` has a nullable `bonus_malus_id` link to this table — currently unused. When you author a hint-usage malus, that link is how a hint carries its cost. It's already in the hint schema; just noting the connection so the two tables are wired consistently in Airtable (a link field from `brain_hint` → `brain_bonus_malus`).
