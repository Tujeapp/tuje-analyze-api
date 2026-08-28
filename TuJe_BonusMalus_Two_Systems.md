# TuJe — Two Bonus-Malus Systems

**Status: unresolved. Two independent bonus-malus dispatch systems exist. Both are reachable. The older one is what actually adjusts interaction scores today; the newer one is the considered design and is documented as "not yet wired into scoring" — which is inaccurate, because the older one already is.**

*Discovered 2026-08-23 while wiring the `brain_bonus_malus` Airtable sync. Not a sync problem — sync work is complete and unaffected. This is a scoring-path question.*

---

## 1. Why this doc exists

`TuJe_BonusMalus_Reference.md` describes `bonus_malus_engine.py` and says, in bold: *"engine built and verified standalone (interaction scope). NOT yet wired into scoring."* Section 10 lists wiring as the immediate next step.

That doc was written as though `session_management/bonus_malus_service.py` did not exist. It does, it predates the engine, and it **is** wired into scoring.

So the reference doc is correct about the engine and silent about the thing actually running. This doc records the gap.

---

## 2. The two systems

### `bonus_malus_engine.py` — the newer design

Flat module, no class. Documented in `TuJe_BonusMalus_Reference.md`.

- `_HANDLERS` dict keyed on **uppercase**: `"ATTEMPT_COUNT"`, `"LISTEN_COUNT"`
- Dispatch at line 94: `handler = _HANDLERS.get(r["rule_code"])` — plain exact-match `.get()`, no normalisation
- Unknown `rule_code` → appended to `skipped_rule_codes`, logged as a warning, rule skipped (fail-safe)
- Reads `conditions` jsonb, normalising the asyncpg str-vs-dict quirk
- Per-rule fault isolation — a bad rule joins `skipped_rule_codes` rather than crashing the score
- `evaluate_interaction_bonus_malus()` is **pure**: computes an adjustment, never reads or writes a score
- `clamp_score(gross, adjustment)` provided separately

**Call sites (3):**
- `routers/session_router.py:22` (import), `:1021` (call)
- `answer_split_orchestrator.py:20` (import), `:738`, `:798` (calls)

Per the reference doc, verification was via a debug-only endpoint `GET /api/session/debug-bonus-malus` that "touches no score."

### `session_management/bonus_malus_service.py` — the older design

Class-based. Module docstring: *"Modular Bonus-Malus System — Each rule is independent and controlled from Airtable."*

- `BonusMalusRule` class wrapping a DB row
- `BonusMalusService` with a 5-minute rules cache (`cache_ttl_seconds = 300`)
- `load_rules()` reads from `brain_bonus_malus`
- Dispatch at lines 191–195 via **if/elif on lowercase literals**: `"streak_bonus"`, `"hint_malus"`
- Handler methods `_check_streak_bonus`, `_check_hint_malus`
- Singleton at line 298: `bonus_malus_service = BonusMalusService()`

**Call sites (1 real):**
- `session_management/scoring_service.py:9` (import), `:143` (call)
- `routers/session_router.py:20` and `answer_processing_orchestrator.py:21` also import it

---

## 3. The critical finding — the service is the one that scores

`scoring_service.py:143` sits inside `calculate_interaction_score` (method begins line 17), under a comment reading:

```
# ============================================================
# STEP 5: Apply Bonus-Malus (NOW IMPLEMENTED!)
# ============================================================
```

It calls `bonus_malus_service.calculate_bonus_malus(...)`, takes `result['total']`, adds it to the gross score, and clamps.

`calculate_interaction_score` is called from `answer_processing_orchestrator.py:367`.

**So bonus-malus adjustment is live on that path, using the service.** The reference doc's claim that wiring is "not built yet" describes the engine's status, not the system's.

---

## 4. No double-scoring

The two systems occupy separate paths and neither calls the other:

| Path | Bonus-malus source |
|---|---|
| `answer_processing_orchestrator` → `scoring_service.calculate_interaction_score` | **service** |
| `answer_split_orchestrator` → `evaluate_interaction_bonus_malus` directly | **engine** |
| `session_router:1021` → `evaluate_interaction_bonus_malus` | **engine** (likely the debug endpoint) |

One adjustment per answer, whichever path runs. This was the main risk and it is not present.

**Still unverified:** which orchestrator handles a live submitted answer today. That is the first question to answer.

---

## 5. Consequences for `rule_code` casing

The two systems use different conventions for the same column:

| System | Codes | Case |
|---|---|---|
| engine | `ATTEMPT_COUNT`, `LISTEN_COUNT` | upper |
| service | `streak_bonus`, `hint_malus` | lower |

Current data in `brain_bonus_malus` (4 rows) holds three conventions:

