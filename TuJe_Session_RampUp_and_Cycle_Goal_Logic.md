TuJe — Session Ramp-Up & Cycle-Goal Logic
First regular session, seen-ratio override, cycle-goal selection, and intent-cycle content.

How to read this document
This document is authoritative for the topics it covers. Where it conflicts with the older project documents — Logic of a Session, Definitions, Details of logic of session, Set first session for a new user — this document wins. Those were written last year and carry stale details, most importantly the level cap (was 500, now 400) and the wording (was rate, now score). The older documents remain the correct reference for everything they describe that is not restated or overridden here — in particular the full step-by-step logic of a normal regular session.
What this document specifies

The three-stage progression from a brand-new user to a fully data-driven session.
How the first regular session is set up despite having almost no history (the override list).
The permanent seen-ratio override governing content repetition for low-history and returning users.
How cycle goals are chosen (referencing the existing calculation) and the new exception for empty intent data.
How an intent cycle builds its content (the session_intents model).

Out of scope (defined elsewhere, intentionally not here): the answering system; the interaction-score calculation; speaking / comprehension / accuracy scoring; and the internal formulas for the intent score and intent priority score (named here, but deliberately left undefined — see §8).

1. Three-stage progression
There are three stages, not four. The exceptions described in this document apply only up to and including the first regular session. The second regular session is already fully normal.
StageStructureData situationInitial session1 cycle of 7 pre-selected interactions (already implemented)A tutorial plus a rough level read. Outputs a user level snapped to 0, 100, or 200. Writes no notion or intent data.First regular session3 cycles × 7 interactionsRuns almost like a normal session, but starts with almost no history. Several inputs are skipped, preset, or overridden (§4).Regular session onward3 cycles × 7 interactionsFrom the second regular session, the full normal logic in the base documents applies — with the 400 cap, the score wording, the permanent seen-ratio override (§5), and the empty-intent exception (§6) all in force.
The initial session sits outside the session_rank chain. The first regular session is rank 1 — the first ranked session. Every "if it is the first session, skip…" exception in the base documents therefore applies to the first regular session.

2. Corrected definitions
2.1 Level scale — the cap is 400
The level scale is the CEFR converted to a number from 0 to 400, stepping by 50. The maximum level is B2. Forget every reference to 500 / C1 in the older documents.
LevelValueA0.00A0.550A1.0100A1.5150A2.0200A2.5250B1.0300B1.5350B2.0400
Every level-based quantity in the base documents (cycle level, interaction user level, notion level-from, notion level-owned, subtopic level-from, etc.) is bounded by this 0–400 range; 400 is the hard ceiling.
The initial session can only snap the user level to 0, 100, or 200 (the three onboarding level options: A0 / A1 / A2).
2.2 Wording — "rate" → "score"
Across the whole project the performance / priority measures are named with score, not rate. So: notion score (was notion rate), notion priority score, notion complexity score, cycle score (was cycle rate), session score, interaction score, and the new intent score / intent priority score.
Genuine proportions and frequencies that are not tracked performance measures keep their natural names to avoid confusion: streak7 / streak30, the seen-ratio (§5), and the cycle-goal usage measures (§6). Where a usage measure could be confused with the per-intent performance score, the full disambiguating name is used (e.g. intent-goal usage score vs intent score).

3. Initial session (reference only — already implemented)
The initial session is already built and tested. It is documented here only for what it hands off:

It provides a tutorial and a rough level read.
Its single output that the rest of the system consumes is the user level, snapped to exactly 0, 100, or 200 (the onboarding choice, confirmed or moved up/down).
It writes no session_notion rows and no session_intents rows. No notions or intents are properly tracked from it.
It is outside the session_rank chain (see §1).

Consequently, when the first regular session is set up, all notion and intent history is empty and must be cold-started (§4, §7).

4. First regular session — the override list
This is the spine. The first regular session runs the normal session logic except for the following. (Anything not listed here behaves as in the base documents.)
Session-level handling

Rank: it is session_rank 1. All "first session" skips apply.
Skipped at setup (return empty / are not computed): streak7, streak30, session boredom, top session mood, session mood recommendation, the update-notion-score step, notion priority score, notion complexity score, list of intents seen, list of subtopics seen.
Session mood: default effective. The user still sees the mood-selection screen and may override.
Modulo: preset to 0.5. (The modulo is session-setup plumbing whose only consumer is the answer-scoring; the scoring itself is out of scope, but the modulo value is set here.) From the second regular session, the normal modulo formula applies.

List of notions (cold-start override)

Pull directly from brain_notion: maximum 5 notions, at the exact user level only, ordered by rank (rank = learning priority).
These 5 notions are written into session_notion here for the first time, each at score 0, with the notion introduction date set.
This write is the seed that gives the second regular session its first readable notion history.

Cycles — all three are goal story
Intent and notion goals are not available during the first regular session; the app does not yet have enough data to select goals properly. Cycle-goal selection (§6) therefore does not run in this session — it begins at the second regular session.

Cycle 1: cycle level = user level; cycle boredom = 0.
Cycles 2 and 3: the standard "not the first cycle" formulas apply. They are fed by the end-of-cycle data of the previous cycle (cycle level, cycle level direction, cycle score, cycle boredom). Cycle 2 reads cycle 1's end-of-cycle values; cycle 3 reads cycle 2's.

Note: the stored user_level does not move mid-session (it only updates at end-of-session). Cycles 2–3 read the cycle-level value, not a re-snapped user level.



Story interaction search (override)

Drop the normal filter "expected notions at score ≥ 0.8" — a brand-new user has no notion at ≥ 0.8, so this filter would otherwise return nothing.
Keep all other story-search filters (subtopic from the subtopic list, level ±50 around the interaction user level, boredom, type matches session mood, ≥ 7 interactions per subtopic, entry-point for the first interaction, follow for the next interaction).
The 5 seeded notions are tracked as they naturally appear in completed interactions; they do not gate selection in this session.

