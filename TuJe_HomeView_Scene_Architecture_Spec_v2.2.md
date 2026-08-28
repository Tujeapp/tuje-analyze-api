# TuJe — HomeView Parisian Scene
## Scene Architecture Specification

**Version:** 2.2
**Supersedes:** v1.0, v2.0, v2.1
**Status:** Sections 1–11 and 14 measured and verified on device. Sections 12–13 still design-only.
**Scope:** Client-side rendering architecture for the HomeView Parisian scene (iOS / SwiftUI)
**Out of scope:** The engine that decides scene content (user data, weather, season, special days). That is a separate system, deliberately designed *after* the view's capabilities are known.

---

## 0. What changed since v1.0

v1.0 was written before any code existed. Building P1–P5 invalidated several of its assumptions and produced measured numbers where v1.0 had estimates.

| Area | v1.0 said | v2.0 says | Why |
|---|---|---|---|
| Parallax formula | `offsetY × depth` | `(offsetY − neutralOffsetY) × depth` | v1.0's formula collapses all planes into alignment at full tilt-up — zero separation exactly where the design needs the most |
| Canvas multiplier | 1.8× | **2.30×** | Tuned on device against the designer's three reference views |
| Depth coefficients | 0.55 → 0.00, clustered | 0.77 → 0.00, widely spread | v1.0's spread was too narrow to perceive |
| Multi-angle renders | Open question (O2) | **Rejected for v1** | Memory budget cannot afford 5× |
| Dormant state | Open question (O1) | **Still open**, deliberately | Deferred until real artwork exists |
| Performance | Estimated | **Measured on iPhone SE 2022** | See §10 |
| Animation mechanism | Unspecified | **Pure functions of elapsed time** | Implicit `.animation` failed silently — see §8.1 |
| Visible area per plane | Not considered | **§6 — new section** | Caused a real bug: elements permanently invisible |

---

## 1. Decision register

### LOCKED

| # | Decision | Value |
|---|---|---|
| L1 | Viewport position persists while on HomeView | Free position, clamped |
| L2 | Viewport resets to neutral after absence | 30-minute threshold |
| L3 | No elastic spring-back during interaction | Position holds where released |
| L4 | Parallax is anchored to the neutral position | `(offsetY − neutralOffsetY) × depth` |
| L5 | Horizontal parallax is gyroscope-driven | Not yet built |
| L6 | Gyro constants are placeholders until measured | Debug panel exists |
| L7 | Layers ship content-cropped with position metadata | Never full-canvas |
| L8 | Anything expressible natively is drawn, not shipped | Sky, tints, fog |
| **L9** | **All animation is a pure function of elapsed time** | **No implicit `.animation`** — §8.1 |
| **L10** | **Physically attached elements share a depth coefficient** | `frontDetail == front`; `water == street` |
| **L11** | **Every element must sit inside its plane's visible band** | §6 |
| **L12** | **Multi-angle renders rejected for v1** | Single centre render + offset parallax |
| **L13** | **Soft edges are the dominant render cost** | §11.5 |
| **L14** | **Scene cost budget** | **600 units**, single technique-weighted axis — §11.5, §14.5 |
| **L15** | **Texture variety is free; sprite count is not** | Commission reusable, parameterisable sheets — §11.7 |

### OPEN

| # | Question | Status |
|---|---|---|
| O1 | Dormant state: runtime filter, hand-authored, or hybrid? | **Deferred to real artwork.** Runtime filtering assumed — the reversible choice |
| O4 | Which Home view is the destination? | `Views/HomeView.swift` (tab) vs `Views/Onboarding/HomePlaceholderView.swift`. Unresolved |
| O5 | Does the 2.30× travel read as camera tilt or scroll? | Never explicitly confirmed |

### RESOLVED

| # | Question | Answer |
|---|---|---|
| O2 | Multi-angle renders? | **No.** 5× memory unaffordable. Offset parallax reads convincingly |
| O3 | Canvas multiplier? | **2.30×** (roof 0.72 + neutral 1.0 + water 0.58) |

---

## 2. Reference device and coordinate system

All dimensions in **logical points** unless marked px.

**Performance reference device:** iPhone SE 2022 — 375 × 667 pt, @2x, A15, **60 Hz display**
**Layout reference device:** iPhone 15 Pro — 393 × 852 pt, @3x
**Support range:** 375 × 667 through 430 × 932

> **The simulator cannot measure performance.** It compiles for the Mac's architecture and renders on the Mac's GPU. Selecting "iPhone 16" changes screen dimensions and idioms only. All performance figures in this document come from a physical SE 2022.

> **ProMotion caution:** the SE runs at 60 Hz (16.7 ms budget). iPhone Pro models run at 120 Hz (8.3 ms budget). A scene comfortable on the SE may drop frames on a *newer* device attempting twice the frame rate. Headroom on better hardware is not guaranteed.

### 2.1 Axis conventions

- `offsetY` — vertical camera position. **Increasing moves the camera down** (reveals water)
- `delta` — `offsetY − neutralOffsetY`. Zero at neutral. The parallax driver
- `tiltX` — normalised gyroscope roll, −1.0 … +1.0
- `zoom` — scale factor (deferred, not built)

---

## 3. Layer stack and depth coefficients

Render order is fixed, back to front. These coefficients were tuned on device.

