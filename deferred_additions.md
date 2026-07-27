## Recently deferred (June 25, 2026 session — notion build)

### Moment 2 — notion per-interaction tracking (passive + active)
- **What it is**: During a session, increment each notion's passive/active "mentioned"
  counts as the user encounters/uses it, so notion scores rise from real usage (not just
  carry-forward decay). Passive side = notions an interaction CONTAINS (buildable now via
  `brain_interaction.interaction_notion`). Active side = notions the user's ANSWER actually
  produced (needs answer-notion detail from the answering system).
- **Scope**: Large (multi-session; the active side depends on the answering system)
- **Risk**: Medium. Touches the in-session answer flow; the score-adjustment formula
  (incl. the "reverse coefficient" inversion logic) lives here.
- **Why deferred**: The active side needs the interaction answering system to be reworked
  first (a separate conversation). Until tracking populates real passive/active rates,
  seed notion rows stay at score 0 (excluded from the list), and decay Coef B Data 2/3 run
  with 0 inputs. This is the keystone that makes the notion engine actually *learn*.
- **Last touched**: June 25, 2026

### Notion decay Coefficient B — calibration review
- **What it is**: The session-start decay (`_calculate_coefficient_b` in notion_management.py)
  looked steep in testing (0.50→0.15 crafted, 0.50→0.25/0.30 live). Audited line-by-line:
  the code is CORRECT-per-spec (all 4 Data points match) — nothing to fix or "invert". The
  open question is whether the decay MAGNITUDE is the desired learning behavior.
- **Scope**: Medium (a deliberate spec/design recalibration of bucket values, not a code bug)
- **Risk**: HIGH if done blindly — changing decay buckets silently alters all mastery
  tracking. Must be a deliberate, data-informed change.
- **Why deferred**: Can't calibrate well without data — passive/active rates (Coef B Data
  2/3) are 0 until Moment 2 tracking exists, and there's little real multi-session usage to
  judge the "right" decay curve against. Also confirm the Data 3 (active rate) bucket
  interpretation then (the spec text for Data 3 is malformed/overlapping; code mirrored
  Data 2). See DECAY_COEFFICIENT_B_NOTE.md.
- **Note**: "§8 inverted Coefficient B" (earlier shorthand) was a misnomer — the decay Coef
  B is not inverted; the reverse-coefficient inversion belongs to per-interaction score
  adjustment (part of Moment 2 above).
- **Last touched**: June 25, 2026

### Double-session guard (force-close active session on new start)
- **What it is**: When a user starts a new session, if they already have an `active`
  session, forcibly close it (status → `incomplete`) before creating the new one. A user
  must never have two `active` sessions.
- **Scope**: Small-Medium (one guard at the top of start_session_endpoint)
- **Risk**: Medium. Must close as `incomplete` (NOT `completed`) so the force-closed session
  stays out of the notion carry-forward's "highest-rank COMPLETED session" selection and
  out of streak math. Decide if it counts toward session_rank.
- **Why deferred**: Not blocking — the notion orphan-cleanup protects the NULL-marker model
  meanwhile. But genuinely needed: the notion integration runs repeatedly created 2+ active
  sessions (no guard), confirming the gap. See SESSION_GUARD_NOTE.md.
- **Last touched**: June 25, 2026

### Piece 4 refinements — notion-goal cycle search (full version)
- **What it is**: The notion-goal cycle search PLUMBING is built/validated
  (interaction_search_notion.py, branched in start_new_cycle, content-validated: 68
  candidates). Two refinements were deferred: (a) the "expected_intent contains seen
  intents" filter (Part 2) — deferred with the intent system; (b) the first/next-interaction
  ORDERING (Parts 4-5), incl. same-subtopic-max-TWICE — currently reuses the simple
  select_cycle_interactions branch.
- **Scope**: Medium
- **Risk**: Low-Medium. Ordering refinement; the pool-building works.
- **Why deferred**: Plumbing-first was the goal; ordering is a refinement on a working
  search. The intent filter waits on the intent list being wired.
- **Last touched**: June 25, 2026

### Intent-goal cycle search (Piece 4 for intent)
- **What it is**: Mirror the notion-goal search for the `intent` cycle goal — an
  intent-filtered interaction search (new file, e.g. interaction_search_intent.py), branched
  in start_new_cycle, consuming the intent list. Same plumbing-first discipline as notion.
  Currently `intent` goal falls through to the story search.
- **Scope**: Medium (mirrors the notion build)
- **Risk**: Low-Medium. New file, story untouched; depends on the intent list being
  populated (session_intents work was placeholder, §8/§6-blocked earlier).
- **Why deferred**: The logical NEXT major piece after the notion arc — flagged as the
  follow-up but not yet started.
- **Last touched**: June 25, 2026

### Deployed vs local StartCycleRequest drift
- **What it is**: The DEPLOYED `/start-cycle` endpoint requires `user_id` + `session_type`
  in its request body, but the LOCAL `session_management_router.py` `StartCycleRequest` class
  only declares `session_id`, `cycle_number`, `session_mood`. Local is behind deployed (or
  a change wasn't pulled/committed).
- **Scope**: Small (reconcile the local file with deployed)
- **Risk**: Low, but confusing — local code doesn't match the running API.
- **Why deferred**: Surfaced during the notion integration run; not blocking that work.
- **Last touched**: June 25, 2026

### Boredom precision — recurrence at the sync (optional)
- **What it is**: `brain_*` boredom/weightiness columns were constrained to `numeric(3,2)`
  (and timer_seconds to numeric(6,2)), which cleaned existing values AND enforces 2-decimal
  storage going forward — so recurrence is already prevented at the schema level. OPTIONAL
  follow-up: also round at the Airtable sync write, and watch for the sync doing redundant
  rewrites if it compares incoming full-precision floats to the now-rounded stored values.
- **Scope**: Small
- **Risk**: Low. Schema constraint already handles the core issue.
- **Why deferred**: The schema fix is sufficient; the sync-side rounding is belt-and-braces.
  See BOREDOM_PRECISION_NOTE.md.
- **Last touched**: June 25, 2026
