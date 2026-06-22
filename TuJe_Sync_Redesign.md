# TuJe Sync Redesign

**Spec & architecture for the per-lifecycle content/media sync system, plus the Subtopic Analytics Interface for production-readiness analysis.**

*Status: applied to all 6 modernized tables — Interaction, Subtopic, Mistake, Answer, Vocab, Interaction-Answer. Stage 5 complete.*

*Deferred items, open questions, and future cleanup are tracked separately in `TuJe_Deferred_Items.md`.*

---

## 1. Purpose

This document captures the design and rationale for the redesigned sync system between Airtable (content authoring CMS) and PostgreSQL (the `brain_*` tables consumed by the app), plus the analytics Interface built on top of it. It exists to:

- Make the design explicit so future-you (or another Claude session) doesn't have to reverse-engineer it from code.
- Define the recipe for applying this pattern to any future tables.
- Capture principles and patterns that emerged from the work.

For active backlog, deferred decisions, and known gaps, see `TuJe_Deferred_Items.md`.

---

## 2. Context: what existed before

The old system had:

- A single status formula per table mixing content readiness and media readiness.
- A single `LastModifiedSaved` timestamp written back by the backend after sync.
- A single `lastModifiedTimeRef` formula computing the modtime across all fields.

Problems with that design:

- Content and media lifecycles were entangled. Modifying media data triggered "content needs resync" signals, and vice versa.
- "Status" conflated several distinct questions: "is data complete?", "has it been synced?", "is it live?", "is the media uploaded?"
- No archive concept — `Live=No` had to do double duty for "paused" and "retired," which are different things.
- No way to mark test/dev records that don't follow normal completeness rules.

---

## 3. Core design: parallel lifecycles per table

The redesign separates independent sync flows that share a record. The shape varies per table:

- **Interaction**: 2 lifecycles — content + video
- **Subtopic**: 2 lifecycles — content + video (icon derived from video frame, no separate image lifecycle)
- **Mistake**: 1 lifecycle — content only (no media)
- **Answer**: 3 lifecycles — content + audio + image (audio combines AudioNormal + AudioSlow as one operation)
- **Vocab**: 3 lifecycles — same shape as Answer (content + audio + image)
- **Interaction-Answer**: 1 lifecycle — content only (join table with relationship attributes)

Each lifecycle has:
- Its own modtime formula tracking only the fields belonging to that lifecycle
- Its own sync timestamp (`LastXSyncedAt`)
- Its own sub-status formula
- A combined composite `Status` formula bringing them together with lifecycle state (Archived, Test, Live, etc.)

### 3.1 Why separate modtime tracking matters

Each lifecycle's `LAST_MODIFIED_TIME` formula watches only its own fields. Example from Interaction:

```
VideoLastModified = LAST_MODIFIED_TIME({Video})

ContentLastModified = LAST_MODIFIED_TIME(
  TranscriptionFr, TranscriptionEn, Subtopic, Type, ..., 
  VideoUrl, PosterTime
)
```

**Key insight**: when an upload script writes a URL field (e.g., `VideoUrl`), that URL is *content* destined for Postgres — so it belongs to the content lifecycle, not the video lifecycle. Only the source attachment defines the video lifecycle.

### 3.2 Subtopic media: collapsed image into video

Subtopic originally had three planned media types (video, image, audio). Audio was deferred. Image was collapsed into video using Cloudinary's frame extraction:

- Source: `VideoCover` attachment uploaded to Cloudinary as video
- `VideoCoverUrl`: raw Cloudinary URL (already optimized at upload time)
- `PosterUrl`: derived formula extracting a still frame at `PosterTime`
- `IconUrl`: derived formula extracting the same frame as a circular icon (200x200, `r_max`, `f_png`)

One source asset, two derived assets. No separate image upload needed.

### 3.3 Answer media: combined audio + separate image

Answer has two distinct media types:

