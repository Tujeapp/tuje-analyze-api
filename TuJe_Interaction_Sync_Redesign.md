# TuJe Interaction Sync Redesign

**Spec & architecture for the two-lifecycle content/video sync system, plus the Subtopic Analytics Interface for production-readiness analysis.**

*Status: implemented and validated on the Interaction table. Recipe template for other media-using tables (Vocab, Subtopic, Answer, Mistake).*

---

## 1. Purpose

This document captures the design and rationale for the redesigned sync system between Airtable (content authoring CMS) and PostgreSQL (the `brain_*` tables consumed by the app), plus the analytics Interface built on top of it. It exists to:

- Make the design explicit so future-you (or another Claude session) doesn't have to reverse-engineer it from code.
- Define the recipe for applying this same pattern to other tables in Stage 5.
- Track deferred decisions and known gaps so they aren't lost.

---

## 2. Context: what existed before

The old system had:

- A single status formula per table mixing content readiness and video readiness.
- A single `LastModifiedSaved` timestamp written back by the backend after sync.
- A single `lastModifiedTimeRef` formula computing the modtime across all fields.

Problems with that design:

- Content and video lifecycles were entangled. Modifying video data triggered "content needs resync" signals, and vice versa.
- "Status" conflated several distinct questions: "is data complete?", "has it been synced?", "is it live?", "is the video uploaded?"
- No archive concept — `Live=No` had to do double duty for "paused" and "retired," which are different things.
- No way to mark test/dev records that don't follow normal completeness rules.

---

## 3. Core design: two parallel lifecycles

The redesign separates two independent sync flows that share a record:

### Content lifecycle

- **Tracks**: text fields, relationships, numerics, video URL outputs (`VideoUrl`, `VideoUrlOptimized`, `PosterUrl`, `PosterTime`).
- **Sync action**: Airtable "Sync Data" button → POSTs to `/webhook-sync-interaction` → backend upserts `brain_interaction`.
- **Backend writes back** `LastContentSyncedAt` to Airtable on success.

### Video lifecycle

- **Tracks**: only the `Video` attachment field itself.
- **Sync action**: Airtable "Upload Video to Cloudinary" button → POSTs to `/upload-video-to-cloudinary` → backend uploads to Cloudinary, returns URL.
- **Airtable script writes** `VideoUrl` AND `LastVideoSyncedAt` on success.

The two lifecycles produce independent sub-statuses (`ContentStatus`, `VideoStatus`), which a composite `Status` formula combines into a single human-readable state.

### 3.1 Why the two lifecycles need separate modtime tracking

Each lifecycle has its own `LAST_MODIFIED_TIME` formula watching only its own fields:

```
VideoLastModified = LAST_MODIFIED_TIME({Video})

ContentLastModified = LAST_MODIFIED_TIME(
  TranscriptionFr, TranscriptionEn, Subtopic, Type, Intents,
  Hints, ExpectedNotion, ExpectedEntities, ExpectedVocab,
  InteractionVocab, InteractionOptimumLevel, Boredom, LevelFrom,
  EntryPointy, SelectionMode, Speak, Gender, Live, RecordState,
  MatchedAnswer, MatchedAsVariant, MatchedAsFollowUp,
  Initial Interaction, VideoUrl, PosterTime
)
```

**Key insight**: the Cloudinary upload writes `VideoUrl`, which is data destined for Postgres — so `VideoUrl` belongs to content, not video. Only the source `Video` attachment defines the video lifecycle.

### 3.2 Critical field placement

| Field | Source | Lifecycle | In LAST_MODIFIED_TIME of |
|---|---|---|---|
| `Video` (attachment) | Manual upload | Video | `VideoLastModified` |
| `VideoUrl` | Cloudinary script | Content | `ContentLastModified` |
| `VideoUrlOptimized` | Formula from VideoUrl | Content (derived) | — (formula, auto-tracks) |
| `PosterUrl` | Formula from VideoUrl | Content (derived) | — (formula, auto-tracks) |
| `PosterTime` | Manual entry | Content | `ContentLastModified` |

---

## 4. The state machine

The composite `Status` formula evaluates conditions in priority order. The first matching condition wins.