Seen-ratio override

The seen-ratio override (§5) also applies to this session. It applies to every cycle, forever — it is not a first-session-only patch.


5. Seen-ratio override (permanent, per cycle)
Why it exists
The base logic maps a low boredom toward combination 1 (all content "seen"), but a low-history or returning user has almost no "seen" content — so the mapping points at content that does not exist. This override resolves that conflict.
When it runs
At the start of every cycle setup, before the boredom → combination mapping. It is a permanent rule, applied to first and all subsequent regular sessions alike.
The check

Bracket = { user level − 50, user level, user level + 50 }, clamped to [0, 400].
(Edges: level 0 → {0, 50}; level 400 → {350, 400}.)
Bracket total = count of all interactions whose interaction_level_from falls inside the bracket.
Seen count = number of distinct interactions inside the bracket that the user currently holds as "seen". This is rolling: an interaction counts as "seen" only within its recency window (per the base definition, ~4 days or 3 sessions) and reverts to "new" afterward. A user returning after a long break therefore drops back under the threshold and re-triggers the override — this is intended.
Threshold = min( 20% of bracket total, 100 ), rounded to the nearest integer. The 20% scales with the catalogue; the cap of 100 prevents the threshold from growing unbounded as content is added.

The result

If seen count < threshold → the override fires:

Force combination 5 (new subtopic and new interaction).
Push both the subtopic search and the interaction search into their "new" branches.
Query combination 5 only — skip combinations 1–4 entirely, to avoid the dead lookups (cost optimisation).


If the override does not fire: the normal boredom → combination cascade (1 → 5) runs as in the base documents and naturally falls through to new content when "seen" content is exhausted — so cycles never starve. In that case the override is purely an optimisation; when it fires, it is also a hard guarantee.

Worked examples

Bracket total 300 → threshold = 60. The override fires while the user has seen fewer than 60 distinct interactions in the bracket.
Bracket total 600 → threshold = 100 (the cap binds, not 120).


6. Cycle-goal selection
Applies from the second regular session onward. (During the first regular session all three cycles are forced to story — see §4.)
Inputs (unchanged from the base logic)

Cycle boredom.
The last (closing) cycle goal.
The three goal-usage scores, each = the share of cycles using that goal in the last 7 days (count ÷ 7):

story-goal usage score,
notion-goal usage score,
intent-goal usage score.



The full selection algorithm — the boredom bands and the comparisons between usage scores that decide which goal comes next — is in Details of logic of session → Set a new cycle → Calculate the cycle goal (read with the 400 cap and score wording applied). This document does not restate those thresholds; it only adds the exception below.

Emergent note: at the second regular session the only history is the first session's three story cycles, so the story-goal usage score is high and the notion/intent usage scores are 0. This naturally biases the second session away from story.

New exception — empty intent data
If session_intents is empty — a new user, or a user whose intents were wiped because they left the app for more than 30 days (the prune in §7) — then intent is excluded from selection. The cycle goal is chosen only between story and notion.
The subsequent story / notion cycles repopulate session_intents (§7), after which intent becomes selectable again.

7. Intent-cycle content — the session_intents model
When a cycle goal resolves to intent, the cycle drills the vocabulary of one or more intents (e.g. "going for groceries") by grouping interactions that share that intent — without the conversational ordering that story requires. This section defines what populates an intent cycle, mirroring the notion architecture.
The table
A table session_intents holds, per user, one row for each intent the user has encountered. Each row carries:

a reference to the intent (from brain_intent, the full list of intents),
an intent score — how well the user handles that intent's vocabulary; low score = needs practice,
an intent priority score — how important that intent currently is to the user (analogous to notion priority score),
a last-updated timestamp (used for pruning).

The internal formulas for intent score and intent priority score are deferred — see §8. This document only establishes that they exist and what high/low means.
Population

The initial session writes nothing to session_intents.
Rows are created / updated as the user completes interactions that carry an intent, in any cycle type (story, notion, or intent).
The first regular session's three story cycles therefore produce the first session_intents rows. An intent cycle is never the first cycle to populate the table — it always inherits data from earlier story / notion play.

Pruning

Opportunistic at session setup (no separate scheduled job — cheaper, and it sits alongside the existing last-7-day / last-30-day reads already done at setup).
Remove any intent whose score / priority has not been updated in the last 30 days, so stale data does not pollute the list. (A full wipe via inactivity is what triggers the empty-intent exception in §6.)

Building the list of intents
When a cycle resolves to the intent goal, take session_intents and:

Sort by intent priority score, descending (primary).
Then by intent score, ascending (tiebreaker — lowest score first = most in need of vocabulary practice).
Take the top intents.

This list then feeds the intent-cycle interaction search in Details of logic of session (the search that was previously blocked precisely because the list of intents was undefined — it is now defined here, with the 400 cap and score wording applied).

8. Deferred internals (named, not yet defined)
These exist and are referenced above, but their formulas are intentionally left open, because they depend on designs not yet finalised. They are named here so other conversations know they exist and what they will mean.

Intent score. Will be built around vocabulary usage in the user's answers — the quality and quantity of vocabulary the user manages to produce for the intent induced by the interaction. Depends on the vocabulary design, which is not yet built, so the intent score cannot be defined yet.
Intent priority score. Will derive from the link between user goal (why the user is learning French), user interest (whether the user wants to practise this kind of vocabulary), and user level (whether this vocabulary matches the user's level). Not yet finalised.

For completeness: the notion score, notion priority score, and notion complexity score formulas already live in Details of logic of session and are unchanged except for the 400 cap and the score wording.
