# TuJe — Notion Model (Redesign)

**Status:** Authoritative design for the notion system. This document **supersedes**
the notion sections of *Logic of a Session* and the notion fragments in *Details of
logic of session* where they conflict. It was written after recognising the original
notion design was incomplete — in particular, it adds the passive/active mastery
tracking and changes `session_notion` from update-in-place to new-rows-per-session.

**Not yet built.** This is the spec to build against, not a description of current
code. See §6 ("What exists vs. what this changes") for the gap.

---

## 1. Core idea — mastery is passive AND active

A notion is "owned" only when the user can both **understand it when heard**
(passive) and **produce it when answering** (active). These are tracked separately
and both feed the notion score.

- **Passive notion** — a notion present in an interaction (the user listens to it).
  Sourced from `brain_interaction.interaction_notion` (the list of notions the
  interaction contains).
- **Active notion** — a notion the user actually produces in their answer. Sourced
  from answer analysis. **May differ** from the interaction's notions — the user can
  produce notions that were not presented.

Mastery (score → 1) requires both halves: recognising the notion *and* producing it
when warranted.

---

## 2. Terms (renames noted)

- **Notion score** (was "notion rate") — decimal 0–1. 1 = fully owned; 0 = unknown.
- **Notion priority score** (was "notion priority rate") — decimal 0–1. 1 = top
  priority to practise. Low = already owned, or at a level the user can't use yet.
- **Notion complexity score** (was "notion complexity rate") — decimal 0–1. 1 = this
  notion is especially hard **for this particular user** (not universally).
- **List of notions** — the ordered list of which notions to practise first. Built
  from each valid notion's priority score + complexity score. Drives interaction
  selection: find interactions that primarily use the top notions → the interaction
  pool.

### New tracked values (new columns on `session_notion`)

- **`passive_notion_understood`** (list) — notions the user understood from listening,
  per record.
- **`passive_notion_understood_score`** (0–1) — 1 = the user understood this notion
  every time any interaction in the session presented it. Computed against
  `brain_interaction.interaction_notion`.
- **`active_notion_mentioned`** (list) — notions the user produced in their answers.
- **`active_notion_mentioned_score`** (0–1) — 1 = the user used this notion every time
  it was warranted, measured against `brain_interaction.expected_notions` (the notions
  a good answer should produce). Using **more complex** notions than expected also
  scores 1.

### Passive / active score — confidence-weighted (LOCKED)

`passive_score` and `active_score` measure how well the user handles a notion this
session, **dampened by how much evidence there is** — a perfect 2/2 is not trusted
like a 13/14, because two observations could be luck. This is confidence-weighted
(shrinkage) scoring.

**Counts tracked per `session_notion` row (per side):**
- `passive_mentioned_total` (T) — starts at 0; +1 each time an interaction's
  `interaction_notion` contains this notion.
- `passive_mentioned_succeed` (S) — starts at 0; +1 each time interaction analysis
  says the user understood it.
- (active side identical: `active_mentioned_total`, `active_mentioned_succeed`, where
  "total" = times the notion was warranted per `expected_notions`, "succeed" = times
  the user produced it — producing a *more complex* notion than expected also counts.)

**The formula (Option 1 — shrinkage toward a baseline):**

```
passive_score = (S + k·m) / (T + k)        # with m = 0  →  S / (T + k)
active_score  = (S_active + k·m) / (T_active + k)
```

