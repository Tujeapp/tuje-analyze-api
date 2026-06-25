# Note — Notion decay Coefficient B: calibration review (DEFERRED)

**Status:** Deferred until content is larger and real usage data exists. The code is
correct-per-spec today; this is a future *calibration* check, not a bug fix.

## What was audited (and the conclusion)
`_calculate_coefficient_b` in notion_management.py was audited line-by-line against the
spec ("Details of logic of session", the decay "coefficient B" section). It is COMPLETE
and MATCHES the spec:
- Data 1 (intro date): <=7d=0, >30d=0.2, else 0.1 — matches (604800s / 2592000s).
- Data 2 (passive rate): <0.05=0, <0.1=0.1, <0.15=0.15, else 0.2 — matches.
- Data 3 (active rate): same buckets as Data 2. NOTE: the SPEC TEXT for Data 3 is
  malformed (overlapping conditions: "<=0.1=0" AND ">0.05=0.1"). The code resolved this
  by mirroring Data 2's clean buckets. CONFIRM this interpretation when revisiting.
- Data 4 (weightiness): <=0.5=0, <=0.7=0.1, <=0.9=0.15, else 0.2 — matches.

So there is **nothing to "invert"** — the decay Coefficient B is not an inverted
calculation in the spec. (The "reverse coefficient" inversion logic — "if score positive,
1 - coef; if negative, use coef" — belongs to the per-interaction SCORE ADJUSTMENT, part
of Moment 2 / the answering system, NOT this session-start decay.)

## The actual open question (why it's deferred)
The decay looked STEEP in testing: 0.50 -> 0.15 (~70% in one session) with crafted inputs,
0.50 -> 0.25/0.30 in the live run with real coefficients. This is the formula
`new = last - last*(coefA + coefB)` working as specified — NOT a bug. But whether that
magnitude is the DESIRED learning behavior is a calibration question.

Calibrating now would be guessing, because:
- passive_rate / active_rate (Data 2/3) are 0 today (Moment 2 per-interaction tracking not
  built — it needs the answering system, deferred to a separate conversation). So Coef B
  currently runs with those inputs at 0, i.e. not at full signal.
- There's little real usage data to judge "right" decay against.

## When to revisit
After: (1) Moment 2 tracking is populating real passive/active rates, and (2) there's
enough real session/content data to observe decay over multiple sessions. Then decide:
is a notion at 0.50 supposed to drop to ~0.40, ~0.25, ~0.15 per session? Work backward
from the desired curve to recalibrate the bucket VALUES (a deliberate spec/design change),
rather than changing the structure. Also confirm the Data 3 (active rate) bucket
interpretation then.

## Where it lives
notion_management.py: `_calculate_coefficient_a` (session-wide) and
`_calculate_coefficient_b` (per-notion), consumed by `update_notion_rates_on_session_start`.
