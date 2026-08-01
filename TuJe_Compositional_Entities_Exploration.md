# TuJe — Compositional (Recursive) Entities: A Design Exploration

**Status: EXPLORATORY. Nothing here is built or committed. This is a thinking document for Rémi to reflect on at leisure. The current app uses the single-slot, non-recursive `realize_template` (built, verified). This explores what it would mean to go compositional — the idea, the payoff, the hard parts, and possible staged paths. Read it as "here is the shape of the decision," not a plan.**

---

## 1. The idea in one sentence

Today an entity is a slot filled by a **vocab** word. In a compositional system, an entity slot could be filled by **another answer/template** — so small structures nest inside larger ones, and a sentence is built by composition rather than authored whole.

**Example (Rémi's):**
- Answer A: `un entityAnimal` → realizes to `un chien`
- Answer B: `entityVerbAvoirWithJe entityAnswerA` → realizes to `j'ai un chien`

Here `entityAnswerA` is an entity whose "vocab" is *Answer A itself*, and `entityVerbAvoirWithJe` is an entity whose vocab is a conjugated verb form (`j'ai`). Entities stop being "a tool for some answers" and become the **universal building block** — for nouns, verbs, and sub-phrases alike.

---

## 2. Why it's appealing

1. **Authoring efficiency / reuse.** Author `un entityAnimal` once. Every template that needs "a possessed thing" composes it instead of re-authoring the noun phrase. At scale, this is the difference between authoring N×M sentences and authoring N + M parts.

2. **Complexity becomes structural, not a separate tag.** You asked how the app knows a template's complexity. In a compositional model, complexity ≈ **composition depth**. `un chien` (depth 1) is inherently simpler than `j'ai un chien` (depth 2) than `je pense que j'ai un chien` (depth 3). The "easy vs hard template" axis falls out of the tree depth for free — no separate complexity authoring needed. (This is the elegant convergence with the level_from/level_own idea: deeper compositions tend to be higher-level.)

3. **Verbs as entities → conjugation by lookup.** `entityVerbAvoirWithJe` → "j'ai", `entityVerbAvoirWithTu` → "tu as". Conjugation becomes entity resolution, consistent with the "no morphology engine, pure authored lookup" philosophy that already powers grammatical agreement.

4. **It generalizes the pattern you already trust.** Entity normalization is already the core IP. This is that idea taken to its logical conclusion: *everything* is a normalized, composable unit.

---

## 3. The hard parts (the honest cost)

This is a **significant** escalation, and it touches the part of the system that currently works. Each of these is its own design problem:

### 3a. Recursive resolution
Realizing a template stops being "replace one token" and becomes "recursively resolve each sub-entity, depth-first, then assemble." You need:
- A **resolver** that walks the composition tree.
- **Depth limits** (how deep can composition go? unbounded is dangerous).
- **Cycle detection** — can Answer A ever reference (transitively) itself? A→B→A would infinite-loop. The resolver must detect and reject cycles.
- **Ordering** — sub-entities resolved before the parent can assemble.

### 3b. Attribute propagation across composition boundaries (the hardest)
Today you avoid agreement computation with "one template per grammatical variant" (`un`/`une` are separate templates). Composition **reintroduces agreement at the seam**:
- If `entityAnswerA` = `un entityAnimal` and it fills a slot in B, does B need to "see through" A to the animal's gender/number? (e.g. if a later word must agree with the animal.)
- Does the composed unit **expose** the attributes of its head (the animal's gender), or is it opaque?
- If it must expose them, every composed unit needs a computed attribute set derived from its children — which is exactly the agreement-propagation problem the flat model sidesteps.

**This is the crux.** In the flat model, a template's required attributes are authored directly. In a compositional model, a parent's slot requirements may depend on what its children resolved to — dynamic, not authored. That's a real grammar engine, not a lookup.

*Possible mitigation:* keep composition **attribute-opaque** — a composed sub-answer is treated as a fixed string once realized, and parents never agree with the internals. This keeps it tractable but limits what compositions are grammatical (you can only compose where no cross-boundary agreement is needed). Worth deciding whether that restriction is acceptable.

### 3c. Verb-entity naming / combinatorics
`entityVerbAvoirWithJe` encodes verb + person into the entity name. Across all verbs × persons × tenses × moods, this could explode into thousands of entity names, or need its own **structured** representation (a verb entity + a separate person/tense/mood parameter) rather than baking everything into the name. Naming scheme is a design decision with scaling consequences.

### 3d. Scoring / matching identity (Option A tension)
Today (Option A), a button submits the **template's answer id**, scored as that answer's type. With composition:
- What id does `entityVerbAvoirWithJe entityAnswerA` submit? The composed answer B's id? Does B even have an `answer_type` / level of its own, or is it derived from its parts?
- For **voice matching** — does the matcher match against composed forms, or only leaf templates? If Answer B is never authored as a flat matchable string, how does the voice matcher recognize "j'ai un chien"? (Composition helps *generation*/buttons; it complicates *matching* unless the matcher also composes.)

### 3e. It's a rebuild of a working piece
`realize_template` is single-slot, non-recursive, verified on device. Going compositional is not an addition — it's a **replacement** of the core realization logic, plus the schema to represent composition (an answer referencing another answer as a slot), plus authoring-tool implications (how do you author `entityAnswerA`?).

---

## 4. Where complexity-from-composition meets level_from/level_own

You noted template complexity can come from `level_from`/`level_own` compared to user/cycle level. That works in **both** models:

- **Flat model (today):** each template is authored at some difficulty; `level_from`/`level_own` on its vocab (and an eventual complexity signal on the template) tell you if it fits the user.
- **Compositional model:** depth is a *structural* complexity proxy, and `level_from`/`level_own` still gate the leaf vocab. The two combine — a shallow composition with rare vocab could be as hard as a deep one with common vocab.

So the level-based difficulty idea is **not** dependent on composition — it's usable now (Path 1) and would carry forward into a compositional model later. This is part of why deferring composition is safe: the difficulty machinery you build now isn't wasted.

---

## 5. Possible staged paths (if you ever pursue it)

**Path A — Never (flat forever).** Author full-sentence templates directly. Simple, no resolver, no agreement-propagation. Cost: authoring volume grows multiplicatively as structures combine. Viable if the template count stays manageable.

**Path B — One level of composition, attribute-opaque.** An answer may reference **one** other answer as a slot, and that referenced answer must be a **leaf** (no further composition). Composed sub-answers are opaque strings (no cross-boundary agreement). Captures the common `entityAnswerA` case (noun-phrase reused in sentences) without a full recursive resolver or agreement engine. Risk: "one level, opaque" restrictions tend to erode toward full recursion as you hit cases they don't cover.

**Path C — Full recursive composition.** The complete vision — arbitrary depth, verbs-as-entities, attribute propagation. Most powerful, most expensive. Effectively a compositional grammar engine. Would be its own multi-session design+build project (like rescue or the button engine were), with its own spec, schema, resolver, and careful handling of matching + scoring identity.

**A pragmatic sequence** if you decide it's worth it: A (now) → B (when authoring volume actually hurts) → C (only if B's restrictions become the bottleneck). Let the *pain* pull you up the ladder rather than building C speculatively.

---

## 6. Questions to reflect on (these decide the path)

1. **Is the flat model actually blocking you, or is composition an elegant future?** If full-sentence templates aren't yet painful to author, composition is a "someday," not a "now."
2. **How much cross-boundary agreement do your real sentences need?** If most compositions are attribute-opaque (no agreement across the seam), Path B is viable. If agreement pervades, you need Path C's harder machinery.
3. **What is the matching story?** Composition clearly helps button *generation*. Does the voice *matcher* also need to compose, or do you keep flat matchable forms alongside composed generatable forms? (You could have both: flat templates for matching breadth, composed templates for button generation — but that's two representations to keep in sync.)
4. **Verb representation:** entity-name-per-conjugation (simple, explodes) vs. structured verb entity + person/tense parameters (scalable, more design). This choice alone is worth its own think.
5. **Scoring identity:** what does a composed button submit, and how is it typed/leveled? Does a composed answer have its own authored `answer_type`, or a derived one?

---

## 7. Bottom line

The compositional-entity direction is **coherent and powerful**, and it's a natural extension of the entity-normalization IP you already believe in. It is **not** a prerequisite for the vocab-review purpose or for difficulty-scaling (both work on the flat model today — Path 1). Its real costs are recursive resolution, cross-boundary attribute agreement (the hardest part), verb-entity representation, and the matching/scoring identity questions — and it would be a *replacement* of a currently-working piece, so it deserves to be a deliberately-designed project, not a mid-task pivot.

Recommended posture: **build vocab-review flat now; keep this vision on the shelf; pursue it (starting from Path B) only when authoring volume or expressiveness genuinely demands it** — pulled by real pain, not speculation. Nothing you build on the flat model is wasted, because a composed template still ultimately realizes to a string, and the difficulty/config machinery is composition-agnostic.
