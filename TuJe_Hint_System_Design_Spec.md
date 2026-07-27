# TuJe — Hint System Design Spec

**Status: DESIGN LOCKED, not yet built. First build = Understand-L1 vertical slice.**

This captures the agreed hint model before implementation. Most of this feature is client-side (SwiftUI); the backend's role is comparatively small (serve categorized content, record usage).

---

## 1. Core concept

Hints help the user **understand** or **answer** an interaction. They are authored, per-interaction, and reset every new interaction (hint state is interaction-scoped and independent).

Crucially: a "hint" is **not** just fetched text. Each level is its own mini-interaction with its own UI flow, media, and sometimes user input. The higher levels (L3) are closer to guided comprehension/answer mini-features than to "show a tip." Two layers must not be conflated:

- **Content layer** — what's authored per interaction (context text, simplified audio, vocab blocks, answer lists, advice media).
- **Behavior layer** — the state machine + UI choreography that *plays* each level. This is the bulk of the work, and it's client-side.

---

## 2. Two buttons

Placed on the **right side of the screen (TikTok-style)**.

- **UNDERSTAND** — help comprehending the interaction (context, vocab, grammar, literal meaning).
- **ANSWER** — help producing an answer. Which help depends on the tier of the user's last voice answer.

---

## 3. State model (client-owned, per-interaction, reset on new interaction)

Two independent counters, both owned by the client (the backend just serves content for a requested button+level and records usage). Both reset to 0 on every new interaction.

### `understand_level` (0–3)
- Starts at 0.
- **Button disabled until the user has listened to the interaction at least once.**
- Each press increments 0→1→2→3.
- After each press, a brief cooldown (a couple of seconds) keeps the button inactive so that level's UI can play before another press.
- Completing L3 sets a flag **`understood = true`**.

### `answer_level` (0–3)
- Starts at 0.
- **First press gate:** if the user has never pressed Understand AND `understood == false` → first show a quick yes/no "Are you sure you understand the interaction enough to answer?" in the middle of the screen. After they answer, proceed to L1. If `understood == true` (completed Understand L3), **skip the gate**, go straight to L1.
- Each press increments 0→1→2→3.
- **Reset rule (important):** when the user submits a new answer, **if `answer_level <= 1`, reset `answer_level` to 0.** If `answer_level >= 2`, no reset (ever).
  - Rationale: at L0/L1 the help was general; once the user answers, the app knows their tier/mistake, so the next L1 should be freshly relevant to what they just did. At L2/L3 they were already shown concrete answer options — that help doesn't go stale, and re-escalating through concrete answers would defeat the point.

---

## 4. UNDERSTAND button — the three levels

Source: `brain_interaction`.

### L1 — contextual explanation (English text)
Explains what the interaction seems to be about, without literally translating it. Lets the user recall mostly by themselves.
- Example: interaction "Est-ce que tu vas au cinéma aujourd'hui ?" → hint "Your friend is asking you a yes/no question about an activity plan. You need to decide if you'd like it or not."
- **UI:** pinned text at the very top of the screen (just below the top-most elements), always visible.

### L2 — simplified audio (no text)
A slower, more articulated, simplified spoken version of the interaction. Audio only — no transcription or translation shown (we want the user to work from sound).
- Example: "Tu vas au cinéma ?"
- **UI:** a new play button appears top-right (below other top elements), persistent and replayable. Auto-plays once when it first appears.

### L3 — vocab-block comprehension flow → translation reveal
A guided flow that surfaces *what specifically is blocking* the user, then reveals the translation.
- The main central play button is replaced by a rectangle-shape element in the middle of the screen, with two buttons below: "I don't understand" / "I understand."
- The rectangle plays a **vocab-block audio** (a block of words from `brain_vocab`, author-edited — not necessarily single words). E.g. blocks "Est-ce que", "tu vas", "au cinéma", "aujourd'hui."
- The user can tap the rectangle to replay the block audio; must press one of the two buttons to mark understood/not.
- On press, the block is replaced by the **next** block (auto-plays), same interaction, until all blocks are done — a dynamic flow.
- After the last block, the translation appears pinned at the top (below existing top elements), always visible: **French, French phonetic, and English.**
- **Completing L3 ⇒ the app considers the user now understands the interaction** (sets `understood = true`, which skips the Answer-button gate).

---

## 5. ANSWER button — the three levels