| # | Plane | Contents | **Depth** | Density tier |
|---|---|---|---|---|
| 0 | `sky` | Gradient, clouds, birds, time-of-day | **0.77** | Native |
| 1 | `far` | Furthest building band | **0.70** | C |
| 2 | `midBack` | Middle hidden building band | **0.55** | B |
| 3 | `mid` | Third band, Eiffel Tower | **0.35** | B |
| 4 | `front` | Front building band, cars | **0.16** | B |
| 5 | `frontDetail` | Chimneys, smoke, windows | **0.16** | A |
| 6 | `street` | Near quai, figures | **0.00** | A |
| 7 | `water` | Seine surface, boats | **0.00** | B |

Higher coefficient = further away = moves *less* relative to the viewport.

### 3.1 Attachment invariants (L10)

Two pairs must never diverge:

**`frontDetail` must equal `front`.** Chimneys and windows are painted onto the front facades — the same physical surface. Any difference makes windows slide across the wall they belong to.

**`water` must equal `street`.** If they differ, they separate on tilt-down, opening a gap between the bottom of the front buildings and the top of the water — through which the viewer sees behind the scene. **The bottom of the composition must never open a gap.**

These are enforced by `ScenePlane.assertDepthInvariants()`, called in debug builds.

> **Generalisation for future elements:** any element painted onto, attached to, or resting on another element must share its depth coefficient. Depth separation is only valid between things that are genuinely at different distances.

---

## 4. Canvas geometry

### 4.1 Ratios

```
roofTravelRatio        = 0.72
waterTravelRatio       = 0.58
canvasHeightMultiplier = 1.0 + 0.72 + 0.58 = 2.30      (derived, never hardcoded)
```

### 4.2 Derived values

```
canvasHeight   = screenHeight × 2.30
maxOffsetY     = canvasHeight − screenHeight  = screenHeight × 1.30
neutralOffsetY = screenHeight × 0.72
```

| Device | screenH | canvasH | neutralOffsetY | maxOffsetY |
|---|---|---|---|---|
| iPhone SE 2022 | 667 | 1534 | 480 | 867 |
| iPhone 15 Pro | 852 | 1960 | 613 | 1108 |
| iPhone 15 Pro Max | 932 | 2144 | 671 | 1212 |

### 4.3 Zone layout

```
canvasY 0.000  ┌─────────────────────────┐
               │      ROOF ZONE          │  0.313 of canvas
canvasY 0.313  ├─────────────────────────┤  ← viewport top at neutral
               │     NEUTRAL ZONE        │  0.435 of canvas
canvasY 0.748  ├─────────────────────────┤  ← viewport bottom at neutral
               │      WATER ZONE         │  0.252 of canvas
canvasY 1.000  └─────────────────────────┘
```

### 4.4 The three canonical views

Derived from the designer's reference mockups and verified numerically.

**NEUTRAL** (`offsetY = neutralOffsetY`, `delta = 0`)
- Thin sky strip at top: 2.5% through the roofline peaks, opening to 10.0% through the valleys
- Front buildings dominate
- Thin water strip at bottom: ~3%
- **All three hidden building bands completely invisible**

**TOP** (`offsetY = 0`)
- Sky occupies top ~33%
- `far`, then `midBack`, then `mid` emerge in a receding stack
- Front buildings occupy bottom ~33%
- No water, no quai

**BOTTOM** (`offsetY = maxOffsetY`)
- Front buildings top ~19%, roofline off the top edge
- Water dominates ~63%
- Near quai bottom ~18%
- Sky and hidden bands occluded (not off-screen — see §11.3)

---

## 5. Depth model — vertical axis

### 5.1 The formula (L4)

```
delta        = offsetY − neutralOffsetY
canvasOffset = −offsetY                       (applied to the whole canvas)
planeOffset  = delta × plane.depth            (applied to each plane)
```

Net apparent movement of a plane is `offsetY × (1 − depth)`, but *separation between planes* is driven by `delta`, not `offsetY`.

### 5.2 Why neutral-anchored (this is the single most important line in the module)

v1.0 specified `offsetY × depth`. At `offsetY = 0` — full tilt up — every plane's offset is zero and **all eight planes collapse into perfect alignment.** Maximum separation occurred at the bottom, minimum at the top: exactly inverted from the design intent.

With neutral anchoring:

- At neutral, `delta = 0`. Every plane sits exactly where authored. **Separation is zero and the composition is authoritative.**
- Moving away in *either* direction separates planes differentially.
- Tilting up: deeper planes shift more, so background emerges from behind foreground.

This also gives "neutral" a real meaning: the one position where the scene is exactly as composed. That is what an artist designs against.

> **Do not "simplify" this back to `offsetY × depth`.** The code carries a comment block saying so.

### 5.3 Occlusion at neutral

The front roofline valley line is the occlusion threshold. Every hidden band's topmost point must sit below it in canvas space.

| Band | Top (canvas fraction) | Margin below front valley (0.328) |
|---|---|---|
| `mid` | 0.334 | 12.8 pt — **tightest tolerance in the layout** |
| `midBack` | 0.344 | 34 pt |
| `far` | 0.358 | 64 pt |

The 12.8 pt margin on `mid` is fragile. It holds for placeholder geometry with a clean zigzag roofline; **real artwork with irregular rooflines will need a larger margin.** Recommend ≥ 40 pt equivalent when authoring real assets.

