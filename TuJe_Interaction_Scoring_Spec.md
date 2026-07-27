# TuJe — Interaction Scoring Finalization (Design Spec)

**Status: design only. Not built. This spec reconciles the intended scoring model with the existing code and the bonus-malus engine, and defines exactly what changes.**

---

## 0. The core principle — two separate systems

The single most important framing, and the thing that resolves prior confusion:

**Matching and scoring are separate systems.**

| | Matching | Scoring |
|---|---|---|
| **Job** | Given the user's answer, return *which* saved answer it matches and whether that answer is good or wrong (`answer_type`). | Produce the interaction's numeric score. |
| **Uses similarity?** | Yes — similarity is a tool *inside* matching to find the best match. | **No.** Never. |
| **Uses `answer_type`?** | It *produces* it. | Not for the gross number. Wrongness enters later, as a malus. |
| **Derives the score from** | — | **Levels** (optimum levels + cycle level), then bonus-malus. |

Matching's job ends at "here's the matched answer + its `answer_type`." Scoring takes that match as its starting input and computes a number from a completely different basis.

**Consequence — the "similarity vs verdict" concern is void.** Earlier worry: "a voice answer 95% similar to a *wrong* answer scores 95 but verdicts wrong." Under this model the score was never meant to come from similarity. A wrong-but-matched answer still gets a gross score from its levels; its wrongness will be expressed as a **malus** in phase 2, not by suppressing the gross score.

**Consequence — this REPLACES the current score derivation.** The existing commit path (Chunk 2) derives a score from `answer_type` and stores it on the answer's `similarity_score`, then `commit` reads it back (`answer_split_orchestrator.py` ~lines 539–552, 662–679). That is a *different, older* scoring approach. This model supersedes it. Finalizing scoring = swapping the derivation, not patching it.

---

## 1. The three phases

For every user answer to an interaction, the interaction score is computed in three phases:

```
A. Gross Interaction Score  =  Gross Score  ×  Coefficient
B. Bonus-Malus Score        =  Σbonus  −  (Σmalus × Modulo)
C. Interaction Score        =  Gross Interaction Score  +  Bonus-Malus Score        (clamped)
```

The gross score is computed for **any** matched answer — perfect or wrong. Correctness does not gate it.

---

## 2. Phase A — Gross Interaction Score

```
Gross Interaction Score = Gross Score × Coefficient        (rounded to integer)
```

### Gross Score (the base that gets multiplied)
- **First answer of this interaction:** default **100**.
- **Not the first answer:** the **previously calculated interaction score** (`session_interaction.interaction_score`). So repeated attempts *compound* — each answer scores off the last, and the coefficient applies again.

This is why `interaction_score` must be **persisted and read back**. On answer N, the gross score is the interaction_score left by answer N−1.

### Coefficient
```
Coefficient = ((answer_opt_level / interaction_opt_level) + (answer_opt_level / cycle_level)) / 2
```

Three levels feed it:
| Level | Source |
|---|---|
| `interaction_optimum_level` | `brain_interaction`, by current interaction id |
| `answer_optimum_level` | `brain_answer`, via the matched `brain_interaction_answer` → `brain_answer` |
| `cycle_level` | the current cycle/session level (confirm exact source at commit) |

The coefficient rewards answering with a **higher-level answer** relative to the interaction and the cycle. An answer at or above the interaction's level, in a cycle at or below the answer's level, scores near or above 1.0.

### Worked examples (from the spec)
First answer:
```
Gross = 100, interaction_opt = 150, answer_opt = 150, cycle = 200
100 × (((150/150) + (150/200)) / 2) = 100 × ((1 + 0.75)/2) = 100 × 0.875 = 88
```
Second answer (prior interaction_score was 77):
```
Gross = 77, same levels
77 × 0.875 = 67
```

### Edge cases to nail down in the build
- **Division by zero:** if `interaction_optimum_level` or `cycle_level` is 0 or null, the coefficient breaks. Need a defined fallback (skip that term? treat as 1.0? clamp?).
- **Coefficient > 1:** if the answer level exceeds both the interaction and cycle levels, the coefficient exceeds 1 and the gross interaction score can exceed the gross score (a reward). Confirm this is intended and whether it's clamped before or only at phase C.
- **No matched answer (not_understood):** there is no `answer_optimum_level`. Does the interaction still score (gross → something), or is scoring skipped entirely for an unmatched answer? **Open question — needs an answer.**

---

## 3. Phase B — Bonus-Malus Score

