# test_selection.py — Manual

*How to set up, run, and interpret the selection-trace harness. Read this when you come
back to it after adding content and want to find flaws in the selection logic.*

---

## What this tool is (and is not)

It runs the **real** selection pipeline against the **real** database, for a user you choose,
and prints everything the normal `start-cycle` call hides:

- the user's actual recent history (the "seen" sets),
- the full candidate pool the search found,
- each candidate's **combination** value and the seen/new reasoning behind it,
- the final ordered 7 interactions,
- a one-line diagnosis.

It is **read-only** — it never writes to the DB. You can run it as often as you like.

**It tests:** whether the search finds the right candidates, whether `get_combination`
classifies them correctly, and whether the ordering picks/sequences them per the logic.

**It does NOT test:** the session-setup calc (boredom/level/mood derivation) — you *inject*
those as config. Nor the cycle-level/boredom/goal calc (that's the simplified placeholder).
This tool is about **selection given setup values**, nothing upstream of that.

---

## Setup & run

The script must live in the backend repo root (same folder as `session_context.py`,
`interaction_search.py`) so its imports resolve.

```bash
cd ~/Desktop/tuje-analyze-api
source venv/bin/activate
set -a; source .env; set +a       # loads DATABASE_URL — REQUIRED
python test_selection.py
```

If you see `DATABASE_URL not set`, you skipped the `set -a; source .env` line.

To change the scenario, edit the **CONFIG block** at the top of the script, then re-run:

| Config field | Meaning | Notes |
|---|---|---|
| `USER_ID` | which user's history to load | the seen-sets come from this user's real recent sessions |
| `CYCLE_BOREDOM` | 0.0–1.0 | filter: candidates need `boredom >= this`. Also the sort tie-break. |
| `CYCLE_LEVEL` | 0–400, step 50 | used by the first-interaction level constraint |
| `INTERACTION_USER_LEVEL` | 0–400 | the level the search filters around (`level_from BETWEEN level-50 and level+50`) |
| `SESSION_MOOD` | effective / playful / cultural / relax / listening | maps to allowed interaction *types* |
| `CYCLE_GOAL` | story / notion / intent | only **story** is fully built; notion/intent fall through |

> The history is the USER's (real, from the DB). The cycle params are YOURS (injected).
> To change what's "seen," change the user's history (via the SQL tools), not the config.

---

## Reading the output, section by section

### 1. SESSION CONTEXT (real history)
The three "seen" sets, loaded from the user's recent completed activity:
- `seen_subtopics` — subtopics from cycles completed in the **last 7 days**
- `seen_interaction_ids` — interactions completed in the **last 4 days**
- `seen_intents` — intents from interactions completed in the **last 7 days**

**If all three are empty** → cold-start. Every candidate becomes combination 5 (all "new"),
and selection can't differentiate. To test real behavior you need history here — use the SQL
tools to give the user completed cycles within those day-windows.

**Key insight:** "seen/new" is **time-windowed**. An interaction done 5 days ago is "new"
again for the transcription check (4-day window). So history decays — the same user tested
today vs. next week may see different combinations. When interpreting, always check this
section first: *the combinations only make sense relative to what's currently "seen."*

### 2. CANDIDATE POOL
The interactions the search found, in the single best subtopic (the one with the most
qualifying interactions). For each:
- `comb` — its combination (1–5)
- `boredom` — the interaction's own boredom rating (from `brain_interaction`)
- `level` — its `level_from`
- `entry` — whether it's an entry point (story cycles need one to start)
- `why` — the seen/new breakdown: `subtopic/transcription/intent`

**The combination map** (what `why` produces):
| subtopic / transcription / intent | combination |
|---|---|
| seen / seen / seen | 1 |
| seen / new / seen | 2 |
| seen / new / new | 3 |
| new / seen / seen | 4 |
| new / new / new | 5 |
| (anything else) | 5 (default) |

**If you see `⚠️ Starting boredom fallbacks...` or level fallbacks** before the pool: the
search couldn't find ≥7 candidates at your settings and had to relax (lower boredom, then
lower level). That's a **content-thinness signal** — not enough interactions matched. A
healthy content library should rarely trigger fallbacks for a mid-range user.