---

## 6. Visible bands — the authorable region per plane

**New in v2.0. This section exists because its absence caused a real bug: three birds and three clouds were placed outside their plane's reachable area and were permanently invisible at every camera position.**

### 6.1 The principle

Because each plane lags the camera by its depth coefficient, **only part of the canvas ever passes through the viewport for that plane.** A deeper plane has a *narrower* authorable band.

Placing an element outside its plane's band means it is rendered every frame, costs performance, and can never be seen.

### 6.2 The formulas

Solving `screen_y = f × canvasH − offsetY + delta × d` for the range of `f` visible at some valid `offsetY`:

```
bandLower(d) = roofTravelRatio  × d / canvasHeightMultiplier   = 0.313 × d
bandUpper(d) = 1 − (waterTravelRatio × d / canvasHeightMultiplier) = 1 − 0.252 × d
```

**These are device-independent.** Screen height cancels out. The bands depend only on depth and the two travel ratios — so changing `roofTravelRatio` or `waterTravelRatio` changes every plane's authorable region.

### 6.3 Current bands

| Plane | Depth | Band lower | Band upper | Width |
|---|---|---|---|---|
| `sky` | 0.77 | **0.241** | **0.806** | 0.565 |
| `far` | 0.70 | 0.219 | 0.824 | 0.605 |
| `midBack` | 0.55 | 0.172 | 0.861 | 0.689 |
| `mid` | 0.35 | 0.110 | 0.912 | 0.802 |
| `front` | 0.16 | 0.050 | 0.960 | 0.910 |
| `frontDetail` | 0.16 | 0.050 | 0.960 | 0.910 |
| `street` | 0.00 | 0.000 | 1.000 | 1.000 |
| `water` | 0.00 | 0.000 | 1.000 | 1.000 |

### 6.4 Consequences

**For the artist brief:** an instruction like "place this at canvas y 0.14" is meaningless without naming the plane. On the sky plane, 0.14 does not exist. **This table must appear in the artist brief**, and every layer's `canvasRect` must be validated against its plane's band.

**For the code:** the registry (§14) must reject or warn on any element placed outside its band. Known outstanding violation: three of the six sky clouds sit above 0.241 and are permanently invisible while still costing a blur each.

---

## 7. Viewport behaviour

### 7.1 Vertical drag

```
offsetY -= dragDeltaY / zoom
offsetY  = clamp(offsetY, 0, maxOffsetY)
```

No spring-back. Hard clamp at both ends — no rubber-banding, since the artwork does not extend beyond the canvas.

### 7.2 Reset to neutral (L2)

```
on HomeView appear:
    if timeSinceLastExit > 30 minutes:
        animate offsetY → neutralOffsetY   (0.8s ease-out)
    else:
        restore previous offsetY
```

Cold launch always resets. Tab switching preserves. Backgrounding briefly preserves. Returning next morning resets.

### 7.3 Deferred

**Drag inertia** — a flick should coast and decelerate. v1.0 conflated "no spring-back to neutral" with "no inertia"; only the former was intended. Queued, not built.

**Pinch zoom** — deferred. It would force resolution decisions (§12.5) that cannot be made before real artwork exists.

### 7.4 Known architectural debt

`offsetY` currently lives inside `ParisSceneTuning`, a dev-only object, because the tuning panel's jump buttons need to drive it. **`offsetY` is production state** — §7.2 persistence must read it. Camera state must be split out of tuning state before the dev panel is stripped for release.

---

## 8. Animation model

### 8.1 All animation is a pure function of elapsed time (L9)

**This is a hard rule, arrived at by debugging a silent failure.**

The natural SwiftUI pattern —

```swift
@State private var crossed = false
.offset(x: crossed ? end : start)
.animation(.linear(duration: d).repeatForever(), value: crossed)
.onAppear { crossed = true }
```

— **does not work here.** `.animation(_:value:)` interpolates only when it observes `value` change between two *rendered* states. Mutating the flag in `.onAppear` happens inside the same transaction that first renders the view, so there is no "before". The property jumps directly to its end value. A `repeatForever` animation that never starts never repeats.

The observed symptom was: river streaks frozen at rest, and boat/cars/birds invisible because they had snapped to their off-screen end positions. Five animations were dead for two phases.

The scene amplified it: every drag frame re-renders all eight planes, continuously re-targeting any animation that had started.

**Required pattern:**

```
TimelineView(.animation) { context in
    let t = context.date.timeIntervalSince(anchor)
    let phase = (t.truncatingRemainder(dividingBy: duration)) / duration
    // position is a pure function of phase
}
```

Position derived from elapsed time cannot desync, cannot fail to start, and survives view identity changes without restarting.

**One `TimelineView` per plane, not per element.** The clock sits as a sibling of the plane's static shapes so per-frame re-evaluation never reaches the band geometry.

### 8.2 Transform separation

An animated element's own motion and its parallax offset must occupy **separate modifiers**. If both write to the same transform, the per-frame parallax update stomps the animation.

```
ParisSceneView          → .offset(y: delta × depth)     [parallax]
  └── placement         → .offset(y: canvasPosition)    [static]
        └── animation   → .offset(x: f(t))              [motion]
```