- **Audio (combined lifecycle)**: `AudioNormal` and `AudioSlow` attachments. Authoring discipline keeps them in sync — when audio is recorded, both versions are produced together. One Cloudinary upload action handles both, writes `AudioNormalUrl` and `AudioSlowUrl`, and writes a single `LastAudioSyncedAt` timestamp.
- **Image lifecycle**: single `Image` attachment, independently authored. Has its own sub-status and timestamp.

The composite Status has 10 states because audio and image needs-resync are surfaced separately (🎵 Audio needs resync, 🖼️ Image needs resync).

### 3.4 Vocab media: same shape as Answer

Vocab uses the identical 3-lifecycle design as Answer. The audio Cloudinary endpoint pattern from Answer (`upload_answer_audio_from_url`) was the model for Vocab's audio endpoint (`upload_vocab_audio_from_url`). Image endpoint also reused (`upload_vocab_image_from_url`).

Vocab introduced the **lenient + ContentStatus + IsTest bypass** design pattern — see Section 6.

### 3.5 Interaction-Answer: join table with relationship attributes

Interaction-Answer connects Interactions to Answers but also carries real relationship data (AnswerType, LevelAnswerRate, multiple relationship arrays). Single content lifecycle, no media. Strict Pydantic on the 4 core fields, lenient on relationship arrays (variants, follow-ups, bonus-malus, feedback, hints, mistakes — any of which can be empty).

---

## 4. The state machine

The composite `Status` formula evaluates conditions in priority order. The first matching condition wins. The shape varies by lifecycle count.

### 4.1 9-state machine (Interaction, Subtopic)

| State | Condition | What to do |
|---|---|---|
| ⚫ Archived | `RecordState = Archived` | Ignore |
| 🧪 Test | `IsTest = TRUE` | Ignore in normal workflow |
| 🟠 Not ready | Any sub-status is 🟠 | Fill missing required fields |
| 🆕 Ready for first sync | Content/Video are 🟣 New (never synced) | Click Sync Content and/or Upload Video |
| 🟢 Live | Both sub-statuses 🟢, `Live = Yes` | Done — serving to users |
| ⏸️ Ready, paused | Both sub-statuses 🟢, `Live = No` | Decide whether to flip Live to Yes |
| 🔵 Content needs resync | `ContentStatus = 🔵 Update` | Click Sync Content |
| 🎥 Video needs resync | `VideoStatus = 🔵 Update`, `ContentStatus = 🟢` | Re-upload video to Cloudinary |
| 🟡 In progress | Anything else | Keep authoring |

### 4.2 7-state machine (Mistake, Interaction-Answer — no media)

| State | Condition | What to do |
|---|---|---|
| ⚫ Archived | `RecordState = Archived` | Ignore |
| 🟠 Not ready | `ContentStatus = 🟠` | Fill missing required fields |
| 🟢 Live | `ContentStatus = 🟢 Done`, `Live = Yes` | Done — serving to users |
| ⏸️ Ready, paused | `ContentStatus = 🟢 Done`, `Live = No` | Decide whether to flip Live to Yes |
| 🆕 Ready for first sync | `ContentStatus = 🟣 New` | Click Sync Content |
| 🔵 Content needs resync | `ContentStatus = 🔵 Update` | Click Sync Content |
| 🟡 In progress | Anything else | Keep authoring |

No 🧪 Test, no media-needs-resync states.

### 4.3 10-state machine (Answer, Vocab — 3 lifecycles)

| State | Condition | What to do |
|---|---|---|
| ⚫ Archived | `RecordState = Archived` | Ignore |
| 🧪 Test | `IsTest = TRUE` | Ignore in normal workflow |
| 🟠 Not ready | Any sub-status is 🟠 | Fill missing required fields |
| 🟢 Live | All 3 sub-statuses 🟢, `Live = Yes` | Done — serving to users |
| ⏸️ Ready, paused | All 3 sub-statuses 🟢, `Live = No` | Decide whether to flip Live to Yes |
| 🆕 Ready for first sync | Any sub-status is 🟣 New, none Update or Not ready | Click Sync buttons |
| 🔵 Content needs resync | `ContentStatus = 🔵 Update` | Click Sync Content |
| 🎵 Audio needs resync | `AudioStatus = 🔵 Update`, content done | Re-upload audio to Cloudinary |
| 🖼️ Image needs resync | `ImageStatus = 🔵 Update`, content done | Re-upload image to Cloudinary |
| 🟡 In progress | Anything else | Keep authoring |

