# TuJe — Rescue System Reference

**Status: BUILT and verified end-to-end on device (frustration brain, button generation, persistence, four-state view layer). This is the authoritative "as-built" reference. The older `TuJe_Rescue_System_Spec.md` holds the design history and is superseded by this document for current behavior.**

---

## 1. What rescue is

**Rescue is app-initiated help for a struggling user who is NOT helping themselves.**

| | Hints | Rescue |
|---|---|---|
| Initiated by | The user (taps a hint) | The app (notices and steps in) |
| Signals | "I'm engaged, working it out" | "Struggling and not asking for help" |
| Job | Serve requested help, stay out of the way | Intervene before frustration → quitting |

A user stuck but **using hints** is engaged → the app leaves them alone. A user stuck and **not** using hints — grinding out wrong/not-understood answers — is heading toward quitting → the app steps in.

**Two populations, one mechanism:**
1. The **sincere-but-stuck** learner — eased gently toward an answer they can manage.
2. The **non-serious mic-gamer** (never produces a usable answer) — progressively constrained into buttons until they show good will. If they never do, they stay locked — an accepted outcome (TuJe isn't for mic-players).

**Silent mode is separate** — a user opts out of speaking via `declareSilentSession` / persistent `always_silent`, forcing buttons independently of frustration. Never conflated with rescue.

---

## 2. The frustration ladder (numeric, FINAL)

Live frustration is a value in [0, 1] within an interaction. Four bands, each with a distinct UI state (`RescueUIState`):

| Live frustration | `RescueUIState` | Stage | UI |
|---|---|---|---|
| 0 – 0.39 | `.none` | normal | **mic only** |
| 0.4 – 0.59 | `.switchButton` | **invite** | **mic + toggle** (offer buttons; mic stays) |
| 0.6 – 0.79 | `.buttonsAboveMic` | **auto-switch** | **buttons + toggle** (app switched; can toggle back) |
| 0.8 – 1.0 | `.locked` | **lock** | **buttons only** (toggle hidden; no return to mic) |

Above 0.8 it can still climb to 1.0. The user must earn frustration back below 0.8 to escape lock.

**Always mic XOR buttons — never both.** The toggle is the only thing that controls which is shown. (An earlier "buttons above mic" rendering that showed both at once was removed — it contradicted this model.)

**The invite does NOT force-swap.** At 0.4 the mic stays active and the toggle is merely offered. Only auto-switch (0.6) and lock (0.8) actually flip the mode to buttons. Accepting the invite toggle is the user's choice to get help early.

**Lock is terminal (within the interaction).** At 0.8 the toggle is hidden AND `switchBackToVoice()` hard-guards `.locked` (early return) — so there is genuinely no path back to the mic. It resets on the next interaction via the carried floor (§4).

---

## 3. Within-interaction increments

Applied to live frustration, all clamped [0, 1]:

| Event | Δ |
|---|---|
| Tier 3 voice answer (not understood) | **+0.2** |
| Tier 2 voice answer (vocab only) | **+0.1** |
| Tier 1 voice answer (matched) | **0**, or **−0.1** if frustration > 0 |
| Hint used | **−0.1** (good-will signal — reversed from the old +0.40) |
| Answer with buttons in invite band (0.4–0.59) | **−0.1** |
| Answer with buttons in auto-switch band (0.6–0.79) | **−0.1** |

Good behavior (matches, hints, accepting buttons) pulls frustration DOWN; Tier-2/3 failures push it UP. Bands are a live tug-of-war and are **non-monotonic** — frustration (and the UI state) can fall back through bands as the user recovers.

Failures that drive escalation are Tier 2/3 (nothing matched) — rescue is coupled to the matching/tier system.

---

## 4. The floor / carry-over across interactions (`rescue_level`)

`rescue_level` (in `user_behavior`, [0,1], **new-user default 0.0**) is the persistent **starting floor** each interaction resets to.

**Carry-over rule:** each new interaction starts at `previous_interaction_ending_frustration − 0.1`, clamped [0,1]. This single rule produces the whole progressive-lock-but-recoverable behavior:
- A struggler who recovers is walked back toward 0 (−0.1/interaction passive decay + active decreases from good answers).
- A non-serious gamer who ends ~0.9 starts the next interaction ~0.8 — pre-locked from the first answer — and stays there until they show good will faster than failures climb.
- A cruising proper user stays at 0 (`0 − 0.1` clamps to 0).

The floor can reach the pre-locked zone (≥0.8) — that's how a bad interaction makes the next start pre-locked. Persisted across sessions, so a returning rescuer starts where they left off (minus the 0.1 decay).

---

## 5. As-built — client (iOS)

**`RescueUIState.swift`** — enum, four cases mapped to the bands: `.none`, `.switchButton`, `.buttonsAboveMic`, `.locked`.

**`FrustrationTracker.swift`** — the frustration brain (numeric band model, `@MainActor`, pure). Key API:
- `init(floor:)` — seeded from the carried floor.
- `recordTier1/2/3()`, `recordHintUsed()`, `recordButtonsAcceptedInInvite()`, `recordButtonsInAutoSwitch()` — the increments (§3), each clamps + recomputes the band.
- `endingFrustration() -> Float` — the current value, read at interaction end to compute the next floor.
- `reset(toFloor:)` — reset for a new interaction to the carried floor.
- Band computed from the live value each recompute (NOT monotonic — can fall through bands). `rescueNeeded = (state != .none)`.

**`SessionViewModel.swift`** (`@MainActor`):
- Both voice submit paths map the evaluate result's tier → `recordTier1/2/3()`.
- Both button-submit paths ease frustration when in a rescue band (adaptive path; legacy frozen).
- **Invite does not force-swap** — only `.buttonsAboveMic`/`.locked` auto-call `switchToMultipleButtons`.
- `switchToMultipleButtons(rescueTriggered:)` — passes `rescueTriggered || inRescue`, so a MANUAL toggle tap in a rescue band fetches the quick-help GENERATED buttons (not the empty `is_button` path); also syncs `rescueUIState`.
- `switchBackToVoice()` — guards `.locked` (early return); refreshes `rescueUIState`.
- New-interaction reset blocks compute the carried floor (`ending − 0.1`) and `reset(toFloor:)`.
- `advanceAdaptive()` sends the decayed floor to the backend (persistence, §6).

**`SessionView.swift`** — four-state rendering keyed off `rescueUIState` ALONE (untangled from `currentAnswerMode`):
- The toggle (a capsule button for now) shows for `.switchButton` + `.buttonsAboveMic`, hidden for `.none` + `.locked`.
- The main answer control renders mic (`.voice`) or buttons (`.multipleButtons`) — mode follows the band.
- *(The sliding-circle toggle visual is deferred — behavior-first; the capsule works.)*

---

## 6. As-built — backend & persistence

**Button generation for rescue's response** (see the button-engine reference): when rescue presents buttons, `answers-by-interaction?rescue_triggered=true` routes through `curate_quick_help`, which realizes entity-templates into legible buttons. The level for realization is derived server-side from `session_interaction → session_cycle → cycle_level` (NOT the client-sent `user_level`, which for rescue is the frustration floor and would be too low). This closed the original "no buttons to switch to" gap.

**Persistence** — the carried floor survives across sessions:
- Client `advanceAdaptive` computes `floorToPersist = max(0, min(1, endingFrustration() − 0.1))` (read before the next interaction's reset overwrites the tracker) and sends it as `rescue_level` on `/advance-interaction`.
- Backend upserts `user_behavior.rescue_level` (`ON CONFLICT (user_id) DO UPDATE SET rescue_level = EXCLUDED.rescue_level, updated_at = now()`).
- New-user default is 0.0 everywhere (both fetch-or-create INSERT seeds, both return variables, and the DB column default).
- Session start reads it back to seed the tracker.

---

## 7. Verified

- **Escalation (live):** clean user, four not_understood voice answers → 0.00 → 0.20 → 0.40 → 0.60 → 0.80, bands flipping at exactly 0.4/0.6/0.8.
- **Button generation in-app:** frustration → 0.6 auto-switch → generated quick-help buttons rendered (the interaction that used to return `[]`) → tapped correct → scored.
- **Persistence:** built frustration, advanced → `user_behavior.rescue_level` = `ending − 0.1`; new session seeded from the persisted floor (returning rescuer starts elevated).
- **Four-state view (device):** walked to lock — buttons only, toggle gone, no path back to mic.

---

## 8. Deferred / open (optional, not blocking)

- **Sliding-circle toggle visual** — the left/right mic↔buttons control with a sliding indicator. Behavior-first was the deliberate call; the capsule toggle is in place. Polish later.
- **Timer expiry feeding frustration** — `recordTimerExpired` exists but is unfired; open whether idle/timeout should raise frustration.
- **Within-interaction de-escalation UI walk-back** — the brain steps states down (non-monotonic), but seeing the UI walk *backward* through bands mid-interaction wasn't explicitly device-tested (cross-interaction de-escalation via the floor IS proven). Low priority.
- **Rescue ↔ scoring** — a button reached via rescue currently scores through the button path; whether triggering rescue should carry any scoring signal is undecided (not currently intended).
- **entityNumber user-metadata reuse** and other button-engine enrichments — see the button-engine reference.

---

## 9. Key files

- Client: `RescueUIState.swift`, `FrustrationTracker.swift`, `SessionViewModel.swift`, `SessionView.swift`, `APIService.swift` (advance sends `rescue_level`).
- Backend: `answer_selection_service.py` (rescue branch → `curate_quick_help`), `button_realization.py` (generation), `routers/session_router.py` + `session_management_router.py` (persistence upsert + 0.0 defaults).
- Design history: `TuJe_Rescue_System_Spec.md` (superseded by this reference for current behavior).