Never merge into a single `.offset(x:y:)` carrying both a placement and an animated component.

### 8.3 Animation classes

| Class | Behaviour | Current examples |
|---|---|---|
| Emitter | Rises from a point, expands, fades | Chimney smoke |
| Traversal | Crosses horizontally on a long loop | Boat, cars |
| Drift | Wanders slowly on a Lissajous path | Birds |
| Pulse | Brightens and dims | Eiffel glow, window lights |
| Flow | Surface translation, seamless tiling | River streaks |
| Static | Positioned, no motion | Most of the scene |

Six classes cover everything currently built and most of what the artist brief describes. Each is implemented once; appearance is a parameter.

### 8.4 Determinism

**No randomness anywhere.** All positions, stagger offsets, durations and phases come from fixed arrays or index-derived formulas. Two runs at the same configuration must produce identical scenes, so performance readings are comparable.

Generated elements (stress harness, and later the registry) use an **R2 low-discrepancy sequence** — the 2D generalisation of the golden ratio, using the plastic number:

```
x_i = frac(0.5 + i / g)     1/g  = 0.7548776662466927
y_i = frac(0.5 + i / g²)    1/g² = 0.5698402909980532
```

Measured over 256 points on an 8×8 grid (ideal 4/cell): R2 gives min 3, max 5, stdev 0.75. A seeded RNG gives min 0, max 8, stdev 2.02. Random clumping changes overdraw and therefore timing; a grid produces visible rows and moiré. R2 fills evenly at *every* count — essential when count is the independent variable.

It is a pure function of index, so element 0 is always the same point. Raising a count appends rather than rebuilding.

### 8.5 Suspension

All animation suspends when `scenePhase != .active` and resumes on return. Periodic timers do not accumulate missed fires.

---

## 9. Layer state model

Three states per layer. Assumes runtime filtering (O1 unresolved).

| State | Treatment |
|---|---|
| `dormant` | `saturation 0.15`, `brightness −0.45`, `contrast 0.9`, `opacity 0.70` |
| `awakening` | `saturation 0.60`, `brightness −0.25`, `opacity 0.85` |
| `alive` | No filter |

Transitions animate over 1.2 s ease-in-out — light arriving, not a value flipping.

### 9.1 Proximity gradient

Layers nearer to unlocking appear less dark, via a backend-supplied `dormantDepth` in 0.0–1.0:

```
effectiveBrightness = −0.45 × dormantDepth
effectiveOpacity    = 0.70 + (0.25 × (1 − dormantDepth))
```

Defaults to 1.0 (fully dormant) until the backend supplies it.

---

## 10. Quality tiers

### 10.1 Tier parameters

| Parameter | Full | Reduced | Minimal |
|---|---|---|---|
| `blurEnabled` | true | true | **false** |
| `blurRadiusScale` | 1.0 | 0.5 | 0.0 |
| `smokeSlotsPerChimney` | 3 | 2 | 1 |
| `windowUpdateHz` | 10.0 | 4.0 | 1.0 |
| `birdCount` | 3 | 2 | 1 |
| `riverStreakCount` | 12 | 12 | 6 |
| `cloudCount` | 6 | 4 | 2 |

### 10.2 The blur substitution

When `blurEnabled` is false, blurred elements do **not** become hard-edged. They swap to a `RadialGradient` fill fading to fully transparent at the rim:

```swift
RadialGradient(gradient: Gradient(stops: [
    .init(color: color.opacity(1.00), location: 0.00),
    .init(color: color.opacity(0.82), location: 0.30),
    .init(color: color.opacity(0.42), location: 0.58),
    .init(color: color.opacity(0.14), location: 0.80),
    .init(color: color.opacity(0.00), location: 1.00)
]), center: .center, startRadius: 0, endRadius: radius)
```

Curved mid-stops, not linear — a linear ramp reads as a flat halo rather than a blurred disc. `RadialGradient` does not force an offscreen render pass.

The `.blur()` modifier stays **attached** at every tier with radius scaled to 0, rather than being wrapped in a conditional. Wrapping it would change view identity and restart animations with a visible pop on every tier switch.

**Measured: SwiftUI does elide a zero-radius blur.** This was an unverified assumption in v1; §11.2 confirms it empirically.

### 10.3 Known problem with the current tier definitions

The tiers currently reduce **apparent size and quantity** — a smaller glow, fewer puffs. The designer's assessment on device: this reads as *diminished* rather than *simplified*. The scene looks broken rather than cheaper.

**The correct axis is cost, not appearance.** A cheaper glow should be the same size and brightness, achieved with fewer render passes. Tier definitions need redesigning around this. **Outstanding work.**

---

## 11. Performance — measured

**All figures: iPhone SE 2022 (A15, 375×667, 60 Hz), placeholder vector shapes, p95 over a 600-frame window, sustained energetic dragging.**

### 11.1 Measurement protocol

Stationary readings are **worthless** for this scene. At 300 blurred smoke puffs the scene reports a locked 16.7 ms while stationary and 35 ms while dragging. Parallax recomposition and animation cost compete for the same resource.

Protocol:
1. Set one element type's count
2. Drag energetically up and down for **≥ 10 seconds continuously** (the p95 window is 600 frames)
3. Read p95 *without stopping*
4. Converge on the count where p95 stays at 16.7 ms