Resync priority: Content first, then Audio, then Image. If multiple lifecycles drift simultaneously, the highest priority signal shows first.

### 4.4 Priority rationale

- **Archived** overrides everything.
- **Test** (when present) overrides operational signals — test records have different completeness rules.
- **Not Ready** surfaces blocking data gaps before showing positive signals.
- **Live** distinguishes "served to users" from "complete but paused."
- **Resync states** surface drift after a successful sync.
- **In Progress** catches everything else.

---

## 5. The archive concept

`RecordState` is a single-select with three values: **Active** (default), **Retired**, **Archived**.

- **Active**: in normal use. `Live=Yes` means serving; `Live=No` means temporarily paused.
- **Retired**: pulled from active rotation but kept for reference. Reversible.
- **Archived**: terminal soft-delete. Filtered out of app queries via `brain_*.archived` column. Still reversible if needed.

Archive is achieved by changing `RecordState` to Archived in Airtable, then syncing. The backend stores this as a boolean `archived` column on each `brain_*` table.

### Cross-table archive policy

- Records are independent entities — archiving an Answer does **not** block any Interaction that references it, and vice versa.
- Orphans are allowed. The app filters `archived=true` rows at the query layer.

### Wired across all 6 modernized tables

System-wide wiring applied:
- `archived: Optional[bool] = False` added to all Entry Pydantic models
- `"archived"` added to all SYNC_CONFIGS columns lists immediately after `"live"`
- All sync scripts compute `archived = (RecordState.name === "Archived")` and send it in the payload
- Airtable RecordState is source of truth; each sync overwrites the column based on current RecordState

**Note**: app-side queries need to filter on `archived = false` to actually exclude archived records from user-facing results. This is iOS work (see deferred items doc).

---

## 6. Backend architecture (airtable_routes.py)

### Per-lifecycle timestamp config

Each table's `SYNC_CONFIGS` entry declares its own timestamp behavior:

```python
"interaction": {
    "table_name": "brain_interaction",
    "airtable_table": "Interaction",
    "timestamp_field": "LastContentSyncedAt",
    "use_now_timestamp": True,
    "columns": [...]
}
```

`background_airtable_update` accepts a configurable `timestamp_field` parameter (default `LastModifiedSaved` for backward compat with the 11 non-modernized tables).

`generic_sync_webhook` reads the config and branches: if `use_now_timestamp`, write `int(time.time() * 1000)`; else use the payload's `lastModifiedTimeRef` (or fallback to server time if not provided).

### Validator philosophy varies by table

Three resolution strategies for "what does 'required' mean":

- **Strict Pydantic** (Mistake, Answer key fields, Interaction-Answer core): backend rejects partial payloads. Use when missing data means broken records.
- **Lenient Pydantic + ContentStatus** (Subtopic, Interaction): backend accepts partials, Airtable formula prevents reaching Done. Use when missing data means degraded but functional.
- **Lenient Pydantic + ContentStatus + IsTest bypass** (Vocab): same as above plus escape hatch for partial test records. Use when strict authoring discipline matters but flexibility is needed during heavy authoring.

The IsTest-bypass design is the recommended pattern for tables with many required fields plus media.

---

## 7. Daily workflow

### Authoring a new record

1. Fill required content fields (specifics vary by table).
2. Link related records.
3. Attach media file(s) (for media-bearing tables).
4. Set `PosterTime` (where applicable).
5. Click media-specific upload button → URL written, status → 🟢 Done.
6. Click "Sync Content" → ContentStatus → 🟢 Done.
7. Set `Live = Yes` when ready → `Status` → 🟢 Live.

### Modifying an existing record

- Edit any content field → `ContentStatus` → 🔵 Update → click Sync Content.
- Replace media attachment → media sub-status → 🔵 Update → click media upload, then Sync Content (because the URL changes).