**Gate:** on the first Answer press, if the user hasn't used Understand and `understood == false`, ask the yes/no "sure you understand enough to answer?" first, then go to L1.

Source depends on the tier of the user's **last** voice answer (reusing the voice tier system):
- No answer yet → generic (from `brain_interaction`).
- Tier 1 (matched an answer, even wrong) → `brain_interaction_answer` of the matched answer.
- Tier 2 (no match, vocab/attribute mistakes found) → `brain_attribute_mistake`.
- Tier 3 (not understood) → `brain_interaction`, filtered to hints categorized for "not understood."

### L1 — how to approach / handle a mistake (media-flexible)
Advice on how to approach the answer, or how to handle a specific prior mistake. Flexible content: text, audio, image, gif, or short video (audio/video can quickly unblock).
- **UI:** pinned at top, may sit after the Understand elements (if the user requested those too).
- **Flexible by design:** must serve whether the user hasn't answered yet or has answered and is in any of the three tiers. This is the one real coupling to the evaluate/tier result.

### L2 — English answer ideas (read-only panel)
5–6 plain **English** answer ideas. No audio — read only. The user translates for themselves and picks one.
- **UI:** panel slides up from the bottom with the list. Selecting one writes that English text **above the mic button** as a reminder.

### L3 — French answer options (with audio)
5–6 **French** answers, with (optionally) phonetic and a listen button each. The perfect answer is NOT identified among them. The user picks one.
- **UI:** bottom panel with French text + phonetic + a listen icon per row. Selecting one replaces the L2 English reminder above the mic with the French text + a tiny listen icon.

---

## 6. Malus (cost)

Using hints will feed a scoring malus (magnitude TBD — **use 1 as a placeholder per press** for now). The malus math is deferred to the scoring step, BUT: **record usage events from the start** so the data exists when the malus lands. Record per press: (interaction, button, level reached, timestamp). Cheap now; painful to backfill.

Malus can eventually cover several aspects of the interaction lifecycle; for the two-button hint system specifically, it's per-click.

---

## 7. Build sequence

The feature is large and client-heavy. Do NOT build it in one pass. Build proven vertical slices, hardest (the two L3 flows) last.

**Slice 1 (FIRST — agreed): Understand-L1, end to end.**
- Backend: serve the interaction's L1 contextual English text.
- Client: add the Understand button (right side), enable-after-first-listen, press → fetch → pin text at top; brief post-press cooldown; increment `understand_level`; record a usage event (malus=1).
- Proves the whole spine: button, gating, fetch, display placement, level counter, usage recording.

**Then, layering on the proven skeleton (rough order):**
- Understand-L2 (simplified audio + persistent replay button)
- Answer button skeleton + L1 (tier-routed advice) + the gate + the reset rule
- Answer-L2 (English ideas panel + write-back to mic)
- Answer-L3 (French options panel + audio + write-back)
- Understand-L3 (vocab-block comprehension flow + translation reveal) — a focused build of its own
- Malus scoring math (in the scoring step of the dependency chain)
- "Highlight the hint button when the user is struggling" nudge (deferred)
- User-history personalization ("likes hints") (deferred)
- Structural-help finale on repeated pressing (deferred; mentioned but not designed)

---

## 8. Open questions / to resolve in discovery

- **Does `brain_hint` exist, and what are its columns?** Does a hint record carry usage / type / level / media-kind / text (fr/en) fields? (Schema discovery not yet done.)
- **Where do `hint_ids` (or equivalent) attach?** Confirm links on `brain_interaction`, `brain_interaction_answer`, `brain_attribute_mistake`.
- **Answer-L1 ↔ mistake entanglement:** Answer-L1 for a Tier-2 answer comes from `brain_attribute_mistake` — does that table need a hint column, or does the mistake itself carry the hint?
- **Answer-L2/L3 source:** where are the English ideas / French options authored?
- **Understand-L3 vocab blocks:** how are the author-edited word blocks + their audio linked to the interaction (via `brain_vocab`)?

---

## 9. Hint categorization (author-side vocabulary)

For reference, hints are conceptually categorized on three axes (schema may or may not encode all of these — TBD in discovery):
- **Usage:** understand the interaction / formulate first answer / answer after no match / improve a matched answer.
- **Type:** contextual (help figure the surrounding context, without explaining the interaction outright) / conjugation (tense/verb help).
- **Level:** 1 (brief, user recalls mostly alone) / 2 (moderate guidance, user still fills the gap) / 3 (clear, direct, tells the user what to do).
