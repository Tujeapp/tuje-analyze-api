# TuJe Deferred Items

**Living queue of work that's been considered but deferred. Updated across Claude conversations as items get added, completed, re-scoped, or dropped.**

*Purpose: keep open work surfaced across sessions so nothing falls through the cracks. Items here are NOT actively being worked on — they're cataloged for future sessions to pick up.*

---

## How to use this doc

- **Adding items**: when something gets deferred during a conversation, append to the appropriate section below with date, scope estimate, and reason for deferral.
- **Updating items**: if scope changes or a discovery reveals an item is bigger/smaller than thought, update in place with a note about what changed.
- **Closing items**: when an item is completed in some future session, move it to the "Completed" section at the bottom with the completion date. Don't delete — keep history.
- **Re-classifying items**: if an item turns out to be much bigger than originally scoped (like the plural rename below), update its scope and note the discovery that revealed the bigger picture.

Each item should have:
- **Title** — short identifier
- **What it is** — 1-2 sentences
- **Scope** — small (under 30 min) / medium (1-2 hours) / large (multi-session)
- **Risk** — what could go wrong
- **Why deferred** — what's blocking it from being done now
- **Last touched** — date last considered

---

## Recently deferred (June 20, 2026 session)

### `expected_*` and `interaction_vocab_*` plural rename
- **What it is**: Postgres columns are named `expected_notion_id`, `expected_entities_id`, `expected_vocab_id`, `interaction_vocab_id` (on brain_interaction), `expected_notion_id`, `expected_intent_id` (on brain_vocab). All six store TEXT[] arrays but are named with singular `_id`. Pydantic equivalents are already plural (`expectedNotionIds` etc.).
- **Scope**: **Large** (re-classified from "small cleanup" after discovery)
- **Risk**: HIGH. The 6 columns are read by **8 modules** in the backend (data_access_routes, bubble_integration_router, adjustement_cache_manager, adjustement_adjuster, adjustement_notion_matcher, adjustement_intent_matcher, adjustement_models, match_routes). A rename requires coordinated updates to SQL queries AND Record key accesses across all 8 files, distinguishing real DB references from already-plural Python identifiers (false positives exist).
- **Why deferred**: The June 20 session attempted this as a small cleanup. Postgres columns were renamed, but discovery then revealed the broader read paths. System was briefly broken; rollback was applied. Re-scoped properly as multi-module coordinated rename requiring full repo discovery BEFORE any Postgres ALTER.
- **Approach for future**: 
  1. Full repo grep for all 6 column names (singular form)
  2. Tabulate every reader file with line numbers
  3. Decide order of operations (probably: backend changes in all files → Postgres rename → test)
  4. Single atomic commit covering all backend changes
  5. Postgres rename in one batch
  6. End-to-end tests immediately after
- **iOS check**: Already done — zero references to any spelling. iOS clean.
- **Last touched**: June 20, 2026

### Gender field wiring on Interaction
- **What it is**: The `Gender` field is authored in Airtable on Interaction records but not synced to `brain_interaction`. Would need: Postgres column add, Pydantic field add, SYNC_CONFIGS update, field_mappings entry, sync script update.
- **Scope**: Medium (~30-45 min)
- **Risk**: Low. Pure feature addition, no rename.
- **Why deferred**: Originally bundled as "small cleanup" but is actually feature work (adding sync coverage), not cleanup. Deserves its own focused session with intentional design decisions (e.g., is Gender single-select or multi-select? What are the expected values?).
- **Last touched**: June 20, 2026

---

## Background-priority items

These can wait. Not blocking anything; cosmetic or low-impact.

### App-side query filtering on `archived`
- **What it is**: `archived` column is now correctly populated by sync on all 6 modernized tables, but iOS queries must add `WHERE archived = false` (or equivalent) for archive to actually hide records from users.
- **Scope**: Medium (iOS work, separate context entirely)
- **Why deferred**: Backend side is fully wired. iOS query work is a different context — not in scope for backend/sync conversations. Track here so it's not lost.
- **Affects**: brain_interaction, brain_subtopic, brain_mistake, brain_answer, brain_vocab, brain_interaction_answer
- **Last touched**: June 19-20, 2026

### Cloudinary upload file-type validation
- **What it is**: Existing Cloudinary endpoints rely on Cloudinary itself to reject mismatched file types, producing cryptic errors. Adding backend-side validation would reject non-matching MIME types early with a clearer error message.
- **Scope**: Small (~30 min per endpoint)
- **Why deferred**: Nice-to-have, not blocking. Real-world errors are rare and surface to authoring users (who can re-upload).
- **Last touched**: noted June 19, 2026

### Phonetic table decision
- **What it is**: A `Phonetic` link exists on Vocab but isn't synced. Decision pending on whether to author phonetic content as a separate brain_phonetic table.
- **Scope**: Large (depends on authoring strategy)
- **Why deferred**: Waiting for active phonetic authoring need to emerge. Currently not blocking anything.
- **Last touched**: noted multiple sessions