| State | Condition | What to do |
|---|---|---|
| ⚫ Archived | `RecordState = Archived` | Ignore |
| 🧪 Test | `IsTest = TRUE` | Ignore in normal workflow |
| 🟠 Not ready | Either `ContentStatus` or `VideoStatus` is 🟠 | Fill missing required fields |
| 🆕 Ready for first sync | Content/Video are 🟣 New (never synced) | Click Sync Data and/or Upload Video |
| 🟢 Live | Both sub-statuses 🟢, `Live = Yes` | Done — serving to users |
| ⏸️ Ready, paused | Both sub-statuses 🟢, `Live = No` | Decide whether to flip Live to Yes |
| 🔵 Content needs resync | `ContentStatus = 🔵 Update` | Click Sync Data |
| 🎥 Video needs resync | `VideoStatus = 🔵 Update`, `ContentStatus = 🟢` | Re-upload video to Cloudinary |
| 🟡 In progress | Anything else (typically mid-authoring) | Keep authoring |

### 4.1 Priority rationale

- **Archived** overrides everything — a record taken out of rotation should be visually distinct regardless of data state.
- **Test** overrides operational signals — test records have different completeness rules.
- **Not Ready** surfaces blocking data gaps before showing positive signals.
- **Live** distinguishes "served to users" from "complete but paused."
- **Resync states** surface drift after a successful sync.
- **In Progress** catches everything else.

---

## 5. Required fields for content readiness

| Field | Required? | Notes |
|---|---|---|
| TranscriptionFr | Required | Core content |
| TranscriptionEn | Required | Core content |
| Subtopic | Required | Categorization |
| Type | Required | Categorization |
| InteractionOptimumLevel | Required | Numeric |
| LevelFrom | Required | Numeric |
| EntryPointy | Required | Categorical role (*typo: rename to `EntryPoint` later*) |
| Speak | Required | Behavior flag |
| MatchedAnswer | Required (≥1 linked) | At least one answer must be linked |
| Intents | Not required | Optional list, can be empty |
| ExpectedNotion / Entities / Vocab | Not required | Optional lists |
| Hints, InteractionVocab | Not required | Optional lists |
| SelectionMode | Not required | Has a backend default |
| Gender | Not required (yet) | Will be wired to backend later |
| Live, RecordState | Not checked | Have defaults, never blank |

---

## 6. The archive concept

`RecordState` is a single-select with three values: **Active** (default), **Retired**, **Archived**.

- **Active**: in normal use. `Live=Yes` means serving; `Live=No` means temporarily paused.
- **Retired**: pulled from active rotation but kept for reference. Reversible.
- **Archived**: terminal soft-delete. Filtered out of app queries via `brain_*.archived` column. Still reversible if needed.

Archive is achieved by changing `RecordState` to Archived in Airtable, then syncing. The backend stores this as a boolean `archived` column on each `brain_*` table (to be added when each table is migrated).

### Cross-table archive policy (decided design)

- Records are independent entities — archiving an Answer does **not** block any Interaction that references it, and vice versa.
- Orphans are allowed. The app filters `archived=true` rows at the query layer.
- Future: a periodic "data quality" view will surface orphaned/forgotten records for cleanup (Stage 4+).

---

## 7. Backend architecture (airtable_routes.py)

### Per-lifecycle timestamp config

`SYNC_CONFIGS["interaction"]` declares its own timestamp behavior:

```python
"interaction": {
    "table_name": "brain_interaction",
    "airtable_table": "Interaction",
    "timestamp_field": "LastContentSyncedAt",  # vs default LastModifiedSaved
    "use_now_timestamp": True,                  # vs default: use payload timestamp
    "columns": [...]
}
```

`background_airtable_update` accepts a configurable `timestamp_field` parameter (default `LastModifiedSaved` for backward compat).

`generic_sync_webhook` reads the config and branches: if `use_now_timestamp`, write `int(time.time() * 1000)`; else use the payload's `lastModifiedTimeRef`.

### Validators relaxed on InteractionEntry

- `intents` is now optional (`Optional[List[str]] = None`) with a lenient validator matching the other optional ID arrays.
- Duplicate `videoUrl` declaration removed.

---

## 8. Airtable fields added to Interaction

### Sync infrastructure fields

- `RecordState` — single-select: Active / Retired / Archived, default Active
- `IsTest` — checkbox, default unchecked (marks test records exempt from video requirement)
- `LastContentSyncedAt` — Number, integer (written by backend after content sync)
- `LastVideoSyncedAt` — Number, integer (written by Cloudinary script after upload)
- `ContentLastModified` — formula, `LAST_MODIFIED_TIME` of content fields
- `VideoLastModified` — formula, `LAST_MODIFIED_TIME` of `Video` attachment only
- `ContentStatus` — formula, 4 states: Not Ready / New / Update / Done
- `VideoStatus` — formula, 5 states including Test variant
- `Status` — formula, composite 9-state machine (see section 4)