```
Bonus-Malus Score = Σ(bonus values) − (Σ(malus values) × Modulo)        (rounded)
```

- Collect every bonus and malus triggered for this interaction.
- **Bonuses and maluses are summed separately.**
- The malus total is scaled by **Modulo** before subtraction; bonuses are not.

### Modulo
Already exists: `session.modulo` (default 0.5, set per session; the returning-user path sets it). It damps the malus impact — a session-level dial on how punishing maluses are. Read it from the session at commit.

### ⚠️ This requires a change to the bonus-malus engine
The engine we built returns a single signed `total_adjustment` (bonuses and maluses already netted together). **This model needs them separate**, because Modulo applies only to maluses. So:

- Adjust `evaluate_interaction_bonus_malus` to return **`bonus_total`** and **`malus_total`** (both positive magnitudes) *in addition to* (or instead of) the netted `total_adjustment`.
- The `applied` breakdown already carries per-rule signed adjustments and `bonus_malus_type` context, so splitting the sum by type is a small change.
- Phase B then computes `bonus_total − (malus_total × modulo)`.

Everything else about the engine (rule loading, `rule_code` dispatch, `conditions`, fault isolation) stays as built.

### Where bonuses/maluses come from (future — not all built)
- `brain_interaction_answer` linked bonus/malus (the answer itself carries some)
- behavioural rules (attempts, listens — the two we built; hints later)
- contextual (date, time, session moment)
- "weird answer" detections, gift bonuses for motivation
- Only the **behavioural** category (ATTEMPT_COUNT, LISTEN_COUNT) is implemented today. A **wrong-answer malus** will live here — that's how wrongness reduces the score.

---

## 4. Phase C — Interaction Score

```
Interaction Score = Gross Interaction Score + Bonus-Malus Score
```

Then **clamp to [0, 100]** (use the engine's `clamp_score` definition so there's one clamp everywhere).

Persist the result to `session_interaction.interaction_score` — both as the answer's outcome *and* as the gross score for the next attempt (phase A's compounding input).

---

## 5. What changes in the code

### Replace (the current derivation)
- The Chunk-2 `answer_type → (score, verdict)` mapping that sets the score (~lines 539–552) — the **verdict** part stays (matching still needs it), but the **score** it produces is superseded by phase A.
- The commit-path reads that pull the score back off `similarity_score` (~lines 662–679) — replaced by reading `interaction_score` and the new phase calculation.
- Keep `similarity_score` doing its real job (matching), stop overloading it as a score carrier.

### Add
- A **scoring module** (or extend `scoring_service`) with:
  - `compute_gross_interaction_score(gross, interaction_opt, answer_opt, cycle_level)`
  - phase B consumption of the split bonus/malus totals × modulo
  - phase C assembly + clamp
- Read the three levels + prior `interaction_score` + `session.modulo` at commit.
- Adjust the bonus-malus engine to expose `bonus_total` / `malus_total`.

### Confirm before building
- `session_interaction.interaction_score` exists (the persistence target).
- The cycle level is reachable at commit (which record/column).
- The matched `brain_interaction_answer → brain_answer.answer_optimum_level` join is available where scoring runs.

---

## 6. Open questions (resolve before building)

1. **Unmatched answer (not_understood):** no `answer_optimum_level`. Does the interaction still score (and how — gross stays as prior/100 with coefficient skipped?), or is scoring skipped for that attempt? **Most important open question.**
2. **Coefficient div-by-zero / null levels:** defined fallback?
3. **Coefficient > 1:** intended reward, clamped only at phase C?
4. **First-vs-not-first detection:** is "first answer" determined by `interaction_score IS NULL` on the session_interaction, or by `attempts_count`, or another flag?
5. **Does phase A round before phase C, or only at the end?** (The spec rounds the gross interaction score to integer, then adds the rounded bonus-malus score — so two rounding points. Confirm.)

---

## 7. Build order (when we build it)

1. Confirm the three schema/reachability items in §5.
2. Adjust the bonus-malus engine → `bonus_total` / `malus_total`.
3. Build the scoring module (phases A/B/C) as pure functions, unit-testable with the spec's worked examples (87, 67).
4. Wire into the three commit paths (voice, multi-button, single-button), reading levels + prior score + modulo.
5. Verify against the worked examples on real interactions, then with maluses firing (the forced attempts/listens test), confirming `interaction_score` persists and compounds on a second attempt.

This is a full task on its own — the engine adjustment plus a new scoring module plus rewiring three commit paths plus compounding persistence. Best done fresh, not rushed.