Also watch `run` — the longest unbroken cluster of dropped frames. Two scenes with identical drop percentages feel completely different depending on whether drops are scattered or clustered. A run of 12 is a visible quarter-second freeze that a percentage hides.

### 11.2 Solo ceilings

Maximum count of a single type, everything else at authored defaults:

| Type | Full | Minimal | Tier effect | Bound by |
|---|---|---|---|---|
| **Smoke puffs** | **125** | **> 300** (no break found) | **≥ 2.4×** | blur |
| **Birds** | **200** | 225 | 1.1× | stroked path |
| **Windows** | **550** | 625 | 1.1× | filled shape |
| **Traversals** | > 200 (no break) | > 200 | — | — |
| **River streaks** | > 400 (no break) | > 400 | — | — |

Notes: river streaks render **3× the slider value** (the pattern tiles), so >400 is >1200 capsules on screen. Traversals span two planes — index 0 is the boat on `water`, the rest are cars on `front`.

**Findings:**

- **Blur is the dominant solo cost.** Removing it takes smoke from 125 to beyond the measurable range.
- **The zero-radius blur elision is confirmed.** 125 puffs: 20 ms at Full, 16.7 ms at Minimal.
- **Cost tracks rendering technique, not element count.** A bird costs ~2.75 windows. Both are single small views; the bird is a stroked path with quad curves, the window a filled rounded rect. Stroked paths rasterise slower.
- **The "anim views" count is a poor cost proxy.** Confirmed and should be replaced by a technique-weighted metric.

### 11.3 Combined ceiling — the real constraint

All types running simultaneously, converged so p95 stays at 16.7 ms:

| Type | Full | Minimal | % of solo ceiling (Full) |
|---|---|---|---|
| Smoke | 40 | 40 | 32% |
| Birds | 50 | 50 | 25% |
| Traversals | 70 | 85 | ≤ 35% |
| River streaks | 130 | 145 | ≤ 33% |
| Windows | 130 | 145 | 24% |
| **TOTAL** | **420** | **465** | **~28%** |

**This is the number the whole system must respect.**

**Findings:**

- **The types share one pool.** Combined ceilings are ~25–33% of solo ceilings. Solo numbers answer "how much of one thing before the machine gives up" — a different question from "how much can coexist."
- **Traversals and river streaks are not free after all.** They looked unbounded solo because their ceilings exceeded the slider range. Under combined load they break at 70 and 130.
- **The quality tier barely helps under combined load.** Smoke and birds do not move at all; the cheap types gain 12–21%. Solo, blur removal was a 2.4×+ lever. Combined, it is worth ~11% overall. Once several types run together the bottleneck stops being blur and becomes **shared per-frame compositing across a large view count during parallax updates.**
- **The tier system is still worth keeping**, but as a modest optimisation, not a major one. If automatic degradation is ever built, ~11% is what it can deliver.

### 11.4 Headroom

The current authored scene runs **~84 animated elements** and costs **153 units**. The validated budget is **600 units** (§11.6).

**A maximum-richness B2 scene is roughly 4× the density of what exists today** on the most constrained supported device — a genuinely dense, living Paris.

### 11.5 Cost model validation

**The registry's technique-weighted cost model was tested across its range rather than calibrated at a single point.**

#### Method

The stress harness was wired to the cost model so element counts could be dialled to a target cost. Two distribution shapes were tested at each level:

- **Proportional** — each group receives a share of the budget matching its share of the authored scene's cost. Produces a realistically shaped scene.
- **Even** — the budget is split equally across all seven groups. Produces a differently shaped scene at matched cost.

Each configuration was dragged energetically for ≥ 10 seconds before reading p95.

#### Results

| Target cost | Proportional | Even |
|---|---|---|
| 400 | ✅ pass | — |
| 600 | ✅ **pass — maximum** | — |
| 700 | ❌ fail | — |
| 800 | ❌ fail | ❌ fail |

#### Findings

**The budget is 600, not 800.** The initial 800 figure was derived by summing measured combined ceilings per group. The 25% overestimate is consistent with per-element costs not adding perfectly linearly across types — the expected direction and magnitude of error for that method.

**Cost is shape-independent.** 800 fails in both proportional and even distributions, despite proportional carrying 47 smoke puffs against even's 26. Had even passed where proportional failed, blur would have been saturating non-linearly and required its own budget axis. It does not.

**A single technique-weighted number is therefore sufficient.** The two-axis model speculated in v2.0's §14.5 is rejected.

#### Caveats

The model is now validated at four points across its range rather than one, but two limits remain:

- All measurements use **vector placeholder shapes**. Real image assets will change the weights. The *method* here — dial to target, drag, read p95, bisect — is reusable and should be re-run when assets exist.
- The proportional shape inherits the three permanently invisible clouds (§6.4), so it is not quite the *visually* representative scene it appears to be. Invisible work still costs frames, so the correlation holds, but the shape slightly over-weights clouds relative to perceived richness.

### 11.6 The soft-edge principle (L13)

**Soft edges are expensive. Defined edges are free.**

- A true gaussian blur costs an **offscreen render pass per element per frame**
- A `RadialGradient` fill achieving visual softness costs **nothing measurable**
- Stroked paths cost roughly **3× filled shapes**
- Filled shapes with linear transforms are effectively **free** at any authorable count