### Archiving

1. Change `RecordState` to Archived.
2. Set `Live = No`.
3. Click Sync Content — pushes both changes to Postgres. App stops serving the record.

---

## 8. Stage 5 Recipe

A general guide for modernizing any `brain_*` table. Each table requires the same shape of work, with table-specific design decisions at each stage. This recipe is now battle-tested across 6 tables.

### Pre-work (before any edits)

1. **Discovery**: Read the current Pydantic model, SYNC_CONFIGS entry, Airtable field list, and existing sync scripts. Document what's there.
2. Identify what fields the app actually consumes vs. what's authoring-only.
3. Identify field type drift (numeric where integer should be, etc.).
4. Identify stale validators (Optional fields with strict validators).
5. **Run a full-repo grep for any column name you intend to rename.** Tabulate every reader file. iOS check is necessary but NOT sufficient — backend modules also read the columns and will silently break on rename. (See "Lessons learned" in deferred items doc.)

### Design decisions per table

1. **Media lifecycles**: How many distinct media types? Each gets its own sub-status, sync timestamp, and modtime formula. Decide whether multi-asset media is one combined lifecycle or independent — based on whether the assets always update together.
2. **Field strictness — three options**:
   - **Strict Pydantic + no IsTest**: backend rejects partial payloads.
   - **Lenient Pydantic + ContentStatus formula gates**: backend accepts partials, Airtable formula prevents reaching 🟢 Done.
   - **Lenient Pydantic + ContentStatus formula + IsTest bypass**: backend accepts partials, formula enforces unless IsTest=true.
3. **IsTest**: Needed for this table? Yes if media-bypass is useful and the table has heavy required fields.
4. **Cleanup scope**: Which existing fields are dead? Renames needed?
5. **`archived` strategy**: Now wired system-wide via Pydantic Optional[bool] = False, included in SYNC_CONFIGS columns, scripts compute from RecordState.

### Stage 0: Cleanup

- Drop dead fields after consumer audit.
- Rename for consistency (cross-table naming patterns: lookups like `XxxIds`, link fields without spaces).

### Stage 1: Add new fields

- `RecordState` (always)
- `IsTest` (when media exists, and especially when strictness includes media)
- One `LastXSyncedAt` per lifecycle
- One `XLastModified` formula per lifecycle

### Stage 2: Status formulas

- One sub-status per lifecycle (`ContentStatus`, `AudioStatus`, etc.)
- Composite `Status` combining all sub-statuses with priority order. State count: 7 for media-less, 9 for 2 lifecycles, 10 for 3 lifecycles.
- If using ContentStatus + IsTest design: wrap required-field checks in `AND(IsTest = FALSE(), ...)` so IsTest bypasses strictness.

### Stage 3: Backend wiring

- Add `timestamp_field` + `use_now_timestamp` to `SYNC_CONFIGS`.
- Fix stale validators (relax or tighten per table decisions).
- Update `field_mappings` and column lists for any new fields.
- Add array handling for any new list fields in `sync_entity_to_database`.
- Add `archived: Optional[bool] = False` to the Pydantic model and `"archived"` to SYNC_CONFIGS columns.

### Stage 4: Script updates

- Update content sync script.
- Add or update per-lifecycle media sync scripts. Each writes the URL field AND the corresponding `LastXSyncedAt`.
- Add pre-flight required-fields check if strictness is desired in scripts. Honor IsTest if applicable.
- Apply DEBUG_MODE pattern for clean console output.
- Add `archived = RecordState.name === "Archived"` to all scripts.

### Stage 5: Test

- End-to-end sync verification per lifecycle.
- TablePlus query to verify column values.
- Status transitions through expected states.

### Path A / Path B split for complex tables