### Helper formulas for analytics

Six derived flag/value formulas supporting the Subtopic Analytics Interface (see Section 13):

- `IsReady` — 1 if Status indicates content-complete (🟢 Live, ⏸️ Ready paused, 🆕 Ready for first sync); else 0
- `AnswerCount` — count of records linked via `MatchedAnswer`, using comma-counting workaround for Airtable's link-field count quirk
- `IsUsable` — 1 if `IsReady = 1 AND AnswerCount >= 2`; else 0 (production-ready)
- `IsCounted` — 1 if `RecordState = 'Active' AND IsTest = FALSE`; else 0 (counts in real metrics)
- `LevelBucket` — 50-wide level band as padded string (`000-049`, `050-099`, ... `400+`), or blank if level unset
- `UsableLevel` — `InteractionOptimumLevel` if `IsUsable = 1`, else blank (for level-range rollups)

### 8.1 Fields removed during cleanup

11 dead fields were removed in Stage 0: `Audio`, `AudioName`, `Image`, `Image name`, `RecognitionRate`, `Debugger`, `NormalSpeed`, `ID (from Subtopic)`, `Phonetic` (premature), `(old)AllMatchedReuseVocab`, `AllMatchVariant`.

Three Interaction-Answer link fields were renamed for clarity:

- `Interaction-Answer` → `MatchedAnswer`
- `Interaction-Answer 2` → `MatchedAsVariant`
- `Interaction-Answer 3` → `MatchedAsFollowUp`

---

## 9. Daily workflow

### Authoring a new Interaction

1. Fill required content fields (transcriptions, subtopic, type, level, etc.).
2. Link at least one Answer via `MatchedAnswer`.
3. Attach Video file.
4. Set `PosterTime`.
5. Click "Upload Video to Cloudinary" → `VideoUrl` written, `VideoStatus` → 🟢 Done.
6. Click "Sync Data" → `ContentStatus` → 🟢 Done.
7. Set `Live = Yes` when ready → `Status` → 🟢 Live.

### Modifying an existing Interaction

- Edit any content field → `ContentStatus` → 🔵 Update → click Sync Data.
- Replace Video attachment → `VideoStatus` → 🔵 Update → click Upload Video, then Sync Data (because `VideoUrl` will change).
- **Note**: content sync is usually needed after a video re-upload, since `VideoUrl` is content.

### Archiving

1. Change `RecordState` to Archived.
2. Set `Live = No`.
3. Click Sync Data — pushes both changes to Postgres. App stops serving the record.

### Identifying authoring work (using the analytics Interface, see Section 13)

1. Open the Subtopic Analytics Interface.
2. Pick a subtopic from the dropdown (sorted thinnest-first).
3. Glance at the tile metrics — see total/usable counts and level range.
4. Look at the histogram — see where level coverage is concentrated and where the gaps are.
5. Scroll the interaction list at the bottom — pick a non-usable interaction to work on.
6. Click into it from the list, edit the missing fields, save.
7. Repeat for that subtopic until counts improve, then move to the next subtopic.

---

## 10. Deferred items (running list)

Things noted along the way, not yet done:

- Rename `EntryPointy` → `EntryPoint` (typo, needs backend coordination)
- Lookup field naming convention: `HintsID` / `IntentsIDs` / `ExpectedEntitiesID` inconsistent — pick one
- Dead code in Interaction sync script: unused `subtopicLink` variable
- Gender field wiring (currently authored but not synced)
- Phonetic table: decide whether it links from Vocab, Interaction, or stays standalone
- Field reordering: regroup Interaction table fields into logical sections
- Delete old `LastModifiedSaved` field on Interaction (after a week of stability)
- Pre-emptive Pydantic audit per table before applying recipe (Stage 5 prep)
- Cloudinary asset hygiene — folder structure, deterministic IDs, replace-on-reupload behavior, archive policy (Stage 6, new)
- Clean up test records created during Stage 3 validation
- **Zone 1 of the Subtopic Analytics Interface** (all-subtopics overview tiles + ranked bar chart) — deferred; Subtopic table grid view + picker dropdown order serve the same purpose adequately for now
- **Airtable Number element quirk**: Field Summary mode only offers blank-counting aggregations (Empty, Filled, Percent Filled, etc.) — no Min/Max/Average. Resolution was direct-field-display from the picked record. If the same need arises elsewhere, use direct-field-display rather than Number with Field Summary.
- lastModifiedTimeRef cleanup (multi-step):

