# TuJe — Rescue System (Design Spec)

**Status: design brainstorm. Some code hooks exist (`FrustrationTracker.swift`, `RescueUIState.swift`), partly wired and diverging from intent. This doc captures the intended design and structures the open decisions for a future build. Rescue was originally specced before the hint system existed; this doc reconciles the two.**

---

## 1. Purpose

**Rescue is app-initiated help for a struggling user who is NOT helping themselves.**

The clarifying distinction:

| | Hints | Rescue |
|---|---|---|
| Initiated by | The user (they tap a hint button) | The app (it notices and steps in) |
| Signals | "I'm engaged, working this out" | "Struggling and not asking for help" |
| App's job | Serve the requested help, stay out of the way | Intervene before frustration → quitting |

A user who's stuck but **using hints** is engaged — the app leaves them alone. A user who's stuck and **not** using hints — grinding out wrong/not-understood answers — is heading toward frustration, and the app steps in.

**Rescue serves two populations with one mechanism:**
1. **The sincere learner who's genuinely stuck** — helped gently, eased toward an answer they can manage.
2. **The non-serious user gaming the mic** (just playing, never producing a usable answer) — progressively constrained into buttons until they show genuine intent.

Both are handled by the same escalation, because it's driven by "can they produce a usable (matched) answer" — which, over time, separates sincere-but-stuck from not-trying.

---

## 2. The escalation — invite → auto-switch → lock

Rescue escalates through three stages, driven by continued failure to produce a usable (matched) answer. A "failure" here = a Tier-2 (vocab-only) or Tier-3 (not understood) answer — i.e. nothing matched, nothing useful to score.

### Stage 1 — INVITE (the switch toggle)
When frustration rises to a moderate level, show a **switch toggle** below the mic button:
- A left/right control — mic on one side, multiple-buttons on the other, with a sliding circle indicating the active side.
- Tapping it lets the user **switch themselves** from voice to button answering.
- The mic stays active. This is an *invitation*, not a change — the app extends a hand.

*(This is effectively the "Layer 1" the old spec never defined.)*

