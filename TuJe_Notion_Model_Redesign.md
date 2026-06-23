# TuJe — Notion Model (Redesign) — v2

**Status:** Authoritative design for the notion system. **Supersedes** the notion
sections of *Logic of a Session* / *Details of logic of session* and the previous
version of this doc where they conflict. This v2 folds in the full design worked out
across the redesign session: passive/active mastery, confidence-weighted scoring,
new-rows-per-session, removal of the 7-day window, last-session/this-session data
sourcing, the twice-run decay, and the rank-1 handling.

**Mostly not yet built.** This is the spec to build against. Section 7 lists what exists
vs. what changes; Section 8 the one genuinely open design question; Section 9 the build
order.

---

## 1. Core idea — mastery is passive AND active

A notion is "owned" only when the user can both **understand it when heard** (passive)
and **produce it when answering** (active). Both are tracked and both feed the model.

- **Passive notion** — a notion present in an interaction (user listens). Sourced from
  `brain_interaction.interaction_notion`.
- **Active notion** — a notion the user produces in their answer (from answer
  analysis). May differ from the interaction's notions — the user can produce notions
  not presented.

---

## 2. Terms (renames noted)

- **Notion score** (was "notion rate") — 0-1. 1 = fully owned; 0 = unknown.
- **Notion priority score** (was "priority rate") — 0-1. 1 = top priority to practise.
- **Notion complexity score** (was "complexity rate") — 0-1. 1 = especially hard **for
  this user**.
- **Passive score** (was "passive rate") — see Section 3. **Renamed AND reformulated** —
  it is no longer a relative frequency; it is now the confidence-weighted mastery
  measure.
- **Active score** (was "active rate") — same treatment as passive score.
- **List of notions** — ordered list of what to practise first; built from priority +
  complexity. Drives the notion-goal cycle's interaction pool.

---

## 3. Passive / active score — confidence-weighted (LOCKED formula)

`passive_score` / `active_score` measure how well the user handles a notion, **dampened
by how much evidence there is** — a perfect 2/2 is not trusted like a 13/14.

**Counts per `session_notion` record (per side), reset to 0 at record creation,
incremented only during that session:**
- `passive_mentioned_total` (T) — +1 each time an interaction's `interaction_notion`
  contains this notion.
- `passive_mentioned_succeed` (S) — +1 each time interaction analysis says the user
  understood it.
- active side identical: `active_mentioned_total` (warranted per
  `brain_interaction.expected_notions`), `active_mentioned_succeed` (user produced it;
  producing a *more complex* notion than expected also counts).

**Formula (confidence-weighted shrinkage):**
```
passive_score = (S + k*m) / (T + k)      # m = 0  ->  S / (T + k)
active_score  = (S_active + k*m) / (T_active + k)
```
- **m = 0** — baseline ("prove it" stance).
- **k = 7** — evidence-strength knob. Tuned for ~5-10 notions/level across 21
  interactions/session. **Tunable** once real data exists.

**Behaviour:** few mentions pull a high ratio down (2/2 -> 0.22 at k=7); many mentions
let it settle near the true ratio (13/14 -> 0.62). Needs *both* good performance *and*
exposure to score high.

**Compression caveat:** with m=0, k=7, even 7/7 -> 0.50; high scores need heavy
exposure. What matters downstream is notions' scores **relative to each other**, not
absolute values.

**Feedback-UI caveat:** for the user, show the **raw ratio (S/T)** and **evidence (T)**
separately — a dampened 0.22 on a 2/2 would confuse. The dampened score is for the
engine; the breakdown is for the user.

---

## 4. Record lifecycle — new rows per session, NO 7-day window

- **New `session_notion` record per valid notion at session start.** A notion is
  "valid" / in play when its score is **> 0 and < 1** (0 = not introduced; 1 = owned).
