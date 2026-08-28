# TuJe — Parisian Scene
## Canvas Geometry Reference v3 — Ten-Plane Layout

**Supersedes:** v1 (eight-plane), v2 (ten-plane without image dimensions)
**Status:** Layout agreed. Not yet implemented in code — the current build still runs the eight-plane model.
**Derived from:** the three reference views (Neutral / Roof / River), with neutral proportions held fixed.

---

## 1. What changed from v1

The eight-plane model had a structural problem: everything carrying real animation lived on background planes visible less than half the time. The ten-plane layout fixes it by splitting the front of the scene into more surfaces and pushing the distant material further back.

| v1 | v2 |
|---|---|
| 8 planes | **10 planes** |
| Front detail crowded onto 2 planes | `front`, `frontDetail`, `road` — three surfaces at the same depth |
| One quai | **Two quais** — far (across the water) and near (under the viewer's feet) |
| Roof merged into front | **`roof` is its own plane at 0.39** — it recedes, so it reveals |
| Distant buildings as one band | **`district` and `horizon`** — one for recognisable Paris, one for the skyline |
| Eiffel on `mid`, animated | **Eiffel on `horizon`, static silhouette** — resolves the lighting copyright issue |

---

## 2. The canvas

Unchanged from v1.

```
canvasWidth  = screenWidth
canvasHeight = screenHeight × 2.30        (0.72 roof + 1.00 neutral + 0.58 water)
```

**Reference canvas: 1179 × 5879 px** (393 × 1960 pt, iPhone 15 Pro @3x)

The canvas is a **coordinate space, not an image size.** Each layer is drawn cropped to its own content and placed by a `canvasRect`. Never draw one full-height image per layer — a single full-canvas layer decodes to ~22 MB.

### Zones

```
0.000  ┌──────────────────────────┐
       │       ROOF ZONE          │   0.313 of canvas
0.313  ├──────────────────────────┤  ← neutral viewport TOP
       │      NEUTRAL ZONE        │   0.435 of canvas
0.748  ├──────────────────────────┤  ← neutral viewport BOTTOM
       │       WATER ZONE         │   0.252 of canvas
1.000  └──────────────────────────┘
```

---

## 3. The ten planes

Ordered back to front — render order.

| # | Plane | Depth | What it is | Animation |
|---|---|---|---|---|
| 0 | `sky` | **0.88** | Backdrop, gradient, time of day | Clouds, birds |
| 1 | `horizon` | **0.78** | Far buildings delimiting the skyline. **Eiffel Tower, left side, static silhouette** | **None** |
| 2 | `district` | **0.59** | Another area of Paris — park, garden, Notre-Dame, a museum | Small, sparse |
| 3 | `roof` | **0.39** | Mansard roof of the front building | Chimneys, birds landing, rooftop cat |
| 4 | `front` | **0.16** | The front Parisian building facade | — |
| 5 | `frontDetail` | **0.16** | Windows, shopfronts, signage, balconies | Window lights, shop activity |
| 6 | `road` | **0.16** | The street at the building's base | Cars, pedestrians |
| 7 | `quaiFar` | **0.08** | The quai across the water, with its wall dropping to the river | Figures, benches |
| 8 | `seine` | **0.04** | The river | Boats, current, reflections |
| 9 | `quaiNear` | **0.00** | The quai the viewer stands on — bouquinistes, close detail | Close-range activity |

### Why `roof` is 0.39 and not 0.16

It is physically part of the front building, so instinct says it should share the facade's depth. But a mansard roof genuinely **recedes** behind the facade's top edge — it is further from the viewer.

That depth gap is what makes the roof rise out from behind the facade first as the camera tilts up, before the district and horizon follow. It is the primary lever on how dramatic that reveal feels.

### Why three planes share depth 0.16

`front`, `frontDetail` and `road` are all on or attached to the same vertical surface. They are separate planes for **authoring and animation control**, not for parallax. They must never diverge in depth — windows sliding across the wall they belong to, or a road detaching from the building's base, are the failure modes.

### Why the Eiffel Tower moved to `horizon`

The tower's night illumination is protected by copyright. Placing it on the deepest building plane as a **static silhouette on the left of the skyline** avoids the issue entirely — no lighting, no animation, just a recognisable shape on the horizon.

It also fits the design: `horizon` is the least-seen plane in the scene, so it is the right place for decoration rather than animation.

---

## 4. Layer positions in canvas coordinates

Fractions of canvas height. Pixel values at the reference canvas (@3x).

| Plane | Top edge | Bottom edge | Top (canvas pt) | Top (px @3x) |
|---|---|---|---|---|
| `sky` | 0.0000 | — | 0 | 0 |
| `horizon` | **0.4082** | see overlap | 800 | 2400 |
| `district` | **0.3878** | see overlap | 760 | 2280 |
| `roof` | **0.3674** | see overlap | 720 | 2160 |
| `front` roofline | **0.3470** | 0.6804 | 680 | 2040 |
| `frontDetail` | 0.3470 | 0.6804 | 680 | 2040 |
| `road` | **0.6804** | 0.7000 | 1334 | 4002 |
| `quaiFar` | **0.7000** | see overlap | 1372 | 4116 |
| `seine` | **0.7725** | see overlap | 1514 | 4542 |
| `quaiNear` | **0.8743** | 1.0000 | 1714 | 5142 |

Note the ordering: `horizon` has the **largest** top-edge value despite being furthest away. That is correct — deeper planes sit lower in canvas space so that parallax lifts them into view.

---

## 5. The three views

### NEUTRAL — the resting composition

At neutral every plane shows exactly the same window, **canvas 0.313 → 0.748**, because parallax is anchored here and no plane is displaced.

**Compose for this window first.** It is what users see every launch without touching anything.

| Band | Screen position | Reference sketch |
|---|---|---|
| Sky | 0 – 8.0% | 7.8% |
| Front building | 8.0 – 84.5% | 84.5% |
| Road | 84.5 – 89.0% | 92.4% |
| Quai (far) | 89.0 – 100% | 100% |

*The road is slightly thinner than sketched. It must be narrow enough for the near quai to cover it at full tilt-down; at the sketched width that would require pushing the quai's depth to zero.*

**`roof`, `district` and `horizon` are completely hidden at neutral.** Nothing of them shows through.

### TOP VIEW — tilt fully up

| Band | Screen position | Reference sketch |
|---|---|---|
| Sky | 0 – 37.7% | 37.7% |
| Horizon | 37.7 – 46.7% | 47.8% |
| District | 46.7 – 56.4% | 61.6% |
| Roof | 56.4 – 68.3% | 75.0% |
| Front building | 68.3 – 100% | 100% |

Sky lands almost exactly on the sketch. District and roof come out thinner, front thicker. To widen them, increase the depth gaps — `district` toward 0.65 and `roof` toward 0.45 each buy roughly 3%.

### BOTTOM VIEW — tilt fully down

| Band | Screen position | Reference sketch |
|---|---|---|
| Front building | 0 – 35.8% | 27.7% |
| Quai (far) | 35.6 – 50.0% | 49.4% |
| Seine | 50.0 – 71.1% | 71.1% |
| Quai (near) | 71.1 – 100% | 100% |

Seine and near quai land on the sketch. The building runs longer, squeezing the far quai — a geometric consequence of `front` sitting at 0.16 and unable to retreat faster. Lowering `front` to ~0.10 would fix it at the cost of less sky in the top view.

**The road disappears exactly as intended.** At full tilt-down the far quai's top edge sits at 35.6%, just covering the building's base at 35.8%.

---

## 6. Layer image dimensions

**This is the table to draw against.** Every layer is a transparent PNG, full canvas width, at the height given below.

All figures in pixels at the reference canvas (**1179 × 5879 px**, @3x). Divide by 3 for points.

| Plane | Top edge (px) | **TOTAL IMAGE HEIGHT** | Silhouette band | Ever visible | **Never seen** |
|---|---|---|---|---|---|
| `sky` | 0 | *native gradient — no asset* | — | — | — |
| `horizon` | 2400 | **360** | 140 | 230 | **130** |
| `district` | 2280 | **380** | 120 | 250 | **130** |
| `roof` | 2160 | **430** | 120 | 300 | **130** |
| `front` | 2040 | **1960** | 120 | 1960 | 0 |
| `road` | 4001 | **175** | — | 115 | **60** |
| `quaiFar` | 4115 | **630** | — | 370 | **260** |
| `seine` | 4542 | **800** | — | 540 | **260** |
| `quaiNear` | 5140 | **740** | — | 740 | 0 |

In points: horizon 120 · district 127 · roof 143 · front 653 · road 58 · quaiFar 210 · seine 267 · quaiNear 247.

### The three regions of a layer image

Each layer image divides into up to three horizontal regions:

```
┌─────────────────────────┐  ← top of image
│    SILHOUETTE BAND      │   irregular edge — plane behind shows through
│  (transparent above     │
│   the drawn skyline)    │
├─────────────────────────┤  ← lowest valley of the silhouette
│                         │
│     VISIBLE BODY        │   solid, full width. The user sees this.
│                         │
├─────────────────────────┤  ← lowest point ever on screen
│      NEVER SEEN         │   drawn but invisible. Anti-gap margin.
└─────────────────────────┘  ← bottom of image
```

### Silhouette band — transparency is the occlusion mechanism

Above its drawn edge, every layer must be **fully transparent**. This is not a detail — it is how the scene works.

Each plane covers what is behind it *below* its top edge, and reveals it *above*. Opaque rectangles would break the tilt-up reveal entirely: the roof would never emerge from behind the facade, the district would never emerge from behind the roof.

Concretely:
- `horizon` transparent above its skyline, so the `sky` gradient shows through
- `district` transparent above its skyline, so `horizon` shows through
- `roof` transparent above its ridgeline, so `district` shows through
- `front` transparent above its roofline, so `roof` shows through

**Why the band is capped at 120 px** for `front`, `roof` and `district`: each plane's lowest valley must sit *above* the next plane's highest peak, or the hidden plane peeks through at neutral. 120 px is exactly the 40 pt inter-plane margin.

`horizon` has nothing behind it but sky, so its silhouette can be freer — 140 px, or more for a dramatic skyline.

### Never-seen region — the anti-gap margin

Adjacent planes at different depths separate as the camera moves. If a layer's hidden extension is too short, a gap opens mid-drag and the viewer sees straight through the world.

```
overlap = Δdepth × 0.72 × screenHeight
```

**Content in this region should be structural filler** — more roofscape, more building mass, more water. Never detail, never anything the composition depends on. No user will ever see it.

`quaiFar` and `seine` waste the most: 260 px each, being 41% and 33% of their total height. That is the cost of their depth separation from the layers around them. Keep those regions plain.

### What the numbers tell you about effort

**The three receding planes are small** — 230, 250 and 300 px of visible content, roughly 4–5% of canvas height each. In the top view they read as thin horizontal bands, which is what a receding skyline looks like. Do not over-invest here.

**`front` is 1960 px — more than every other layer combined.** A third of the canvas, visible almost in its entirety at neutral, on every launch. This is where the drawing effort belongs, and where the layer variants and custom parts live.


---

## 7. Visible range per plane

Three progressively stricter answers to "where can I put something?"

| Plane | Depth | CAN REACH viewport | Neutral window | Top window | Bottom window |
|---|---|---|---|---|---|
| `sky` | 0.88 | 0.276 – 0.778 | 0.313 – 0.748 | 0.276 – 0.710 | 0.343 – 0.778 |
| `horizon` | 0.78 | 0.244 – 0.803 | 0.313 – 0.748 | 0.244 – 0.679 | 0.369 – 0.803 |
| `district` | 0.59 | 0.185 – 0.851 | 0.313 – 0.748 | 0.185 – 0.620 | 0.416 – 0.851 |
| `roof` | 0.39 | 0.122 – 0.902 | 0.313 – 0.748 | 0.122 – 0.557 | 0.467 – 0.902 |
| `front` / `frontDetail` / `road` | 0.16 | 0.050 – 0.960 | 0.313 – 0.748 | 0.050 – 0.485 | 0.525 – 0.960 |
| `quaiFar` | 0.08 | 0.025 – 0.980 | 0.313 – 0.748 | 0.025 – 0.460 | 0.545 – 0.980 |
| `seine` | 0.04 | 0.013 – 0.990 | 0.313 – 0.748 | 0.013 – 0.447 | 0.555 – 0.990 |
| `quaiNear` | 0.00 | 0.000 – 1.000 | 0.313 – 0.748 | 0.000 – 0.435 | 0.565 – 1.000 |

**Anything outside the "can reach" column is rendered every frame and never seen at any camera position.** This was a real bug twice in the eight-plane model.

### Where animation should live

The neutral view carries `front`, `frontDetail`, `road` and `quaiFar` — all with wide visible bands. **Animation intended to be seen at rest belongs on these planes.** Cars on the road, lit windows, shop activity, figures on the far quai: seen every launch without the user touching anything.

`roof`, `district` and `horizon` are **discovery rewards**. They are invisible at neutral by design. Animation there is found by tilting up, not encountered passively.

`seine` and `quaiNear` are the equivalent at the bottom — found by tilting down.

This is a deliberate design, not a limitation: the scene rewards exploration. But it means **the resting composition must carry enough life on its own**, or the app looks static to a user who never drags.

---

## 8. Render cost — what to know while drawing

Measured on an iPhone SE 2022. Costs in window-equivalents; one plain filled shape = 1.0.

| Technique | Cost | Solo ceiling |
|---|---|---|
| Filled shape, hard edge | 1.0 | 550 |
| Gradient fill (soft edge, no blur) | 1.8 | >300 |
| Sprite sheet (hand-drawn frames) | 2.3 | 240 |
| Stroked path | 2.75 | 200 |
| **True gaussian blur** | **4.4** | **125** |

**Total budget: 600 units.**

### Two findings that shape the artwork

**Soft edges are expensive; defined edges are free.** A real blur costs an offscreen render pass per element per frame. A gradient fill achieving the same softness costs almost nothing. Watercolour with defined shapes and gradient washes is cheap; watercolour with genuine atmospheric haze is expensive, and the cost lands *per element*.

**Texture variety is free; sprite count is not.** Twenty distinct sprite sheets cost exactly the same as one sheet repeated twenty times. Draw as many different behaviours as you like — what is bounded is how many sprites appear on screen at once (~240 solo).

**Therefore:** vary through tint, scale, horizontal flip and independent motion paths rather than drawing bespoke artwork for each visual variant. One bird sheet yields many visibly different birds at no extra cost. **Commission fewer, more reusable, parameterisable sheets.**

### Sprite sizing

A whole 5–6 storey Parisian building fits on screen, so animated elements are small:

| Element | Typical size |
|---|---|
| Bird, pigeon, distant figure | 16 – 24 pt |
| Car, cat, closer figure | 28 – 34 pt |
| Bouquiniste stall, near-quai detail | 34 – 48 pt |
| Largest hand-animated element | ~48 pt |

Twenty sprite sheets at these sizes total roughly **1.34 MB** of texture memory. Not a constraint.

---

## 9. Motion signatures

Six classes. Each implemented once; appearance is a parameter, so a new variant costs artwork but no new code.

| Signature | Motion | Examples |
|---|---|---|
| `emitter` | Rises **or falls** from a point, expands, fades | Chimney smoke, balloons, falling leaves, snow |
| `traversal` | Crosses horizontally on a long loop | Boats, cars, cyclists, pedestrians |
| `drift` | Wanders slowly on a looping path | Birds, clouds |
| `pulse` | Brightens and dims in place | Window lights, shop signs, glows |
| `flow` | Surface translation, seamlessly tiled | River current |
| `staticEl` | Positioned, no motion | Most of the scene |

The emitter carries a **signed** vertical parameter — positive rises, negative falls — so blossom and snow use the same code as chimney smoke.

**When specifying animation, name the signature plus its parameters** rather than describing motion from scratch. Anything that does not fit these six means new code, not just new artwork — worth flagging early.

---

## 10. Tuning knobs

If the views need adjusting, these are the levers and their trade-offs.

| Knob | Current | Effect |
|---|---|---|
| `front` depth | 0.16 | Lower widens the far quai at bottom view, narrows sky at top |
| `roof` depth | 0.39 | **The biggest lever on how dramatically the roof emerges** |
| `district` depth | 0.59 | Raise toward 0.65 to widen the district band at top view |
| Margins between hidden planes | 40 pt | Larger keeps them hidden longer and reveals later; smaller risks peeking at neutral |
| Road band width | 0.0196 | Wider reads better at neutral but constrains the quai's depth at bottom |

---

## 11. Quick reference

```
CANVAS
  Reference:        1179 × 5879 px   (393 × 1960 pt, iPhone 15 Pro @3x)
  Height:           2.30 × screen height
  Viewport shows:   0.435 of canvas height

ZONES (fractions of canvas height)
  Roof              0.000 – 0.313
  Neutral           0.313 – 0.748    ← compose here first
  Water             0.748 – 1.000

DEPTHS (back to front)
  sky        0.88      front        0.16
  horizon    0.78      frontDetail  0.16
  district   0.59      road         0.16
  roof       0.39      quaiFar      0.08
                       seine        0.04
                       quaiNear     0.00

TOP EDGES (canvas fraction)
  sky        0.0000    front        0.3470   (bottom 0.6804)
  horizon    0.4082    road         0.6804   (bottom 0.7000)
  district   0.3878    quaiFar      0.7000
  roof       0.3674    seine        0.7725
                       quaiNear     0.8743

LAYER IMAGE HEIGHTS (px @3x, full canvas width)
  horizon 360 · district 380 · roof 430 · front 1960
  road 175 · quaiFar 630 · seine 800 · quaiNear 740
  sky = native gradient, no asset

  Transparent above the drawn edge (silhouette band 120px,
  horizon 140px). Bottom region never seen — filler only.

BUDGET
  600 units
  filled 1.0 · gradient 1.8 · sprite 2.3 · stroked 2.75 · blur 4.4

PER LAYER, DELIVER
  A cropped PNG  +  its canvasRect (x, y, w, h in canvas coordinates)
  Never a full-canvas image
```

---

## 12. Outstanding

- **Code does not yet implement this.** The current build runs the eight-plane model. Migrating `ScenePlane`, the catalogue, the placeholder layers and the registry to ten planes is a build phase not yet scheduled.
- Overlap is a new constraint with no validator. The registry checks visible bands and occlusion, but nothing yet verifies that a plane's hidden extension is deep enough.
- The `front` depth trade-off (§5, bottom view) is unresolved — 0.16 favours the top view, 0.10 favours the bottom.

---

*If the travel ratios (0.72 / 0.58) or any depth changes, every derived number in this document changes.*