When a table requires new backend infrastructure (e.g., a new Cloudinary endpoint that doesn't exist yet), split into Path A (Airtable structure: Stages 0-2) and Path B (backend + endpoints + scripts: Stages 3-5). Path A is a safe checkpoint — existing sync still works on old fields; new fields are just dormant until Path B builds the bridge. Used successfully on Answer (audio endpoint built in A2) and Vocab (both audio + image endpoints built in Path B).

---

## 9. Stage 5 Progress

### ✅ Interaction (June 12, 2026 — original blueprint)
Full two-lifecycle (content + video). 11 dead fields removed. RecordState/IsTest added. ContentLastModified, VideoLastModified formulas. ContentStatus, VideoStatus, composite Status formulas. Backend `timestamp_field` config. Cloudinary script writes `LastVideoSyncedAt`. `archived` wiring added June 19. `entry_point` + `entry_point_type` wired into sync June 20.

### ✅ Subtopic (June 18, 2026)
Full two-lifecycle (content + video). Image collapsed into video via Cloudinary frame extraction.

### ✅ Mistake (June 18, 2026)
Single content lifecycle, no media. Strict Pydantic alignment with ContentStatus.

### ✅ Answer (Path A1 + A2, June 18-19, 2026)
Three lifecycles — content + audio (combined AudioNormal + AudioSlow) + image. Audio Cloudinary endpoint built from scratch.

### ✅ Vocab (Path A1 + B, June 19, 2026)
Three lifecycles. Most complex modernization. Introduced the lenient + IsTest bypass design pattern. 11 new Postgres columns. New file `upload_vocab_media.py`.

### ✅ Interaction-Answer (June 20, 2026)
Single content lifecycle, no media. Join table with relationship attributes (AnswerType, LevelAnswerRate) and multiple link arrays. Strict Pydantic on core fields, lenient on relationship arrays. `list_of_mistakes` renamed to `mistake_ids` in coordinated rename.

---

## 10. Principles

These principles emerged through the work and should guide future changes:

- **Lifecycles are independent.** Mixing content drift with media drift hides which thing actually changed.

- **Computed status beats manual status.** Each state should be derivable from underlying data, except where human judgment is required (`Live`, `RecordState`, `IsTest`).

- **Defer infrastructure for decisions you haven't made.** Empty placeholder fields are worse than no fields — they imply a design that doesn't exist yet.

- **Discovery before edits.** Always read actual current state of code/schema/Airtable before changing it. Memory drifts; reality doesn't.

- **Discovery before renames must be repo-wide.** A column rename in Postgres is safe only after every reader (SQL queries, Record key accesses, dict lookups) across the entire codebase has been catalogued. iOS check alone is insufficient — backend modules also read these columns.

- **Two layers of "required" — three resolution strategies.** Strict Pydantic = early failure. Lenient Pydantic + Airtable formula = partial records permitted in DB. Lenient + IsTest bypass = escape hatch for partial test records.

- **Archive instead of delete.** Soft-delete preserves history and is reversible.

- **Single source of truth via rollups, not duplicated logic.** Compute readiness flags once on the source table, reference them everywhere downstream.

- **Audit consumers before removal.** Before deleting or renaming any field, search: Airtable sync scripts, backend (Pydantic + SYNC_CONFIGS + columns lists + SQL queries in every .py file), Postgres schema, other Airtable scripts, and iOS code.

- **Combined-lifecycle decisions.** When multiple media assets always update together, treat them as one lifecycle with one sync action. When they're independently authored, separate lifecycles. Signal: "would I ever want to update only one of them?"

- **Path A / Path B split for complex tables.** When new backend infrastructure is needed alongside Airtable structure work, split into safe checkpoints. Path A (Airtable only) doesn't break existing sync; Path B (backend + endpoints + scripts) bridges the new structure.

---

## 11. Subtopic Analytics Interface

An Airtable Interface page named **Subtopic Analytics** provides visual readiness analysis on the Subtopic table.

### 11.1 Helper formulas on Interaction

Six formulas compute derived flags used throughout the analytics layer:

- `IsReady` — content-complete (Status indicates 🟢 Live, ⏸️ Ready paused, or 🆕 Ready for first sync)
- `AnswerCount` — number of linked answers via comma-counting workaround (`LEN({MatchedAnswer} & "") - LEN(SUBSTITUTE({MatchedAnswer} & "", ",", "")) + 1`); Airtable's COUNTA returns 1 on link fields regardless of count
- `IsUsable` — 1 if `IsReady = 1 AND AnswerCount >= 2`; else 0 (production-ready)
- `IsCounted` — 1 if `RecordState = 'Active' AND IsTest = FALSE`; else 0 (counts in real metrics)
- `LevelBucket` — 50-wide level band as padded string (`000-049`, `050-099`, ... `400+`), or blank if level unset
- `UsableLevel` — `InteractionOptimumLevel` if `IsUsable = 1`, else blank (for Min/Max rollups that should ignore non-usable interactions)

### 11.2 Rollups on Subtopic

| Rollup | Source field | Aggregation | What it shows |
|---|---|---|---|
| `TotalInteractions` | `IsCounted` | `SUM(values)` | Real interactions in this subtopic (excludes archived/test) |
| `UsableInteractions` | `IsUsable` | `SUM(values)` | Production-ready interactions |
| `UsablePercentage` | `IsUsable` | `IF(COUNTA(values) = 0, 0, SUM(values) / COUNTA(values))` (formatted as %) | Share that are usable |
| `MinUsableLevel` | `UsableLevel` | `MIN(values)` | Lowest level with usable content |
| `MaxUsableLevel` | `UsableLevel` | `MAX(values)` | Highest level with usable content |

**Note on UsablePercentage**: the formula returns a fraction (e.g., `0.08`) and Airtable's Percent field format displays it as `8%`. Do NOT include `* 100` in the rollup formula if the field format is Percent — it would double-multiply.

### 11.3 Interface zones

**Zone 2 — Selected subtopic detail (built)**

- Record picker: source = Subtopic, inline filter `TotalInteractions > 0`. Drives all downstream elements.
- Five direct-field tiles (added via "add field from picked record"): `TotalInteractions`, `UsableInteractions`, `UsablePercentage`, `MinUsableLevel`, `MaxUsableLevel`. Read the rollups directly rather than aggregating from links — keeps logic in one place.
- Stacked histogram: bar chart of `LevelBucket` (X axis) × count of Interactions (Y axis), filter `IsCounted = 1`, stacked by `IsUsable`.

**Zone 3 — Interaction drill-down (built)**

- Grid element: source = Subtopic picker → Interaction, filter `IsCounted = 1`, sort by `InteractionOptimumLevel` ascending.
- Visible fields: `ID`, `TranscriptionFr`, `InteractionOptimumLevel`, `Status`, `AnswerCount`, `IsUsable`.

**Zone 1 — All-subtopics overview (deferred)**

Subtopic table grid view + picker dropdown order serve the same purpose. Build only if usage reveals an actual need.

### 11.4 Build notes

- **The Number element's "Source" picker traverses to a related table.** It does NOT display a field on the picked record directly. For that, use the alternate "add field from picked record" flow.
- **Number element's Field Summary mode only offers blank-counting aggregations** (Empty, Filled, Percent Filled, etc.). No Sum/Min/Max/Average. For those, use rollups and display via direct-field tiles.
- **Padded bucket labels** (`000-049` not `0-49`) ensure correct sort order in chart category axes that sort alphabetically.

---

## 12. Schema-wide cleanup history

### NUMERIC → INTEGER cleanup (June 18, 2026)
17 columns across 8 tables converted from NUMERIC to INTEGER. `brain_answer.timer_seconds` later reverted to NUMERIC after spec clarification.

### `archived` system-wide wiring (June 19, 2026)
All 6 modernized tables wired (Pydantic + SYNC_CONFIGS + scripts).

### Vocab Path B migration (June 19, 2026)
11 new columns added to brain_vocab.

### Interaction-Answer modernization (June 20, 2026)
Renamed `list_of_mistakes` → `mistake_ids`. Added 7 new columns including `level_answer_rate`, 5 relationship arrays, and `archived`.

### `lastModifiedTimeRef` full deprecation (June 20, 2026)
BaseEntry now Optional, removed from all 17 SYNC_CONFIGS columns lists, all 17 brain_* Postgres columns dropped. Airtable script + formula cleanup done on the 6 modernized tables. The 11 non-modernized tables keep sending it; backend ignores via Optional + server-time fallback.

### `entry_point` + `entry_point_type` wiring (June 20, 2026)
Added `entry_point_type` (TEXT) to brain_interaction. Wired both `entry_point` (boolean) and `entry_point_type` (text) into the modernized Interaction sync. Airtable single-select drives both via script-side derivation: `entry_point = (type === "First")`, `entry_point_type = verbatim option name`. Both fields are now sync-owned.

---

## 13. Notable workflow patterns

### Pre-flight required-fields check

Scripts for tables with strict Pydantic models should validate required fields *before* the network round-trip. Surfaces "missing fields" errors immediately with clear field names.

For tables using Vocab's design (lenient + ContentStatus + IsTest), the pre-flight check should also honor IsTest:

```javascript
let isTest = record.getCellValue("IsTest") || false;

if (!isTest) {
    const missing = Object.entries(requiredFields)
      .filter(([_, v]) => {
        if (v === null || v === undefined) return true;
        if (typeof v === "string" && v.trim() === "") return true;
        if (Array.isArray(v) && v.length === 0) return true;
        return false;
      })
      .map(([k]) => k);

    if (missing.length > 0) {
      output.markdown("**Cannot sync!** Missing required fields:\n\n" + missing.join(", ") + "\n\nOr check IsTest to bypass.");
      return;
    }
}
```

### DEBUG_MODE flag pattern

All modern sync scripts use `const DEBUG_MODE = false` at the top, with verbose pre-flight logs wrapped in `if (DEBUG_MODE)`. Default output stays clean. Flip to `true` for debugging.

### Media upload script writes URL + timestamp

Cloudinary upload scripts write back BOTH the URL field AND the corresponding `LastXSyncedAt` timestamp in the same `updateRecordAsync` call:

```javascript
await table.updateRecordAsync(record.id, {
    "ImageUrl": data.cloudinary_url,
    "LastImageSyncedAt": Date.now()
});
```

Without writing the timestamp, the sub-status formula stays at 🟣 New forever even after successful upload.

### `archived` from RecordState in every script

```javascript
let recordState = record.getCellValue("RecordState");
let archived = recordState ? (recordState.name === "Archived") : false;
// then in payload:
archived: archived
```

Airtable RecordState is source of truth.

### Camel-case payload to snake-case columns

Airtable scripts send camelCase keys (`userGoalIds`). Backend's `prepare_entry_data` maps camelCase → snake_case (`user_goal_ids`). The `field_mappings` dict must include each transformation explicitly; missing entries cause silent NULL writes for the affected column.

### iOS code search before renames

Before any column rename, run Claude Code grep against `~/Desktop/TuJe` for the column name in all relevant spellings. **But also run repo-wide grep across .py files** — the iOS-only check is necessary but not sufficient.

### Multi-select field reading

Multi-select fields in Airtable return arrays of option objects. To extract option names for sending to Postgres TEXT[]:

```javascript
let genderField = record.getCellValue("Gender") || [];
let gender = Array.isArray(genderField) ? genderField.map(opt => opt.name) : [];
```

### Single-select to multiple-target fields (entry_point pattern)

When an Airtable single-select drives multiple Postgres columns (e.g., the EntryPoint 4-state field drives both `entry_point` boolean and `entry_point_type` text), the script derives all target values:

```javascript
let entryPointField = record.getCellValue("EntryPoint");
let entryPointType = entryPointField ? entryPointField.name : null;
let entryPoint = entryPointType === "First";
// both go in payload
```

Source of truth = Airtable. Backend stores both verbatim. No backend derivation needed.

### Audio attachments to Cloudinary script (multi-file pattern)

Scripts that upload multiple audio files in one operation send all file URLs in a single POST, then write back all returned URLs + a single timestamp.

---

*Active backlog: see TuJe_Deferred_Items.md*