After Stage 5 migrates all media-using tables to per-lifecycle timestamps, audit whether any consumer still needs lastModifiedTimeRef.
If not, make it optional in BaseEntry Pydantic model.
Remove from Airtable sync scripts (one per table).
Remove the last_modified_time_ref column from brain_* tables.
Remove the lastModifiedTimeRef formula field from each Airtable table.

Do these in this order to avoid breakage. Not before Stage 5 is fully done.

- Audit field consumers before any field removal. Surface drift like the missing lastModifiedTimeRef happens when we remove a field without tracing all consumers. Going forward, before deleting any field:

Search Airtable sync scripts for the field name
Search the backend repo for the field name (Pydantic models, SYNC_CONFIGS, columns lists)
Search the Postgres schema for the column
Search any other Airtable scripts (Cloudinary upload, etc.)

Only delete after confirming no live consumer exists, or after coordinating updates to all consumers.

---

## 11. Roadmap

### ✅ Stage 0 — Cleanup (done)
11 dead fields removed, 3 link fields renamed, several typos flagged.

### ✅ Stage 1 — New fields (done)
`RecordState`, `IsTest`, `LastContentSyncedAt`, `LastVideoSyncedAt`, `ContentLastModified`, `VideoLastModified`.

### ✅ Stage 2 — Status formulas (done)
`ContentStatus`, `VideoStatus` rewritten, composite `Status` added.

### ✅ Stage 3 — Sync wiring (done)
Backend writes `LastContentSyncedAt`; Cloudinary script writes `LastVideoSyncedAt`. Validators relaxed to match Airtable readiness rules.

### ✅ Stage 3.5 — Subtopic Analytics Interface (done)
Helper formulas on Interaction, rollups on Subtopic, Interface zones 2 and 3 built. See Section 13.

### Stage 4 — Live with it for a week
Use the new Interaction system for real authoring. Collect observations. Don't iterate prematurely.

### Stage 5 — Apply recipe to other tables
- Subtopic full modernization (complete Path A — Path B done June 17, 2026)
- Mistake (no media, simplest)
- Vocab (audio + optional image).
- Answer (audio + optional image)
- Per-table recipe: `RecordState` + `IsTest` + sync timestamps + `ContentLastModified` + status formulas + sync button + backend `archived` column.

### Stage 6 — Cloudinary asset hygiene
- Audit current asset organization across all media-using tables.
- Establish deterministic `public_id` convention (e.g., `interactions/INT123/video`).
- Modify upload endpoints to overwrite (not orphan) on re-upload.
- Archive policy: keep assets associated with archived records (do not delete).

---

## 12. Principles that shaped this design

Documented because they should guide future changes:

- **Lifecycles are independent.** Mixing content drift with video drift hides which thing actually changed.
- **Computed status beats manual status.** Each state should be derivable from underlying data, except where human judgment is required (`Live`, `RecordState`, `IsTest`).
- **Defer infrastructure for decisions you haven't made.** Empty placeholder fields are worse than no fields — they imply a design that doesn't exist yet.
- **Discovery before edits.** Always read actual current state of code/schema/Airtable before changing it. Memory drifts; reality doesn't.
- **Frontend and backend rules must agree.** "Required at one layer, optional at another" produces records that look ready but can't sync.
- **Archive instead of delete.** Soft-delete preserves history and is reversible.
- **Single source of truth via rollups, not duplicated logic in the Interface.** Compute readiness flags once on the source table, reference them everywhere downstream.

---

## 13. Subtopic Analytics Interface

An Airtable Interface page named **Subtopic Analytics** provides visual readiness analysis on the Subtopic table. Built to support the milestone goal of "200 interactions across 10+ subtopics covering a meaningful level range," but designed to remain useful afterward as ongoing authoring guidance.

### 13.1 Helper formulas on Interaction

Six helper formulas (listed in Section 8) compute derived flags used throughout the analytics layer:

- `IsReady` — content-complete (per Status)
- `AnswerCount` — number of linked answers
- `IsUsable` — production-ready (ready AND ≥2 answers)
- `IsCounted` — counts in real metrics (active, not test)
- `LevelBucket` — 50-wide band for histogram grouping
- `UsableLevel` — level value only if usable, blank otherwise (for Min/Max rollups that should ignore non-usable interactions)

