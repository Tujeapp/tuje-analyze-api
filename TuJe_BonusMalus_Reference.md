# TuJe — Bonus-Malus System Reference

**Status: engine built and verified standalone (interaction scope). NOT yet wired into scoring. Design is intentionally "a bit gross" for now — to be refined later.**

---

## 1. Purpose

A bonus-malus is a **score adjustment**. The common flow for scoring an interaction is: match an interaction-answer → compute a **gross score** → then **adjust** it up (bonus) or down (malus) based on what happened. The final interaction score is the gross score plus the sum of all applicable adjustments, clamped to [0, 100].

Bonuses and maluses can eventually adjust an **interaction**, a **cycle**, or a **session** score — the `scope` column says which. The first and main use is the interaction.

They fire in a huge range of situations. A few illustrative ones:

- **Behavioural (in-interaction):** using a hint; each listen beyond the first two; each answer attempt beyond the first.
- **Answer quality:** perfect on the first try; recovering after a wrong attempt.
- **History-based:** a sustained period of improvement; finally mastering a notion that was long a struggle; returning after an absence.
- **Contextual:** a date (Christmas), time of day, a streak.

There will eventually be **dozens**. The point of the current work was **not** to build them all — it was to define an *approach* for validating and authoring a bonus/malus, so they can be prepared in Airtable, and to build the engine that applies the first behavioural ones (extra listens, extra attempts) so interaction scoring can be tested.

---

## 2. The core approach — `rule_code` + `conditions`

Every rule has a **`rule_code`** and a **`conditions`** (jsonb) payload. They split responsibility:

- **`rule_code` names the metric family.** The backend has one handler per code that knows *how to compute* that metric (how to count listens, read attempts, check a date). Adding a genuinely new *kind* of trigger = writing one handler, once.
- **`conditions` parameterises it.** The row decides the thresholds, whether it repeats, caps, etc. Adding a *variation* of an existing kind = authoring a row in Airtable, no code.

Example:
```
rule_code:  "LISTEN_COUNT"
conditions: {"free_threshold": 2, "per_extra": true}
value:      5
type:       malus
```
→ "the first 2 listens are free; every listen after that costs 5 points."

This keeps a **small, growing vocabulary of rule_codes**, each with a documented `conditions` shape, while most authoring stays in Airtable.

### `conditions` vocabulary so far (count-based rules)
| Key | Meaning |
|---|---|
| `free_threshold` | how many occurrences are free before the rule bites |
| `per_extra` | `true` = value multiplies by the number over threshold; `false` = flat value applied once |

---

## 3. Authoring taxonomy

The useful way to classify a bonus/malus for authoring is **by what data it reads**, because that determines *when* it can be evaluated and *how much plumbing* it needs:

| # | Category | Examples | Evaluated at | Readiness today |
|---|---|---|---|---|
| 1 | In-interaction behaviour | extra listens, extra attempts, hints used | interaction commit | attempts ready; listens need client to send count; hints not recorded |
| 2 | Answer quality | perfect first try, recovered after wrong | interaction commit | ready (`answer_type`, attempts) |
| 3 | Cycle/session aggregate | no hints all cycle, all-perfect cycle | cycle/session completion | data ready, engine scope not built |
| 4 | User history | improvement streak, mastered a hard notion, return after absence | session start/completion | mostly ready |
| 5 | Contextual | Christmas, time of day, streak days | session start | trivial |

**Start with category 1** — it directly adjusts the interaction score, which is what needs testing next.

---

## 4. Rules to author (validation checklist)

Before authoring a rule, decide:

