# TuJe — Interaction Scoring System Reference

**Status: built, wired into the voice commit path, and verified end-to-end on clean data. A perfect voice answer scored 100 through the full three-phase model.**

---

## 1. The core principle — matching and scoring are separate

The single most important thing to hold onto:

| | Matching | Scoring |
|---|---|---|
| **Job** | Given the user's answer, return *which* saved answer it matches and whether that answer is good or wrong (`answer_type`). | Produce the interaction's numeric score. |
| **Uses similarity?** | Yes — internally, to find the best match. | **Never.** |
| **Uses `answer_type`?** | Produces it. | Not for the number. Wrongness enters as a malus. |
| **Derives the score from** | — | **Levels**, then bonus-malus. |

A voice answer can be 100% similar to a saved answer (matching is confident) and still score, say, 75 — because the score comes from **levels**, not similarity. This voids the old "similarity vs verdict" concern: the score was never meant to come from similarity.

This model **replaces** the older Chunk-2 derivation (which stored an `answer_type`-based score on `similarity_score`) for the **voice/matched** path. The **button** paths keep their existing Chunk-2 scoring and are untouched — a button *is* a chosen answer, always matched.

---

## 2. Scoring is gated on a matched answer

Scoring only runs when the user gives a **matched** answer. Consequences:

- **Matched answer** → score through the three phases → complete the interaction with that score.
- **Not_understood / vocab-only (Tier 2) / no answer, and the user forces past** → the interaction is marked **incomplete** (`status = 'incomplete'`, `interaction_score = NULL`). It is *not* scored. The app uses "incomplete" later (e.g. to resurface it); it is not a scoring concern.
- **Matched but missing level data** (a content problem — shouldn't happen) → logged as a warning and marked incomplete, because no reliable score is possible.

The design rationale: unmatched attempts don't score, they only accumulate **maluses** (via the incrementing attempt/listen counts), waiting for the user to finally give a matched answer. When they do, the gross score is fresh but the accumulated maluses pull the final down — so a fumble-then-succeed user scores high gross minus the cost of the fumbles. Someone who abandons after failing is simply left incomplete, not punished with a low score. **The system is fair to those who genuinely try, not to dropped interactions.**

---

## 3. The three phases

```
A. Gross Interaction Score  =  gross_score × coefficient          (capped at 100)
B. Bonus-Malus Score        =  bonus_total − (malus_total × modulo)
C. Interaction Score        =  A + B          (rounded half-up once, clamped 0..100)
```

### Phase A — Gross Interaction Score

```
Gross Interaction Score = gross_score × coefficient        (capped at 100)
```

**gross_score:**
- **First scored answer** (interaction_score is NULL) → **100**.
- **A later matched answer** → the **prior** interaction_score (compounds — each scored answer multiplies the coefficient onto the last result).

**coefficient:**
```
((answer_opt / interaction_opt) + (answer_opt / cycle_level)) / 2
```
Rewards a higher-level answer relative to the interaction and the cycle. Levels are always ≥ 50 (never 0), so no division-by-zero — but the code guards defensively (a non-positive denominator makes that term contribute 1.0).

Three level sources:
| Level | From |
|---|---|
| `interaction_optimum_level` | `brain_interaction`, by the interaction |
| `answer_optimum_level` | `brain_answer`, via the matched `brain_interaction_answer` |
| `cycle_level` | `session_cycle.cycle_level` |

### Phase B — Bonus-Malus Score

```
Bonus-Malus Score = bonus_total − (malus_total × modulo)
```

- Bonuses at full weight; **maluses scaled by `session.modulo`** (default 0.5) — a per-session dial on how punishing maluses are.
- `bonus_total` / `malus_total` come from the bonus-malus engine as **positive magnitudes** (the engine was adjusted to return them separately, precisely because modulo applies to maluses only).

### Phase C — Interaction Score

```
Interaction Score = Gross Interaction Score + Bonus-Malus Score
```
Then **round half-up once** and **clamp to [0, 100]**.

Persisted to `session_interaction.interaction_score` — both as this answer's outcome and as the gross_score for the next attempt (phase A's compounding input).

### Two caps
1. Gross Interaction Score capped at 100 (phase A).
2. Final Interaction Score clamped [0, 100] (phase C).

### Rounding
**Half-up, applied once, to the final score only** (phases A and B stay full precision). Implemented as `math.floor(raw + 0.5)` — NOT Python's `round()`, which is banker's/half-to-even and would send ties like 88.5 → 88. A user-facing score rounds ties up.

---

## 4. Worked examples