### Consider VOCAB_IMAGE_TRANSFORMATION
- **What it is**: Vocab images currently reuse `ANSWER_IMAGE_TRANSFORMATION` (width 300, crop limit). If Vocab UI displays images at significantly different sizes, a vocab-specific transformation would be needed.
- **Scope**: Small (cloudinary_service.py edit + Vocab image endpoint update)
- **Why deferred**: Only matters if/when iOS UI design diverges from Answer image sizing. No actual UI driver yet.
- **Last touched**: noted June 19, 2026

### Cloudinary URL strategy refactor
- **What it is**: Current setup bakes static transformations into URLs at upload time. Future refactor: store raw asset URLs in `brain_*` URL columns; iOS derives delivery URLs at request time based on device context.
- **Scope**: Large
- **Why deferred**: Post-MVP architectural improvement. Defer until iOS media display work is actively underway and the current approach proves limiting.
- **Last touched**: noted multiple sessions

### `last_modified_time_ref` columns as BIGINT
- **What it is**: **N/A — columns dropped on June 20.** Originally noted as a low-priority type cleanup (NUMERIC → BIGINT). Resolved by full deprecation.
- **Status**: Closed implicitly by lastModifiedTimeRef cleanup (June 20).

---

## Re-classified items (originally thought small, turned out bigger)

This section exists to prevent future conversations from making the same scoping mistakes.

### `expected_*` plural rename (see above)
**Why this is here**: It was first noted as "VocabEntry plural-vs-Postgres-singular naming inconsistency" — described as a "low priority cosmetic cleanup" affecting Vocab only. Discovery in the June 20 session revealed:
- Affects 6 columns across TWO tables (Vocab AND Interaction), not just Vocab
- Read by 8 modules in the backend, not just airtable_routes.py
- Coordinated rename requires touching SQL queries, Record key accesses, and false-positive identifier filtering

**Lesson for future sessions**: Before any Postgres column rename, run a full-repo grep for the column name across all .py files. Tabulate every reader. iOS check is necessary but NOT sufficient — backend modules also read the columns and will silently break on rename.

---

## Items that aren't really deferred — just paused on author cadence

### Drop old `LastModifiedSaved` field on the 11 non-modernized tables
- **What it is**: After per-lifecycle timestamps were adopted on 6 tables, the legacy `LastModifiedSaved` field still gets written to on the 11 unmodernized tables via the `or` fallback in generic_sync_webhook. Could be cleaned up when those tables are modernized.
- **Scope**: Bundled into each table's eventual modernization
- **Why not active**: The 11 unmodernized tables don't have active authoring workflows requiring modernization yet. Don't fix what isn't broken.

### iOS code search before any rename
- **What it is**: A pattern established in June 2026 sessions — before renaming any column in Postgres, run a Claude Code search in `~/Desktop/TuJe` for the column name in all relevant spellings.
- **Why noted here**: This is a workflow pattern, not a deferred item. But future conversations should be reminded to use it.

---

## Completed items (history, for future reference)

### June 20, 2026 — `lastModifiedTimeRef` full deprecation
Removed from BaseEntry (now Optional), 17 SYNC_CONFIGS columns lists, all 17 brain_* Postgres columns dropped, all 6 modernized tables had their Airtable scripts cleaned up + formula fields dropped. The 11 non-modernized tables keep sending it; backend ignores via Optional + fallback.

### June 20, 2026 — Interaction-Answer modernization
Full Stage 0-4 recipe applied. Single content lifecycle, 7-state status, strict Pydantic on 4 core fields, lenient on 6 relationship arrays. `list_of_mistakes` renamed to `mistake_ids` in Postgres + backend. End-to-end tested.

### June 20, 2026 — Small cleanups closed
- models.py legacy VocabEntry class deleted (was unused)
- Cosmetic `last_modified_time_ref` response echo removed from generic_sync_webhook
- `upload_answer_image.py` → `upload_answer_media.py` rename (file now contains both image + audio endpoints)
- Dead `subtopicLink` variable removed from Interaction sync script
- `EntryPointy` → `EntryPoint` Airtable rename + wired `entry_point` (boolean) and `entry_point_type` (text) into modernized sync. Both fields now sync-owned. 4-state Airtable single-select (`First`, `Open`, `Follow`, `Last`) drives both: `entry_point = (type === "First")`, `entry_point_type = the verbatim option name`.

### June 19, 2026 — Vocab full modernization (Path A1 + B)
3 lifecycles (content + audio + image). Introduced lenient + IsTest bypass design pattern. 11 new Postgres columns, 12 new Pydantic fields. New file `upload_vocab_media.py` with both Cloudinary endpoints.

### June 19, 2026 — `archived` system-wide wiring
All 6 modernized tables wired. Pydantic Optional[bool] = False on each Entry, "archived" added to SYNC_CONFIGS columns, scripts compute from RecordState.

### June 18-19, 2026 — Answer Path A1 + A2
3 lifecycles, audio endpoint built from scratch in cloudinary_service.py.

### June 18, 2026 — Mistake modernization
1 content lifecycle, strict Pydantic, 7-state status.

### June 18, 2026 — Subtopic modernization
2 lifecycles (content + video). Image collapsed into video via Cloudinary frame extraction.

### June 18, 2026 — NUMERIC → INTEGER cleanup
17 columns across 8 tables converted. `brain_answer.timer_seconds` later reverted to NUMERIC.

### June 12, 2026 — Interaction modernization (original blueprint)
Two-lifecycle design first applied. Recipe established.