**This is an argument about artistic direction, not only implementation.** Watercolour with defined shapes and gradient washes is cheap. Watercolour with genuine atmospheric haze and diffuse glow is expensive, and the cost lands *per element* — a scene with thirty softly-glowing elements is in trouble while a scene with three hundred crisp ones is fine.

**This must be communicated to the artist before any work begins.**

The designer's stated intent for smoke — rounded, circular, lofi-styled shapes rather than diffuse particle blur — is *cheaper* than what is currently built and aligns the artistic and performance directions.

### 11.7 Sprite-sheet cost — measured

**Every figure in §11.1–11.6 measures vector shapes, which must be rasterised each frame. Real artwork will be sprite sheets — bitmaps, where the GPU blits an existing texture. This section measures that difference directly.**

#### Method

Twenty synthetic sprite sheets generated at launch, deliberately non-uniform to reflect a realistic Parisian scene where a whole 5–6 storey building fits on screen:

| Group | Size | Frames | Purpose |
|---|---|---|---|
| Sheets 0–11 | 16–24 pt | 4–8 | Birds, pigeons, small figures |
| Sheets 12–17 | 28–34 pt | 6 | Cars, cats, larger figures |
| Sheets 18–19 | 40 pt | 8 | Largest hand-animated elements |

Frame stepping is a pure function of elapsed time, one `TimelineView` per plane (not per instance). Two modes were compared at matched instance counts:

- **Varied** — N distinct textures, M instances each. The realistic case.
- **Uniform** — one texture, replicated N × M times. The control, eliminating texture switching.

#### Results

| Mode | Distinct | Instances | Total | Result |
|---|---|---|---|---|
| Varied | 20 | 12 | **240** | ✅ pass |
| Varied | 20 | 13 | 260 | ❌ fail |
| Varied | 10 | 25 | **250** | ✅ pass |
| Uniform | 20 | 12 | **240** | ✅ pass |
| Uniform | 10 | 25 | **250** | ✅ pass |

#### Findings

**Texture variety is free.** Varied and uniform break at identical counts. Halving the distinct texture count (20 → 10) bought 4% more instances — noise, not signal. The GPU does not care how many distinct textures are bound; it cares how many sprites are composited per frame.

**This validates authoring many distinct behaviours rather than replicating few.** An artist can draw as many different animations as they like. What is bounded is how many sprites appear on screen simultaneously.

**Sprite ceiling: ~240–250 sprites** solo on the reference device.

**Sprites are mid-cost, not cheap.** At a 240 solo ceiling, a sprite weighs **≈ 2.3 window-equivalents** — between `strokedPath` (2.75) and `gradientFill` (1.8). Blitting avoids rasterisation, but each sprite remains its own composited layer receiving a per-frame update, and that compositing is the shared bottleneck identified in §11.3.

**Consequence: the 600-unit budget does not become more generous with real artwork.** Sprites are not the cheap option. Replacing blurred vector smoke (4.4) with a sprite (2.3) helps, but replacing filled shapes (1.0) with sprites costs more.

**Texture memory is a non-issue.** All 20 sheets decode to **1.34 MB** total. Real artwork at these dimensions lands in the same order of magnitude.

#### Architectural confirmation

**Three-level transform separation works under load.** A sprite swapping its texture frame while its position updates every frame from parallax — the one combination never previously tested — renders correctly during sustained dragging, with no frozen frames and no jitter. The three changes occupy separate modifiers on separate view levels:

```
ParisSceneView   → .offset(y: delta × depth)          [parallax, per plane]
  └── placement  → .offset(x: canvasX, y: canvasY)    [static position]
        └── strip → .offset(x: -frame × cellWidth)    [frame stepping]
```

This closes the last architectural unknown in the animation system.

#### Design consequence: variation through transformation

Since texture variety is free but sprite *count* is not, richness should scale by placing many instances of a behaviour in different places, varied through **tint, scale, horizontal flip, and independent motion paths**, rather than by drawing separate artwork for each visual variant. One bird sheet can yield many visibly different birds at no additional texture cost.

This directly informs what to commission: **fewer, more reusable sprite sheets designed for parameterisation**, rather than many bespoke ones.

### 11.8 Caveats