**If you see `SEARCH FAILED / InsufficientInteractionsError`**: no subtopic had ≥7 qualifying
interactions even after all fallbacks. Pure content problem — add interactions for that
level/mood/subtopic.

### 3. FINAL SELECTION (ordered 7)
The chosen interactions in play order. Position 1 is the entry point (story cycles).
Positions 2–7 follow by combination proximity to the previous one.

### 4. DIAGNOSIS
A heuristic line: did the final 7 span multiple combinations or collapse to one?
- "All share combination N" → either cold-start, or the pool had variety but the sort didn't
  reach it (see the interpretation note below).
- "Span combinations [...]" → differentiation is happening.

> **Caveat on the diagnosis line:** it looks only at the *final 7*. The *candidate pool* may
> have had variety (e.g. some combo-2s) that the sort never selected because there were
> enough combo-1s to fill all 7. So "all share combination 1" can mean "pool had only seen
> content" OR "pool had some new content but selection prioritized seen." Check the POOL
> section to tell which — that distinction is where the real flaws hide.

---

## How to hunt for flaws (the point of the tool)

Once you have real content, this is the interpretation work:

### Check 1 — Does combination classification match reality?
Pick a candidate, look at its `why`. Is it correct? E.g. if a subtopic IS in `seen_subtopics`
but the candidate shows `new/...`, the classification is wrong. (Unlikely — `get_combination`
is simple — but verify once.)

### Check 2 — THE BIG ONE: does the boredom→novelty direction match the design intent?
This is the open question the tool surfaced and the most important thing to verify.

**The design intent** (per *Definitions*, "combinations of repetition"): *higher boredom →
the app should reach for NEWER content* (higher combination numbers). At boredom 0, the app
may use combinations 1–5; at boredom 0.46, it should look in combinations 4 and 5 (newer).

**What the code currently does:** the search filters `boredom >= cycle_boredom` and the pool
is sorted **ascending by (combination, boredom)** — so the *lowest* combinations (most SEEN)
are picked first.

**The thing to check with rich content:** run a HIGH boredom scenario (e.g. `CYCLE_BOREDOM =
0.5`) against a user with mixed seen/new history. Does the selection serve NEWER content
(higher combinations), as the design intends? Or does it still serve combination-1 (all seen)?

- If high boredom still yields all-seen content → the sort direction likely **contradicts**
  the design (boredom should push toward new, but the ascending sort pulls toward seen). That
  would be a real logic flaw to fix.
- If high boredom yields newer content → the direction is fine and the earlier observation
  was just cold-start/thin-content.

**Do not assume which.** This tool exists to answer it empirically once content is rich
enough. With thin content (as now), you can't tell — every interaction is "seen" because the
test user has done them all, so combination 1 dominates regardless of boredom.

### Check 3 — Are fallbacks firing too often?
If almost every run triggers boredom/level fallbacks, your content is too thin at common
level/mood combinations. The selection logic can't be evaluated fairly until the pool is
healthy (comfortably more than 7 candidates, ideally across multiple subtopics).

---

## Why thin content blocks interpretation right now

The current test user has done essentially all interactions in the one available subtopic.
So `seen_interaction_ids` covers almost everything → almost every candidate is "seen" →
combination 1 → no variety for the sort to express. **You cannot judge selection quality
until there is enough content that a user can have a genuine mix of seen and new.**

Priority before serious testing: add subtopics and interactions (varied levels, types,
entry-points, notions) so that a user with partial history produces a candidate pool spanning
multiple combinations. Then this tool will show clearly whether selection behaves per design.

---

## Limits (don't over-read results)

- Tests **selection given injected setup values** — not the setup-calc or the (simplified)
  cycle-calc.
- Only **story** goal is fully built; notion/intent fall through to the story query.
- The notion-mastery filter is currently **disabled** in the search (R11 / R31), so candidates
  are NOT filtered by notion_rate yet — keep that in mind when judging the pool.
- Results are only as meaningful as the content library and the user's history are realistic.