- **m = 0** — the baseline a score drifts toward with little evidence ("assume
  not-yet-understood until proven"). Pedagogically honest "prove it" stance.
- **k = 7** — evidence-strength knob: how many observations before a high ratio is
  trusted. Chosen because a user works ~5–10 notions at a level across 21
  interactions/session, so a notion recurs several times; k=7 dampens low-evidence
  scores without over-penalising normal counts. **Tunable** once real session data
  exists.
- Computed at **session end** (moment 3), rounded to 2.

**Behaviour (why this is right):** few mentions pull a high ratio down (2/2 → 0.22 at
k=7); many mentions let it settle near the true ratio (13/14 → 0.62). A notion needs
*both* good performance *and* enough exposure to score high.

**Important property — scores compress toward the low end.** With m=0 and k=7, even a
perfect 7/7 only reaches 0.50; high scores require heavy exposure. So when these feed
priority/the list, what matters is notions' scores **relative to each other**, not
absolute values — a 0.50 is "perfect, solid evidence," not "mediocre." If higher
absolute scores are ever wanted, raise m above 0 (e.g. m=0.5 = "assume neutral until
evidenced").

**Feedback-UI caveat:** because the score conflates performance and evidence, the
*user-facing feedback* should show the **raw ratio (S/T) and the evidence (T)
separately** — a user seeing "0.22" on a notion they got 2/2 on would be confused.
The dampened score is for the *engine* (priority/list); the breakdown is for the user.

### Rates (unchanged definitions, now fed by the above)

- **Notion passive rate** = (this notion's passive mentions ÷ all notions' passive
  mentions), across all sessions in the last 7 days.
- **Notion active rate** = (this notion's active mentions ÷ all notions' active
  mentions), across all sessions in the last 7 days.

> **Note — passive/active SCORE vs RATE.** The *score* (above) = how well the user
> handles the notion this session, confidence-weighted. The *rate* = how often the
> notion appeared relative to all notions over 7 days. Different things. (See the
> critical-path note in §5.)

---

## 3. Which notions get records, and when they are born

- `session_notion` does **not** hold all of `brain_notion` at once. A notion gets a
  record only when it is in play: **score > 0 and score < 1**. (Score 0 = not yet
  introduced; score 1 = fully owned — neither needs active tracking.)
- **New records every session.** Do **not** update prior-session records — create new
  `session_notion` rows each session. (This is a change from the current
  update-in-place model — see §6.)
- **Records can be born mid-session.** If an interaction presents, or an answer
  produces, a notion not already tracked this session, create a new record then.
- **7-day retention.** Keep only the last 7 days of `session_notion`. After 7 days,
  aggregate to global/historical data and drop the rows, to avoid unbounded growth.

---

## 4. The three update moments

Notion data is computed/updated at three points in a session. (Current code only
really implements the first.)

### Moment 1 — session start (before cycle 1)

The first cycle needs notions ready, so compute everything up front:

- Notion score
- Priority score
- Complexity score
- Passive rate
- Active rate
- Passive understood + passive understood score
- Active mentioned + active mentioned score

### Moment 2 — along each interaction

After each completed interaction, update the running tallies:

- **Passive notion** — update the list (which notions the interaction presented /
  the user understood).
- **Active notion** — update the list (which notions the user produced in the answer).

(These running lists feed the scores recomputed at moment 3.)

### Moment 3 — session end

Recompute all of moment 1's values for final, accurate feedback:

- Notion score, priority score, complexity score
- Passive rate, active rate
- Passive understood + score, active mentioned + score

---

## 5. The list of notions (drives the notion-goal cycle)

- Include only notions with **score > 0 and score < 1** (mid-learning; exclude unknown
  and fully-owned).
- Sort by **priority score (desc)**, then **complexity score (desc)**.
- The top notion(s) of this list are what a notion-goal cycle drills: find interactions
  that primarily use the top notion(s) → the cycle's interaction pool.

(The notion-goal cycle interaction search and ordering — subtopic list, ≥7
interactions total, once-per-subtopic ordering — live in *Details of logic of session*
and are built **on top of** this model. They are out of scope for this document, which
defines the mastery model the search consumes.)

### Critical path vs. feedback layer

Not everything in this model gates the notion-goal cycle. Two tiers:

- **Critical path (needed to build the list → the cycle):** notion score, priority
  score, complexity score, and the passive/active **rate** (7-day relative frequency,
  which feeds priority's coefficient B and complexity). These determine *which notions
  get drilled*.
- **Feedback layer (NOT needed for the list):** the `passive_notion_understood` /
  `active_notion_mentioned` lists and any per-notion quality breakdown shown to the
  user. These are the "rational mirror" for user feedback and can be built as a
  separate workstream, later, without blocking the notion-goal cycle.

The passive/active **score** (the confidence-weighted §3 value) sits between: it feeds
the notion score (critical path) but is *also* surfaced (with its raw-ratio/evidence
breakdown) in feedback. Build it on the critical-path side; expose it in feedback later.

---

## 6. What exists vs. what this changes (build gap)

**Exists today (`notion_management.py`, session-start path):**
- Session-start decay of notion score (coefficient A + B).
- Priority = (1 − score) × weightiness.
- Complexity (5-factor average).
- `get_top_notions_list` (priority desc, complexity desc, excludes 0/1).
- New-user seeding (`initialize_notions_for_new_user`).
- **Update-in-place** on existing `session_notion` rows.

**This redesign adds / changes:**
- **New `session_notion` columns:** `passive_notion_understood`,
  `passive_notion_understood_score`, `active_notion_mentioned`,
  `active_notion_mentioned_score` (plus confirm the existing passive/active rate
  columns feed from these).
- **Per-interaction tracking (moment 2)** — appears **not built**. The passive/active
  increment logic at interaction completion does not yet exist.
- **New-rows-per-session** — **conflicts** with current update-in-place. Revises
  `session_init` and every function that writes `session_notion`. Not additive.
- **Session-end recompute (moment 3)** — not built.
- **Score now derives from passive-understood + active-mentioned** — a different
  driver than the current decay-only model.

---

## 7. Open questions to resolve before building

1. **Data foundation — do these `brain_interaction` columns exist?**
   - `interaction_notion` (notions the interaction contains — passive source)
   - `expected_notions` (notions a good answer should produce — active-score target)
   (Earlier schema reads showed `expected_notion_id`; confirm exact names/shape.)
2. **`session_notion` current columns vs. needed** — confirm what's there now and what
   the four new columns require (types: lists vs. arrays vs. JSON).
3. **Update-in-place → new-rows-per-session** — this is an architectural change
   touching `session_init` and all notion writers. Plan the migration: does anything
   depend on cross-session row continuity? (The 7-day retention + global aggregation
   replaces continuity.)
4. **The decay model's fate** — current code decays score at session start. Does the
   new passive/active-driven score *replace* decay, or do they coexist (decay between
   sessions, passive/active within)?
5. **Score formula** — RESOLVED for passive/active score: confidence-weighted
   shrinkage `(S + k·m)/(T + k)`, m=0, k=7 (see §3). **Still open:** how the
   passive_score and active_score (and the rates) combine into the overall **notion
   score** — the mastery-needs-both principle is clear, the exact combination is not
   yet specified. And how this relates to the existing decay model (§7.4).

---

## 8. Build order (proposed, for a fresh session)

1. **Discovery** — confirm §7 data questions (brain_interaction columns, session_notion
   columns) against the LIVE schema/code. (Note: project-knowledge copies of
   `interaction_search.py` etc. are stale — read live files.)
2. **Data foundation** — add the new `session_notion` columns; confirm/locate the
   `brain_interaction` notion columns.
3. **Per-interaction tracking (moment 2)** — passive/active list updates at interaction
   completion. (Touches the completion path — careful.)
4. **Score derivation** — passive-understood + active-mentioned → notion score; resolve
   the decay question (§7.4) and the combination formula (§7.5).
5. **New-rows-per-session model** — migrate from update-in-place; wire the three
   moments; 7-day retention + aggregation.
6. **Notion-goal cycle search** — only after the mastery model above works, since it
   consumes the list the model produces.