- **Do not** carry forward by mutating old rows — create fresh rows each session. Past
  rows are **kept for feedback**, pruned eventually (no fixed window defined; "after a
  while").
- **Records can be born mid-session** — if an interaction presents, or an answer
  produces, an untracked notion, create its record then.
- **No 7-day window anywhere.** This replaces the earlier windowed model. Recency /
  consistency is carried by **streaks** and **introduction_date** (both already
  available), used inside the decay coefficients (Section 5).

### Fields per `session_notion` record
`introduction_date`, `notion_score`, `passive_score`, `passive_mentioned_total`,
`passive_mentioned_succeed`, `active_score`, `active_mentioned_total`,
`active_mentioned_succeed`, `priority_score`, `complexity_score` (+ housekeeping:
`id`, `user_id`, `notion_id`, `session_id`, `created_at`, `updated_at`).

---

## 5. The notion score — decay formula, run TWICE

The notion score is computed by the **decay formula** (already implemented in
`notion_management.py`):

```
updated_notion_score = last_notion_score - (last_notion_score * (Coefficient_A + Coefficient_B))
```

**Coefficient A** (session-wide, computed once, reused for all notions) = SUM of:
- Data 1 — streak30: `((streak30 - 0.4) / 0.1) * 0.05` (rounded 2)
- Data 2 — streak7: `((streak7 - 0.2) / 0.1) * 0.05` (rounded 2)
- Data 3 — session mood: effective -0.1; cultural/listening +0.1; relax/playful 0
- Data 4 — last session level direction: up 0; stable 0.05; down 0.1
- Data 5 — last session score: <=60 -> 0.1; >80 -> 0; else 0.05
- Data 6 — last session date (now - last): <=86400s -> 0; >259200s -> 0.1; else 0.05

**Coefficient B** (per notion) = SUM of:
- Data 1 — introduction_date age (now - intro): <=604800s -> 0; >2592000s -> 0.2; else 0.1
- Data 2 — passive score  [!] **buckets need redesign — see Section 8**
- Data 3 — active score   [!] **buckets need redesign — see Section 8**
- Data 4 — notion weightiness (`brain_notion`): <=0.5 -> 0; (0.5,0.7] -> 0.1; (0.7,0.9] -> 0.15; (0.9,1] -> 0.2
  (stated as non-overlapping ranges; the source spec's "more than" wording overlaps)

**Run twice:**
- **Moment 1 — session start (before cycle 1):** decay runs on **last session's** data
  (last passive/active score, last level direction, last session score, last session
  date). Produces the score that drives **this** session's notion list / cycle
  selection.
- **Moment 3 — session end:** decay runs again on **this session's fresh** data (the
  new passive/active scores just accumulated, new level direction, new session score).
  The result is stored and becomes the "last session" input the **next** session reads
  at its Moment 1.

**Last notion score** (the `last_notion_score` term) = read from the previous session's
`session_notion` record for that notion.

---

## 6. The three update moments (data sources)

1. **Session start** (before cycle 1) — from the **LAST session's** records: notion
   score (decay run 1), priority, complexity, passive/active score. Builds the notion
   list. *(Consumed for cycle selection only from session_rank >= 2 — see 6a.)*
2. **During the session** — increment **this session's** counts
   (`*_mentioned_total/succeed`) as interactions complete.
3. **Session end** — recompute from **this session's** data: notion score (decay run
   2), priority, complexity, passive/active score. Stored for feedback and as next
   session's "last session" input.

### 6a. First regular session = all story (rank-1 rule)

Per the ramp-up doc (already implemented in `calculate_cycle_goal`: `session_rank == 1
-> story`), the **first regular session forces all 3 cycles to story**. Notion goals
begin at **session_rank >= 2**. Consequence: the first session **populates** notion data
as a by-product of its story cycles, but no notion-goal cycle **consumes** it. The
second session is the first to read "last session" notion data for goal-based
selection. So "read last session" never hits an empty-history edge case — the rank-1
rule guarantees data exists before it's needed. (Brand-new users are still seeded via
`initialize_notions_for_new_user`.)