### Stage 2 — AUTO-SWITCH
If the user keeps failing (still can't produce a usable answer), the app **switches automatically** to multiple buttons:
- The toggle moves to the buttons side, now positioned at the bottom of the buttons.
- The user has been moved, but the toggle is still there — they *can* switch back to mic.
- Buttons are fetched at eased ("rescue → easy") difficulty.

*(Maps to the existing `switchButton` / Layer 2.)*

### Stage 3 — LOCK
If the user switches **back to mic** and fails **again** (another Tier-2/Tier-3):
- The answer mode **locks to multiple buttons** for this interaction.
- No more switching. They must complete this interaction with buttons.
- This is the "force" endpoint — reached only after the invitation *and* the auto-switch *and* continued failure.

*(A new terminal state, beyond the existing layers.)*

**Why this shape is good:** it extends a hand first (invite), moves them if they don't take it (auto-switch), and only removes the choice after repeated demonstrated inability (lock). Gentle for the sincere learner; progressively firm for the time-waster.

---

## 3. The frustration model

`FrustrationTracker` holds a live frustration value, seeded per-interaction from the user's persistent `rescue_level`.

### Inputs that RAISE frustration
- **Failed attempt** (`recordFailedAttempt()`): +0.25, increments a per-interaction fail count.
- **(Open) Timer expiry** (`recordTimerExpired()`, +0.20): exists in code but never fired. Open question whether timer expiry should count at all.

### Inputs that LOWER frustration (NEW — from the hint distinction)
- **Hint usage** (`recordHelpTapped()`): originally specced as +0.40 (raising). **Reversed under this design** — using a hint is the "engaged" signal, so it should *reduce* frustration / suppress rescue. A user actively using hints is not a rescue candidate.
- **Success** (`recordSuccess()`) / **reset** (`reset()`): clear the state.

### History-based sensitivity (the `rescue_level` seed)
`rescue_level` (from `user_behavior`, default 0.50) persists **across sessions** and seeds the starting frustration. A user with a history of triggering rescue starts each interaction **closer to the threshold**, so frustration accrues faster for them. This is what lets rescue progressively constrain the non-serious user — repeat offenders hit the stages sooner.

---

## 4. De-escalation & persistence

- **Success** on the interaction → frustration clears.
- **Moving to a new interaction** → frustration resets (per-interaction state).
- **BUT `rescue_level` persists across sessions** — it remembers repeat-rescuers so their frustration rises faster next time.

**Open tension — does the LOCK persist?** Frustration resets per interaction, so by default the Stage-3 lock would lift at the next interaction. For the sincere-but-stuck learner, per-interaction reset is right (fresh start each time). But for the non-serious user, a per-interaction lock may be too weak to constrain them — they'd get the mic back every interaction and keep gaming it. This needs a decision (see §7).

---

## 5. Existing code & the implementation gap

**Exists:**
- `FrustrationTracker.swift` — accumulates the frustration value + per-interaction fail count.
- `RescueUIState.swift` — derived presentation state (intended: Layer 2 = switchButton, Layer 3 = buttonsAboveMic).
- Backend: `answers-by-interaction` accepts a `rescue_triggered` flag + a rescue-derived `user_level` (`rescueLevel × 500`), and the answer-selection engine picks eased ("rescue → easy") difficulty.
- Reads `rescue_level` + `always_silent` from `user_behavior` (fetch-or-create).

**The gap (known, flagged in the old spec as "Chunk 4"):** `SessionViewModel` only acts on a boolean `rescueNeeded` by calling `switchToMultipleButtons` — it **force-swaps the whole mode** and does **not** differentiate the stages (invite vs auto-switch vs lock). The intended design honors `rescueUIState` per stage. Reconciling the code to the three-stage model above is the core of the build.

**Silent is separate from rescue** — a user opts out of speaking via `declareSilentSession` / persistent `always_silent`, which forces buttons independently of any frustration. Rescue and silent must not be conflated.

---

## 6. Relationship to other systems

- **Hints** (now built): complementary, not competing. Hint use *lowers* rescue pressure (§3). The two serve different user states — engaged-and-helping-themselves vs struggling-and-not.
- **Answer modes:** rescue's whole effect is moving the user along the voice → buttons axis, at eased difficulty.
- **Scoring / bonus-malus:** no direct connection defined. (A rescued interaction still scores if it eventually gets a matched answer — via buttons. Whether triggering rescue should carry a malus is an open question, not currently intended.)
- **Tiers:** the failure signal that drives escalation is "Tier 2 or Tier 3" (nothing matched) — so rescue is tightly coupled to the matching/tier system built earlier.

---

## 7. Open decisions (resolve before building)

1. **Exact thresholds per stage.** How much frustration / how many Tier-2-3 failures move invite → auto-switch, and auto-switch → lock? The old spec had "3 fails if rescue_level < 0.5, else 1" for a single entry — now there are three stages needing their own thresholds.

2. **Does the LOCK persist beyond the interaction?** Per-interaction reset (clean, right for sincere learners) vs. persisting the lock (needed to actually constrain non-serious users). Possibly: lock is per-interaction, but repeated locks raise `rescue_level` so the next interaction starts nearly locked anyway — achieving constraint through the seed rather than a hard persistent lock. **This is the key design question.**

3. **How does `rescue_level` itself update over time?** It seeds faster accrual for repeat-rescuers, but what *writes* it? Presumably: triggering rescue (esp. reaching lock) raises it; sustained consistency (matched answers without rescue) lowers it. This update mechanism is undefined and is what makes the "constrain until they show consistency" goal actually work.

4. **Hint usage as a negative input — how much?** Confirmed it lowers frustration, but by how much, and does *any* hint tap suppress rescue for the interaction, or is it proportional?

5. **Timer expiry** — count toward frustration or not? (Old spec left open; `recordTimerExpired()` unfired.)

6. **The switch toggle UI** — needs building (the left/right mic-vs-buttons control with the sliding circle). New component. Placement: below mic (Stage 1), at the bottom of the buttons (Stage 2).

---

## 8. Build order (when we build it)

1. Settle the open decisions in §7 — especially #2 (lock persistence) and #3 (`rescue_level` update), since they define the whole behavior.
2. Build the **switch toggle** component (invite UI).
3. Wire `FrustrationTracker` → the three-stage `rescueUIState` (replacing the boolean force-swap): invite → auto-switch → lock.
4. Make hint usage a negative frustration input (`recordHelpTapped()` reversed).
5. Implement the `rescue_level` update mechanism (raise on rescue, lower on consistency).
6. Test each stage: moderate frustration shows the toggle; continued failure auto-switches; back-to-mic-then-fail locks; success/next-interaction resets; a repeat-rescuer escalates faster.

**This is a design-first, then build task** — the mechanics of the trigger exist, but the three-stage progression, the lock-persistence question, and the `rescue_level` update are the real decisions, and they should be settled before wiring.