- Sprite figures use **synthetic generated textures**. Real artwork of the same dimensions should behave equivalently — the GPU sees identical bitmaps — but this should be confirmed once assets exist.
- The uniform-mode control carried ~14% less fill area than varied (the replicated sheet was chosen at the set's mean cell area, not the largest). Too small to affect a pass/fail comparison, but relevant to any future fine-grained delta.
- Vector figures in §11.1–11.6 remain valid for anything drawn natively — the sky gradient, tints, fog, and any element not shipped as artwork.
- **The sweep should be re-run when real assets exist.** What transfers is the *method* — dial to target, drag energetically, read p95, bisect — and the structural findings: the shared pool, shape-independence, and free texture variety.

---

## 12. Asset contract

*(Unchanged from v1.0 except where noted. Not yet exercised — no real assets exist.)*

### 12.1 Content-cropped layers (L7)

Layers are **never** full-canvas transparent PNGs. A full-canvas layer at reference dimensions decodes to:

```
1179 px × 4602 px × 4 bytes = 21.7 MB
```

Fifteen such layers is 325 MB — the app would be terminated. Cropping is a hard requirement, not an optimisation.

### 12.2 Layer manifest

```json
{
  "layerKey": "accordion_player",
  "plane": "street",
  "depthCoefficient": 0.00,
  "densityTier": "A",
  "canvasRect": { "x": 84, "y": 1105, "w": 62, "h": 94 },
  "asset": { "bundle": null, "remote": "tuje/scene/street/accordion_player_v3.png" },
  "animation": { "class": "emitter", "intervalRange": [45, 90] },
  "states": { "dormantAsset": null }
}
```

**New in v2.0:** `canvasRect.y` must be validated against the plane's visible band (§6). An element outside its band renders every frame and is never seen.

### 12.3 Density tiers

Asset resolution is **inversely proportional to element size**. Large elements are low-frequency imagery and tolerate low density; small elements carry the detail that rewards close viewing, and their small bounding boxes make high density affordable.

| Tier | Density | Applies to | Typical bbox |
|---|---|---|---|
| A | @3x | Characters, storefronts, signage | < 200 × 200 pt |
| B | @2x | Buildings, Seine surface, monuments | 200–900 pt |
| C | @1.5x | Horizon washes, large soft masses | Full width |
| Native | — | Sky, tints, fog, vignette | Drawn in SwiftUI |

### 12.4 Memory budget

| Metric | Target | Ceiling |
|---|---|---|
| Decoded bitmap, mature scene | 30 MB | 60 MB |
| Time to first paint, cold | < 150 ms | 400 ms |
| Sustained frame rate | 60 fps | 60 fps |
| Lifetime download per user | ~6 MB | 15 MB |

**Measured baseline:** the current scene with pure vector shapes and no images uses **19.0 MB** total process footprint on the SE. (The simulator reported 40.9 MB — Mac-side overhead, not representative.)

Estimated mature scene: ~22 MB of decoded bitmaps on top → **~41 MB total**. Inside target.

### 12.5 Zoom deferred

Maximum zoom of 2.4× would require assets at 2.4 × @3x density for large elements, which is not viable. Deferred until real artwork exists and the trade-off can be judged visually.

---

## 13. Loading strategy

### 13.1 Bundle / remote split

**Every user's day-one scene is identical** — fully dormant, no personalisation. That makes it a bundle asset, not a network fetch.

| Category | Source |
|---|---|
| Base scene (planes 0–4, 7) | App bundle |
| Unlockable elements | Cloudinary → permanent disk cache |
| Seasonal / event overlays | Cloudinary → permanent disk cache |

### 13.2 First paint

Base scene is in-bundle, so first paint needs no network and no `scene-state` fetch. The scene renders fully dormant immediately, then layers crossfade to their state as data and assets arrive.

**The user never sees a spinner or an empty screen.** Worst case — cold launch, no network — is a fully dormant, fully rendered Paris. A legitimate visual state, not an error.

### 13.3 Variant swaps

**New in v2.0.** When a slot's variant changes (smoke → leaves), the new asset must be fetched and decoded. Naively this produces a visible gap.

Required: prefetch in background when scene state arrives, keep the old variant rendering until the new one is ready, then crossfade.

### 13.4 Caching

Disk cache keyed by versioned URL, no expiry. Layers are immutable — a change means a new version means a new URL, so the cache never needs invalidation logic.

**Cloudinary cost:** ~20 layers × ~300 KB, once per user, permanently cached = **~6 MB lifetime per user.** Negligible. Transformations use `f_auto,q_auto`.

---

## 14. Scene registry — design intent

**Not yet built.** Specified here so it is built against measured constraints rather than guesses.

### 14.1 Separation of concerns

Two systems, deliberately independent:

**The view** is a capability surface — all possible planes, slots, motion classes and variants, ready to be filled.

**The engine** decides what to fill it with, based on user data, level, weather, season, special days. **Designed after the view's capabilities are fully known.**

The registry's interface to the outside world is deliberately dumb: a slot → variant map plus enabled flags. Whether that map came from a backend engine, a dev panel, or a hardcoded default is invisible to the scene.

### 14.2 Structure

**Motion signatures** — the six classes in §8.3. Implemented once each.

**Slots** — a fixed position on a plane, with a motion signature and a set of permitted variants. A chimney slot permits emitter variants; a river slot permits traversal variants.

**Variants** — appearance only. Asset reference, colour, size, motion parameters. Smoke, coloured smoke, balloons, leaves, sparks — *same motion, different appearance*.

**Active configuration** — slot → variant mapping, supplied externally.

### 14.3 Why unused variants are nearly free

| Cost | Unused variant |
|---|---|
| Code | Zero — motion is shared |
| Metadata | Bytes |
| Memory | **Zero if the asset is not decoded** |
| Runtime | Zero — a disabled slot renders nothing |

A scene with 200 declared variants and 8 active ones costs almost exactly what a scene with 8 variants costs. **Catalogue everything; download and decode only what is active.**

### 14.4 Requirements

- Enforce §6 visible bands — reject or warn on out-of-band placement
- Enforce §3.1 attachment invariants
- Track a **technique-weighted cost budget**, not an element count (§11.5)
- Stable identity by index — changing a count appends, never rebuilds
- Drive the tuning panel, so every slot is individually switchable without code changes

### 14.5 Budget model — validated

**A single technique-weighted budget. One axis, not two.**

v2.0 speculated that blur might need its own separate budget alongside a view-count budget. **This was tested and rejected** — see §11.6. Blur is priced correctly by its technique weight and does not saturate non-linearly, so one number suffices.

#### Technique weights

Expressed in **window-equivalents**. One window — a filled rounded rect with animated opacity state — is 1.0. Weights derive from measured solo ceilings (§11.2): `weight = 550 / soloCeiling`.

| Technique | Weight | Basis |
|---|---|---|
| `filledShape` | 1.0 | measured, 550 solo ceiling |
| `gradientFill` | 1.8 | estimated, >300 solo, no break found |
| `strokedPath` | 2.75 | measured, 200 solo ceiling |
| `blurred` | 4.4 | measured, 125 solo ceiling |
| `spriteSheet` | 2.3 | measured, 240 solo ceiling — §11.7 |

#### Budget

```
BUDGET = 600 cost units    (iPhone SE 2022, Full tier, sustained dragging)
```

**Tier substitution:** when `blurEnabled` is false, any `blurred` variant is costed as `gradientFill` instead, because the blur is elided (§10.2, §11.2).

#### Current utilisation

| Scene | Cost | Utilisation |
|---|---|---|
| Authored scene today | 153.0 | **25.5%** |
| Maximum-richness B2 | 600 | 100% |

**A maximum-richness B2 scene is roughly 4× the density of what exists today.**

Largest groups in the authored scene: windows 54.0 (35.3%), chimneys 39.6 (25.9%), clouds 26.4 (17.2%). Of the cloud cost, **13.2 units — 8.6% of the entire scene — is the three permanently invisible clouds** (§6.4). They are blurred, the most expensive technique, and have never been seen.

At Minimal tier the scene costs 92.0, and **windows become 58.7% of the total** — the tier reduces every group except the one it never touches. That is where any remaining tier headroom lies (§10.3).

---

## 15. Build status

| Phase | Deliverable | Status |
|---|---|---|
| P1 | Layer stack, vertical drag, depth model, clamping | ✅ Complete |
| P2a | Neutral-anchored parallax, occlusion layout, tuning panel | ✅ Complete |
| P4 | Four animation classes + performance monitor | ✅ Complete |
| P4b | Quality tier system | ✅ Complete — definitions need redesign (§10.3) |
| P4c | Animation bug fix — pure functions of time | ✅ Complete |
| P5 | Stress harness + performance sweep | ✅ Complete — §11 |
| P6a | Scene registry — data model, catalogue, validation, cost model | ✅ Complete — §14 |
| P6a-v | Cost model validation against device | ✅ Complete — §11.5 |
| P5b | Sprite-sheet cost test | ✅ Complete — §11.7 |
| **P6b** | **Migrate rendering onto the registry** | **Next** |
| P7 | Visible-band audit — fix invisible clouds, add warnings | Queued |
| P8 | Tier redesign around cost, not appearance | Queued |
| P9 | CoreMotion horizontal parallax (needs device) | Queued |
| P10 | Drag inertia | Queued |
| P11 | Viewport persistence + camera/tuning state split | Queued |
| P12 | Asset pipeline — manifest, cropping, bundle/remote | Blocked on artwork |
| P13 | Backend `scene-state` wiring | Blocked on P6b |
| — | Pinch zoom | Deferred |
| — | Automatic quality degradation | Deferred |

### 15.1 Pre-launch hygiene

- Remove or `#if DEBUG`-gate the dev buttons in `HomeView.swift` (both "Picker (dev)" and "Paris (dev)" — the first predates this work)
- Strip the tuning panel, stress harness and debug readout from release builds
- Split camera state out of `ParisSceneTuning` (§7.4)

---

## 16. Contradictions with the artist brief

**The artist brief has not been updated since v1.0 of this spec and currently contains instructions that would produce unusable assets.** It must be revised before being sent to anyone.

| Brief says | Spec says | Severity |
|---|---|---|
| Layers at full canvas dimensions | **Content-cropped + metadata** | **Blocking** — 325 MB, app terminated |
| Canvas ≈ 2× screen height | **2.30×** | Correction |
| 5 rendered camera angles | **Single centre render** (L12) | Correction — 5× memory |
| Viewport springs back to neutral | No spring; position holds | Correction |
| Dormant is bespoke artwork ("the most important artistic challenge") | Runtime filter assumed, O1 open | Unresolved |
| No mention of visible bands | **§6 table is mandatory** | **Blocking** — elements can be permanently invisible |
| No mention of render cost by technique | **§11.5 soft-edge principle** | **Blocking** — style choice determines feasible density |
| Zoom to 2.4× | Deferred | Simplification |

**The three blocking items** — cropping, visible bands, and the soft-edge principle — all change what the artist is asked to produce. Sending the current brief would waste their time and yours.

---

## 17. Immediate next actions

1. Build **P6b** — migrate rendering onto the registry, so slot toggles and variant pickers drive what is drawn
2. Fold in **P7** (fix the three invisible clouds) as part of P6b
3. Revise the artist brief against §6, §11.5 and §12 before contacting anyone
4. Redesign the quality tiers around cost rather than appearance (§10.3)
5. Resolve **O4** — which Home view is the destination

---

*End of specification v2.0.*