### 6b. Critical path vs. feedback layer

- **Critical path (gates the notion-goal cycle):** notion score, priority score,
  complexity score, passive/active score (these feed decay Coefficient B -> score ->
  priority -> the list).
- **Feedback layer (does NOT gate the cycle):** the `passive_notion_understood` /
  `active_notion_mentioned` lists and per-notion quality breakdowns shown to the user.
  Separate workstream, buildable later.

---

## 7. What exists vs. what this changes (build gap)

**Exists (`notion_management.py`):** session-start decay (A+B), priority =
(1-score)*weightiness, complexity (5-factor), `get_top_notions_list`, new-user seeding.
Decay Coefficient B currently consumes passive/active **rate** (old frequency formula).

**This redesign changes / adds:**
- **passive/active rate -> score**: rename AND replace the formula with the
  confidence-weighted Section 3 version. **Decay Coefficient B Data 2/3 currently read
  the old rate; they must be redesigned for the new score (Section 8).**
- **New `session_notion` columns:** `passive_mentioned_total/succeed`,
  `active_mentioned_total/succeed` (+ confirm passive_score/active_score columns).
- **Per-interaction tracking (moment 2)** — appears NOT built.
- **Session-end recompute (moment 3)** — NOT built.
- **Remove 7-day window** from rate/score computation; rely on last-session records +
  streaks + introduction_date.
- **Confirm new-rows-per-session** matches current code (current code may update in
  place — verify and align).

---

## 8. THE open design question — Coefficient B Data 2/3 buckets

Passive/active **rate** (old) was a relative frequency (~0.1-0.3 range, high = mentioned
often). Passive/active **score** (new, Section 3) is a mastery measure (~0.2-0.6 range,
high = well understood). The decay Coefficient B Data 2/3 buckets were calibrated for
the OLD range and meaning:
```
0-0.05 -> 0 ; 0.05-0.1 -> 0.1 ; 0.1-0.15 -> 0.15 ; >0.15 -> 0.2
```
Feeding the new score into these buckets breaks discrimination (most scores >0.15 -> all
land at 0.2) **and** may be directionally wrong (high mastery should perhaps mean *less*
decay, not more). **This must be resolved before building:**
- What should high passive/active *mastery* contribute to decay — more or less erosion?
- Recalibrate the bucket thresholds for the new range, and decide the direction.

This is a pedagogical design decision (how mastery affects score erosion), deliberately
left open rather than guessed.

---

## 9. Build order (fresh session)

1. **Resolve Section 8** (the Coefficient B redesign) — design decision first.
2. **Discovery** against LIVE code/schema: confirm
   `brain_interaction.interaction_notion` & `expected_notions` exist; current
   `session_notion` columns; whether current code updates-in-place vs new-rows.
   (Project-knowledge copies of search files are STALE — read live.)
3. **Data foundation** — add the new `session_notion` columns.
4. **Per-interaction tracking (moment 2)** — passive/active count increments at
   interaction completion (touches the completion path — careful).
5. **Score computations** — confidence-weighted passive/active score (Section 3); decay
   run 1 (start, last-session data) and run 2 (end, this-session data) with the
   Section-8-redesigned Coefficient B.
6. **New-rows-per-session + moments wiring**; pruning of old records (feedback only).
7. **Notion-goal cycle search** — only after the model above works (it consumes the
   list the model produces). Separate file `interaction_search_notion.py`, story
   untouched.

### Cross-system note (intent)
The intent system (`session_intents`) was built around the 7-day `get_seen_intents`
query. When the notion pattern is replicated for intent, intent should **mirror this
same model** — last-session/this-session sourcing, no 7-day window, confidence-weighted
scoring — to keep the twins consistent. Update intent accordingly at replication time.