| Inputs | Calculation | Result |
|---|---|---|
| gross 100, answer 150, interaction 150, cycle 200, no B/M | 100 × ((150/150 + 150/200)/2) = 100 × 0.875 = 87.5 | **88** |
| gross 77 (2nd answer), same levels | 77 × 0.875 = 67.375 | **67** |
| gross 100, 50/50/100, no B/M | 100 × ((1 + 0.5)/2) = 100 × 0.75 | **75** |
| gross 100, 100/100/100, no B/M | 100 × 1.0 | **100** |
| gross 100, 150/150/200, 20 malus @ modulo 0.5 | 87.5 − (20 × 0.5) = 77.5 | **78** |
| coefficient > 1 (answer 200, interaction 100, cycle 100) | 100 × 2.0 = 200, capped | **100** |

(Note: an earlier spec draft wrote example 1 as 87 — a hand-calc slip; 87.5 rounds half-up to 88.)

---

## 5. Code layout

| File | Role |
|---|---|
| `interaction_scoring.py` | **Pure functions** (no DB): `compute_coefficient`, `compute_gross_interaction_score` (cap 100), `compute_bonus_malus_score`, `compute_interaction_score` (assemble, round half-up, clamp). Unit-testable against the worked examples. |
| `bonus_malus_engine.py` | Returns `bonus_total` / `malus_total` (positive magnitudes) for phase B, plus the signed `total_adjustment` (debug). |
| `answer_split_orchestrator.py` (`commit_answer`) | The wiring: voice branch gathers the six inputs, gates on match, calls the module, writes via `complete_interaction` or `mark_interaction_incomplete`. Button branches unchanged. |
| `session_management/interaction_service.py` | `complete_interaction` (scored) and `mark_interaction_incomplete` (null score, status 'incomplete'). Both count `('completed','incomplete')` for cycle progress. |
| `cycle_manager/cycle_calculations.py` | `calculate_cycle_level` — sets the cycle level (see §7). |

**Inputs the commit path gathers for a matched voice answer:** prior `interaction_score` (or 100), `answer_optimum_level`, `interaction_optimum_level`, `cycle_level`, `bonus_total`/`malus_total` (from the engine, level-gated by cycle_level), `session.modulo`. All in one join query, with a null-guard that falls back to incomplete if the row or a level is missing.

---

## 6. Idempotency (important when testing)

`commit_answer` short-circuits if the interaction is already `completed` — it returns the existing recap **without recomputing**. So re-committing the same interaction returns the *original* score, not a fresh calculation. **To test fresh scoring code, use a never-before-committed interaction** — re-running an old one just returns its stored score.

---

## 7. The cycle-level dependency (and a fix that lives here)

The coefficient needs a real `cycle_level`. `calculate_cycle_level` sets it:
- **First cycle:** derived from the most recent *completed* session's level (± an adjustment for its direction). If no prior completed session matches, falls back to the user level.
- **Later cycles:** the prior cycle's level ± an adjustment based on that cycle's rate.

**Fix applied:** all return paths and clamps now **floor at 50** (`max(50, ...)`), because the app's minimum level is 50 and a cycle level of 0 is invalid (it distorts the coefficient). Previously the fallbacks returned an unfloored user level and clamps used `max(0, ...)`, which allowed 0.

**The `or 100` mask was removed** from `commit_answer` (`user_level = interaction["cycle_level"] or 100`) — it silently turned a 0 cycle level into 100, hiding the real bug. With the floor fix, the real value flows through.

---

## 8. A debugging lesson worth keeping

Through a long debugging chain, the scoring **code was correct the entire time**. Every wrong-looking number traced to something *around* the code:
- A 0 cycle_level (from polluted test data driving the adaptive level to the floor).
- The `or 100` mask making a 0 look like 100.
- Idempotency returning stale scores on re-runs.
- Old residue from before the deploy.

What cut through it: **running the pure scoring function with the exact DB inputs and comparing to the stored value.** That one-line test proved the module innocent and sent the search upstream to the real cause (test-data pollution + a missing level floor).

---

## 9. Open items

- **Onboarding doesn't set a starting level.** The test user's genuine onboarding sessions are all level 0 / score 0 — onboarding never establishes a real level, so the adaptive logic floors everything. Needs its own investigation; affects real new users, not just the polluted test account.
- **LISTEN_COUNT malus** can't fire until the client persists `listen_count` (only `attempts_count` populates today).
- **Hint-usage malus** — hint usage isn't recorded yet.
- **Button-path scoring** still uses the older Chunk-2 model (score off `similarity_score`); intentionally not migrated to the three-phase model, since buttons always match and score differently.