### 13.2 Rollups on Subtopic

Five rollup fields aggregate the helper flags across each Subtopic's linked Interactions:

| Rollup | Source field | Aggregation | What it shows |
|---|---|---|---|
| `TotalInteractions` | `IsCounted` | `SUM(values)` | Real interactions in this subtopic (excludes archived/test) |
| `UsableInteractions` | `IsUsable` | `SUM(values)` | Production-ready interactions |
| `UsablePercentage` | `IsUsable` | `IF(COUNTA(values) = 0, 0, SUM(values) / COUNTA(values))` (formatted as %) | Share that are usable |
| `MinUsableLevel` | `UsableLevel` | `MIN(values)` | Lowest level with usable content |
| `MaxUsableLevel` | `UsableLevel` | `MAX(values)` | Highest level with usable content |

**Note on UsablePercentage**: the formula returns a fraction (e.g., `0.08`) and Airtable's Percent field format displays it as `8%`. Do NOT include `* 100` in the rollup formula if the field format is Percent — it would double-multiply.

### 13.3 Helper views

Two views were created to feed the Interface:

- **`Interface: Active Subtopics`** (on Subtopic table) — filter `TotalInteractions > 0`, sort by `UsableInteractions` ascending. Provides the picker source.
- **`Interface: Active Interactions`** (on Interaction table) — filter `IsCounted = 1`, sort by `InteractionOptimumLevel` ascending. Provides the list source.

### 13.4 Interface zones built

**Zone 2 — Selected subtopic detail (built)**

- **Record picker**: source = Subtopic, inline filter `TotalInteractions > 0`. Drives all downstream elements.
- **Five direct-field tiles** (added via "add field from picked record"): `TotalInteractions`, `UsableInteractions`, `UsablePercentage`, `MinUsableLevel`, `MaxUsableLevel`. These read the rollups directly rather than aggregating from links — keeps logic in one place.
- **Stacked histogram**: bar chart of `LevelBucket` (X axis) × count of Interactions (Y axis), filter `IsCounted = 1`, stacked by `IsUsable`. Shows level distribution and usable-vs-shell composition at each level band.

**Zone 3 — Interaction drill-down (built)**

- **Grid element**: source = Subtopic picker → Interaction, filter `IsCounted = 1`, sort by `InteractionOptimumLevel` ascending.
- **Visible fields**: `ID`, `TranscriptionFr`, `InteractionOptimumLevel`, `Status`, `AnswerCount`, `IsUsable`.
- Records are clickable for in-place editing.

**Zone 1 — All-subtopics overview (deferred)**

Originally planned with four big-number tiles (total usable, subtopics with ≥1 usable, subtopics at 0% readiness, empty-shell subtopics) and a ranked bar chart of subtopics by readiness. Deferred because:

- The Subtopic table's grid view (filtered + sorted by readiness) answers the same "where to focus" question.
- The picker dropdown's order in Zone 2 already reflects readiness ranking.
- Build only if usage reveals an actual need.

### 13.5 Notes on building this in Airtable Interfaces

A few things that surprised me during the build, recorded for future reference:

- **The Number element's "Source" picker traverses to a related table.** It does NOT display a field on the picked record directly. For that, use the alternate "add field from picked record" flow in the Add Element menu.
- **Number element's Field Summary mode only offers blank-counting aggregations** (Empty, Filled, Percent Filled, Percent Empty, Unique, Percent Unique). No Sum/Min/Max/Average. For those, use rollups on the source table and display them via direct-field tiles.
- **`Percent Filled` summary on `UsableLevel` works as a percentage substitute**: since UsableLevel is non-blank only for usable interactions, "percent filled" equals "percent usable." Useful fallback if direct-field display isn't available for some reason.
- **Padded bucket labels** (`000-049` not `0-49`) ensure correct sort order in chart category axes that sort alphabetically.
- **`AnswerCount` formula needed a workaround.** Airtable's `COUNTA` on a linked-record field returns 1 regardless of how many records are linked. The fix: stringify the field and count commas — `LEN({MatchedAnswer} & "") - LEN(SUBSTITUTE({MatchedAnswer} & "", ",", "")) + 1`. Caveat: would over-count if a linked record's primary field contains commas.

### 13.6 Daily use

See Section 9, "Identifying authoring work."