1. **Which `rule_code`?** Does a handler already exist for that metric, or is this a new kind (needs code first)?
2. **`bonus` or `malus`?** (`bonus_malus_type`)
3. **`value`** — the points.
4. **`conditions`** — thresholds/behaviour, in the vocabulary the handler understands.
5. **`scope`** — interaction / cycle / session (determines when it's evaluated and what total it adjusts).
6. **Level bounds** — `level_from` / `level_to` (null = unbounded).
7. **`priority`** — currently only for later categorisation; does not affect the result (all rules sum).
8. **`live`** — on/off.

**Handlers that exist today:** `ATTEMPT_COUNT`, `LISTEN_COUNT`. Any other `rule_code` is skipped (fail-safe) until its handler is written — so you can author ahead of code, and those rules simply won't fire yet.

---

## 5. Scoring rules (how adjustments combine)

- **Additive points.** A malus of 5 subtracts 5 from the 0–100 gross score (not a percentage).
- **All applicable rules fire and sum.** No selection between them.
- **Clamp to [0, 100].** If the sum takes the score below 0 → 0; above 100 → 100.
- **`priority`** does not currently affect the outcome — reserved for later categorisation.

This is deliberately coarse for now; the intent is to get *some* correct adjustment applied and testable, then refine.

---

## 6. The table — `brain_bonus_malus`

| Column | Type | Role |
|---|---|---|
| `id` | text | PK |
| `name_fr`, `name_en` | text | labels |
| `description` | text | author notes |
| `value` | int | points (magnitude; sign comes from `bonus_malus_type`) |
| `bonus_malus_type` | varchar(20) | `bonus` / `malus` (CHECK-constrained) |
| `rule_code` | varchar(50) | names the metric family → dispatches to a handler |
| `conditions` | jsonb | parameters for the handler |
| `scope` | varchar(20) | `interaction` / `cycle` / `session` (**added this build**, default `interaction`, CHECK-constrained) |
| `priority` | int | default 100; later categorisation, not outcome |
| `level_from`, `level_to` | int | level bounds (null = unbounded) |
| `live` | bool | |
| `created_at`, `update_at`, `airtable_record_id` | | lifecycle/sync |

### Seed rules authored
| id | rule_code | type | value | conditions | scope |
|---|---|---|---|---|---|
| `BM_ATTEMPT_EXTRA` | ATTEMPT_COUNT | malus | 5 | `{"free_threshold":1,"per_extra":true}` | interaction |
| `BM_LISTEN_EXTRA` | LISTEN_COUNT | malus | 5 | `{"free_threshold":2,"per_extra":true}` | interaction |

### Pre-existing rule to resolve
The engine surfaced a live row already in the table, **not authored in this work**: `rule_code = "rule_BOMA202410021017"`. It has no handler, so the engine skips it (fail-safe). **Decide:** give it a real handler + a recognizable `rule_code`, or set `live = false` if it's stale.

---

## 7. The metric source — `session_interaction`

The interaction-scope handlers read counters off `session_interaction`:

| Column | Feeds | State |
|---|---|---|
| `attempts_count` | ATTEMPT_COUNT | populated — rule works today |
| `listen_count` | LISTEN_COUNT | **added this build, but the client does NOT send it yet.** The app tracks `videoPlayCount` client-side but doesn't persist it. LISTEN_COUNT can't fire on real data until that plumbing exists (send at commit, or increment per listen). |

Hint usage is **not** recorded anywhere yet — a hint-usage malus needs that recording built first (the `brain_hint.bonus_malus_id` link is ready and waiting).

---

## 8. The engine — `bonus_malus_engine.py`

**Pure evaluation. It never reads or writes a score** — it computes an adjustment and hands it back. This is what lets it be tested and refined independently of the scoring rework.

```
evaluate_interaction_bonus_malus(session_interaction_id, user_level, db_pool)
  → {
      "total_adjustment": int,      # signed sum, NOT clamped
      "applied": [ {id, rule_code, name_en, adjustment} ],   # audit trail
      "skipped_rule_codes": [str],  # rules with no handler / that errored
    }
```

**Flow:** read the interaction's metric row → load live rules where `scope='interaction'` and the user's level is within bounds → dispatch each by `rule_code` to a handler → sum the signed adjustments → return with a per-rule breakdown.

**`clamp_score(gross, adjustment)`** is provided separately so the scoring task has one clamp definition (`max(0, min(100, gross + adjustment))`).

### Resilience (each matters once dozens of rules exist)
- **jsonb-as-string:** asyncpg may return `conditions` as a `str`; the loop normalises (json.loads if str, else dict).
- **Fault isolation:** each rule's evaluation is wrapped — a bad rule logs and joins `skipped_rule_codes` rather than crashing the whole score.
- **Unknown `rule_code`:** skipped with a warning (author ahead of code safely).
- **Strict sign:** only exactly `"malus"` subtracts; anything else is treated as a bonus. Safe for bonuses, risky for a mistyped malus — authored values were checked.

### The breakdown is not decoration
`applied` exists so that when a score looks wrong later, you can see exactly which rules fired and by how much. Keep it in whatever the scoring path logs.

---

## 9. Verified

Via a debug-only endpoint (`GET /api/session/debug-bonus-malus`, touches no score): a test `session_interaction` was forced to `attempts_count=3, listen_count=4`, giving `total_adjustment: -20` (ATTEMPT −10, LISTEN −10) with both rules in `applied` and the math hand-checkable. The pre-existing unhandled rule appeared in `skipped_rule_codes`, confirming the fail-safe. Row restored afterward.

---

## 10. Not built yet

- **Wiring into scoring.** The engine returns an adjustment; the scoring task applies `clamp_score(gross + total_adjustment)` at interaction commit. This is the immediate next step and is **entangled with the known voice-scoring defect** (verdict is `answer_type`-based, but the score is still similarity-based) — both belong to the scoring rework.
- **`listen_count` client plumbing** — needed before LISTEN_COUNT fires on real data.
- **Hint-usage recording** — needed before any hint malus.
- **Cycle- and session-scope evaluation** — the engine currently handles interaction scope only.
- **Categories 2–5** (answer-quality, aggregate, history, contextual) — the approach supports them; handlers and evaluation moments aren't built.
- **Airtable sync** for `brain_bonus_malus` (this build was TablePlus only).
