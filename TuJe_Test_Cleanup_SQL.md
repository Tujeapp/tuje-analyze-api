# TuJe — Test Session Cleanup SQL

**Purpose:** the adaptive level logic reads the test user's session history to compute cycle levels. Abandoned/incomplete test sessions drag the level to the floor (the app correctly reads repeated quitting as "lower this user"). Run this cleanup after each test session so the level logic sees only clean completed history.

**Test user:** `D08BC99B-0996-4E2B-B4FB-80CF9E0B33DC`

---

## The cleanup (run in TablePlus, safe to run repeatedly)

Deletes all **active** and **incomplete** sessions and their children for the test user. **Preserves completed sessions** (onboarding history + `SESSION_SEED_LEVEL100`). Child-first, so no foreign-key errors. Idempotent — on a clean slate it deletes 0 rows and errors nothing.

```sql
-- 1. session_answer by session_id (dual FK: session_answer links both session_id AND interaction_id)
DELETE FROM session_answer
WHERE session_id IN (
  SELECT id FROM session
  WHERE user_id = 'D08BC99B-0996-4E2B-B4FB-80CF9E0B33DC'
    AND status IN ('active','incomplete')
);

-- 2. session_answer by interaction_id
DELETE FROM session_answer
WHERE interaction_id IN (
  SELECT si.id FROM session_interaction si
  JOIN session_cycle sc ON si.cycle_id = sc.id
  JOIN session s ON sc.session_id = s.id
  WHERE s.user_id = 'D08BC99B-0996-4E2B-B4FB-80CF9E0B33DC'
    AND s.status IN ('active','incomplete')
);

-- 3. session_interaction
DELETE FROM session_interaction
WHERE cycle_id IN (
  SELECT sc.id FROM session_cycle sc
  JOIN session s ON sc.session_id = s.id
  WHERE s.user_id = 'D08BC99B-0996-4E2B-B4FB-80CF9E0B33DC'
    AND s.status IN ('active','incomplete')
);

-- 4. session_cycle
DELETE FROM session_cycle
WHERE session_id IN (
  SELECT id FROM session
  WHERE user_id = 'D08BC99B-0996-4E2B-B4FB-80CF9E0B33DC'
    AND status IN ('active','incomplete')
);

-- 5. session
DELETE FROM session
WHERE user_id = 'D08BC99B-0996-4E2B-B4FB-80CF9E0B33DC'
  AND status IN ('active','incomplete');
```

---

## Verify (optional, after cleanup)

```sql
SELECT status, COUNT(*) FROM session
WHERE user_id = 'D08BC99B-0996-4E2B-B4FB-80CF9E0B33DC'
GROUP BY status;
```
Should show only `completed` (7 at last count, growing as real test sessions complete). No `active`, no `incomplete`.

---

## Recommended test loop

1. Run a test session in the app.
2. Run the cleanup block above.
3. Start a fresh session — the first cycle derives its level from clean completed history (anchored by `SESSION_SEED_LEVEL100` at level 100), so cycle levels and scores compute sensibly.

---

## Important notes

- **`SESSION_SEED_LEVEL100` is LOAD-BEARING — do not delete it.** It's the level-100 completed session that `calculate_cycle_level`'s first-cycle path reads to derive a real starting level. Without it (and with onboarding not yet setting a real level), fresh cycles would floor to 50. (Earlier notes said "delete the seed when done testing" — that is superseded; keep it.)

- **`brain_user.level` was set to 100** for the test user. If it drifts back to 0 (e.g. after a stretch of abandoned sessions before you clean up), reset it:
  ```sql
  UPDATE brain_user SET level = 100
  WHERE id = 'D08BC99B-0996-4E2B-B4FB-80CF9E0B33DC';
  ```

- **The `incomplete` inclusion is right for now** (your incompletes are test junk). Once incomplete interactions become meaningful data you want to keep, narrow the cleanup to `status = 'active'` only.

- **Idempotency reminder:** re-committing an already-completed interaction returns its stored score without recomputing. To test fresh scoring, always use a new interaction, not a re-run.