| id | rule_code | case |
|---|---|---|
| `BM_ATTEMPT_EXTRA` | `ATTEMPT_COUNT` | upper — hand-inserted, engine handler exists |
| `BM_LISTEN_EXTRA` | `LISTEN_COUNT` | upper — hand-inserted, engine handler exists |
| `BOMA202410020701` | `vocabulary_bonus` | lower — no handler in either system |
| `BOMA202410021017` | `rule_BOMA202410021017` | mixed — no handler, flagged in the reference doc as stale |

**Decision, pending §7 step 1:** if the engine survives, **uppercase is canonical** — `ATTEMPT_COUNT` / `LISTEN_COUNT` are its documented vocabulary. Do not lowercase.

An earlier plan in this session moved toward lowercasing, on the reasoning that lowercase is the house style elsewhere (`bonus`/`malus`, `interaction`/`cycle`/`session`). That reasoning was sound but rested on the belief that the service was dead code. It is not. **Nothing was changed** — the plan was abandoned before execution.

---

## 6. What was changed (and is safe)

One fix landed during the investigation, and it is correct regardless of which system survives.

**`BonusMalusEntry.validate_rule_code` in `airtable_routes.py` is now case-preserving.**

It previously did `.strip().lower()` on return. Since the engine's `_HANDLERS` lookup is exact-match, a rule authored in Airtable as `ATTEMPT_COUNT` was stored as `attempt_count`, matched nothing, and was silently skipped — the sync itself producing the failure mode the reference doc warns about.

The two working rules only hold correct uppercase because they were hand-inserted in TablePlus, bypassing the validator. Re-syncing either through the old validator would have broken both.

Now: regex widened `^[a-z0-9_]+$` → `^[A-Za-z0-9_]+$`, tested against `v.strip()` rather than `v.strip().lower()`, returns `v.strip()`. Empty check unchanged. The column holds exactly what the author types.

This is deliberately **not** normalisation. Silent case-correction is what made the original bug invisible. Lowercase should be enforced upstream by an Airtable single-select if it is enforced at all.

`MistakeEntry.validate_rule_code` is a separate validator on a different table — `.strip()` only, no case change, untouched.

---

## 7. Resolution sequence

Do not start by deleting anything. `bonus_malus_service` is imported by three files, and `scoring_service` — which calls it — has a dozen live call sites across `session_router` and both orchestrators. A missing module is an `ImportError` at startup.

1. **Determine which orchestrator handles live answers.** `answer_split_orchestrator` vs `answer_processing_orchestrator`. One file read. If the split path is live, the service's adjustment is already bypassed in practice and only `calculate_interaction_score` needs cleaning.

2. **Replace the call in `calculate_interaction_score`.** Swap `bonus_malus_service.calculate_bonus_malus(...)` for `evaluate_interaction_bonus_malus(...)` plus `clamp_score`. Note the return shapes differ — service returns `{"total", "applied_rules"}`, engine returns `{"total_adjustment", "applied", "skipped_rule_codes"}`.

3. **Decide the fate of the service's rules.** `streak_bonus` and `hint_malus` have handler methods but no rows in `brain_bonus_malus`. They are the reference doc's categories 4 and 1 respectively. Either port them to engine handlers or accept they were never authored.

4. **Delete `bonus_malus_service.py`** and remove its imports from `scoring_service.py`, `session_router.py`, `answer_processing_orchestrator.py`.

5. **Settle `rule_code` casing** — uppercase if the engine survives. Then create the Airtable `RuleCode` single-select with only the valid handler names as options.

6. **Update `TuJe_BonusMalus_Reference.md`** — its status line and section 10 are wrong about wiring, and it does not mention the service at all.

---

## 8. Content still outstanding on `brain_bonus_malus`

Separate from the two-systems question, from the reference doc and today's sync work:

- `BM_ATTEMPT_EXTRA` / `BM_LISTEN_EXTRA` — real working rules, hand-inserted, **not in Airtable**. Author them there or accept they are unmanaged. Note the Airtable `ID` formula may not reproduce those ids.
- `BOMA202410020701` (`vocabulary_bonus`) and `BOMA202410021017` (`rule_BOMA202410021017`) — Airtable records with placeholder codes, both `live = true`, neither has a handler. Give real codes or set `Live = No`.
- `RuleCode` cannot become a single-select until those values are valid.
- `listen_count` client plumbing — the app tracks `videoPlayCount` client-side but never persists it, so `LISTEN_COUNT` evaluates against 0 on real data.
- Hint-usage recording does not exist, so no hint malus can fire. `brain_hint.bonus_malus_id` is ready and waiting.

---

## 9. Method note

Two conclusions in this investigation were wrong before being corrected, both from trusting command output that had not actually run:

- A `grep --include=*.py` failed on zsh glob expansion and returned an error read as "no results" — leading to "nothing imports `bonus_malus_service`," which was false. Quote the glob: `--include="*.py"`.
- A separate conversation ran `ls | grep -i bonus` in the repo root, did not recurse into `session_management/`, and concluded the service does not exist.

Both times the fix was to run a differently-scoped command and compare. Worth remembering: an empty result and a failed command look identical in a paste.
