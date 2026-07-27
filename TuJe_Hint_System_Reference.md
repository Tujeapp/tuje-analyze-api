# TuJe — Hint System Reference

**Complete as built. Two buttons, six levels, all verified in-app.**

---

## 1. Purpose

Hints let a learner ask for help *inside* an interaction rather than failing silently or guessing. Two separate needs, so two separate buttons:

- **UNDERSTAND** — "I don't know what's being said to me."
- **ANSWER** — "I know what's being asked, but I don't know how to reply."

Each button escalates over three presses, from a light nudge to concrete help. The escalation is deliberate: the learner should recall as much as possible on their own before being handed the answer. Pressing a hint button will eventually carry a score cost (the malus, not yet built).

Critically, the **Answer button is situational** — what it offers depends on what the learner's last attempt actually got wrong, routed through the voice tier system. It's not a static help file.

---

## 2. The two ladders at a glance

```
UNDERSTAND (source: brain_interaction)          ANSWER (source: depends on tier)
────────────────────────────────────            ─────────────────────────────────
[gate: must have listened once]                 [gate: "sure you understand?"
                                                 unless Understand-L3 completed]

L1  English contextual text                     L1  tier-routed advice
    pinned top of screen                            pinned top (media-flexible)

L2  simplified/slowed French audio               L2  5–6 English answer ideas
    auto-plays once + replay button                  bottom panel → pick one →
                                                     shown above the mic

L3  vocab-block comprehension flow               L3  same options in French
    per-block audio, "I do"/"I don't",              + phonetic + listen button →
    then FR/phonetic/EN reveal                       pick one → replaces the
    ⇒ sets understood = true                         English reminder
```

---

## 3. State model

Both counters are **client-owned**, **per-interaction**, and **reset on every new interaction**. The backend never tracks hint level — it just serves content for a requested (button, level).

### `understandLevel` (0–3)
- Button is **disabled until the learner has listened to the interaction once** (`hasListenedOnce`, set by `onVideoFirstPlayEnded()` — playback *finished*, not merely started).
- Each press increments. The level only advances when the backend actually returns a hint (`found: true`), so it can never run past authored content.
- Completing L3 sets **`understood = true`**.

### `answerLevel` (0–3)
- **Gate:** on the first press, if `!understood`, show "Are you sure you understand the interaction well enough to answer?". Both buttons proceed to L1 — it's a speed bump, not a branch. **Only completing Understand-L3 skips the gate**; partial Understand use (L1/L2) does not.
- **Reset rule:** when a new answer is evaluated, if `answerLevel <= 1` → reset to 0 (and clear the shown text). If `>= 2` → never reset.
  - *Why:* at L0/L1 the help was general; once the learner answers, the app knows their tier and mistake, so the next L1 should be freshly relevant. At L2/L3 they were already shown concrete answers — re-escalating would defeat the point.
  - The reset fires on **all three** answer paths (voice, multi-button, single-button), not just voice.

---

## 4. UNDERSTAND — the three levels

Source for all three: `brain_interaction.hint_ids`.

### L1 — contextual English text
Explains what the interaction is *about* without translating it. Pinned at the top of the screen, always visible.

> "Est-ce que tu vas au cinéma aujourd'hui ?" → *"Your friend is asking you a yes/no question about an activity plan. You need to decide if you'd like it or not."*

### L2 — simplified audio
A slower, more articulated, simplified spoken version. **Audio only** — no transcription or translation, because the point is aural comprehension. Auto-plays once when it appears; a persistent replay button stays available.

The audio itself lives on **`brain_interaction.simplified_audio_url`**, not on the hint. The hint record (with `media_kind = audio`) is only the *trigger* to look it up; the serve endpoint returns the interaction's URL alongside the hint.

### L3 — vocab-block comprehension flow
A modal flow that replaces the centre play button, and the most involved piece of the system.

- The interaction's vocab blocks come from **`brain_interaction.interaction_vocab_id`** — an **ordered array** authored in Airtable. Each block is a `brain_vocab` record supplying `audio_normal_url`, `audio_slow_url`, and its text.
- A dark-grey rounded square (100pt) with a speaker icon appears, plus progress dots and the prompt *"Do you understand that vocab?"*. Below it: red **"I don't"** / green **"I do"**.
- The square is **audio-only** — no text shown. The block's audio auto-plays on appear.
- **Tap escalation:** auto-play = normal, tap 1 = normal, tap 2+ = **slow** (once slow, stays slow — someone who needs it slower keeps needing it).
- Answering either way advances to the next block, which auto-plays. Tap counts reset per block.
- After the last block, the flow closes and the **translation reveal** pins at the top: French, French phonetic, English.
- Completion sets `understood = true` and records which blocks the learner marked "I don't".

**Ordering is load-bearing.** `WHERE id = ANY(...)` does **not** preserve array order, so the serve endpoint fetches the vocab rows and then **re-orders them in Python** against `interaction_vocab_id`. This is the single place block order could silently break.

Verification query when authoring:
```sql
SELECT array_position(i.interaction_vocab_id, v.id) AS block_order, v.transcription_fr
FROM brain_interaction i
JOIN brain_vocab v ON v.id = ANY(i.interaction_vocab_id)
WHERE i.id = 'INT...'
ORDER BY block_order;
```

---

## 5. ANSWER — the three levels

### The tier routing (L1)

This is where the hint system plugs into the voice analysis system. Every evaluate returns a `tier` describing where the learner's answer was resolved, and the Answer button routes on it:

| Tier | Meaning | Hint source |
|---|---|---|
| 1 | An answer matched | `brain_interaction_answer.hint_ids` of the matched row |
| 2 | No answer matched, but a mistake was diagnosed | `brain_attribute_mistake.hint_ids` of the rows that fired |
| 3 | GPT had to interpret — nothing concrete understood | `brain_interaction.hint_ids` |
| null | No answer submitted yet | `brain_interaction.hint_ids` |

**Tier precedence:** a concrete mistake diagnosis outranks a GPT guess. Tier 3 only claims the tier `if gpt_used and tier is None` — otherwise a Tier-2b diagnosis would be overwritten and the router would serve generic help while holding a specific answer.

**Fallback:** if a tier-specific lookup finds nothing authored, it falls back to the interaction's hints. Some help beats none, and it means per-answer hints don't have to be authored before the button is useful.

Tier 3 and "no answer yet" currently share a source and are **not** distinguished — finer filtering (via `applies_to_tier` or `type`) waits until there's content that needs it.

### L2 — English answer ideas
A bottom panel with up to 6 of the interaction's authored answers, shown in **English**. The learner picks one; it appears above the mic as a reminder they must translate themselves.

### L3 — French answer options
The same options in **French**, each with phonetic and a listen button. Picking one **replaces** the English reminder above the mic, now carrying its own small listen button.

**Audio escalation here is *alternating***, unlike the vocab blocks: odd tap = normal, even tap = slow, odd = normal… The learner is rehearsing something they're about to say, so toggling between natural and articulated is the useful motion. Counters are **per row**, and the above-mic reminder shares its row's counter (the count follows the answer, not the UI location).

Listen buttons are **shown even when a row has no audio** — inert rather than hidden, so a missing-audio content gap is visible during testing instead of silently masked.

### The option list — composition and shuffling

Both L2 and L3 are served by **one endpoint**, which returns English *and* French per option.

Target composition: **1 perfect, 3 good, 1 false good, 1 wrong** (6 max). This is a **target, not a requirement** — short content returns fewer, and types are **never backfilled** from one another.

Two levels of randomisation:
- **Within each type** before slicing, so the same three "good" answers don't always appear.
- **Across the final list**, so position never signals quality — the learner must not be able to spot the perfect answer by where it sits.

The set is **cached client-side per interaction**, so closing and reopening a panel shows the same options rather than a fresh shuffle. L3 reuses L2's cached set, so the learner sees the French versions of options they already considered in English.

---

## 6. Data model

### `brain_hint`
| Column | Role |
|---|---|
| `id`, `airtable_record_id`, `name`, `live`, `created_at`, `update_at` | identity/lifecycle |
| `button` | `understand` / `answer` |
| `hint_level` | 1 / 2 / 3 (structural — the press count) |
| `usage`, `type` | author-managed categorisation |
| `media_kind` | `text` / `audio` / `vocab_flow` / image / gif / video |
| `text_en`, `text_fr`, `text_phonetic` | text content |
| `media_url` | Cloudinary URL for media hints |
| `applies_to_tier` | which answer-tier this serves (nullable) |
| `bonus_malus_id` | link to the future `brain_bonus_malus` (nullable, **unused**) |

**No hardcoded enum values.** `button`, `usage`, `type`, `media_kind` are plain author-managed text. Code filters structurally on `button` + `hint_level` + `live` and never on a hardcoded `type` value.

**The malus is a link, not a value** — the score cost will live in `brain_bonus_malus`, so it's managed in one place.

### Where hints attach
| Table | Column | Serves |
|---|---|---|
| `brain_interaction` | `hint_ids` | all Understand levels; Tier-3 and no-answer-yet Answer hints |
| `brain_interaction_answer` | `hint_ids` | Tier-1 Answer hints |
| `brain_attribute_mistake` | `hint_ids` | Tier-2 Answer hints |

### Supporting content columns
| Table | Column | Used by |
|---|---|---|
| `brain_interaction` | `simplified_audio_url` | Understand-L2 |
| `brain_interaction` | `transcription_phonetic` | Understand-L3 reveal |
| `brain_interaction` | `interaction_vocab_id` (ordered) | Understand-L3 blocks |
| `brain_vocab` | `audio_normal_url`, `audio_slow_url` | Understand-L3 block audio |
| `brain_answer` | `transcription_en`, `transcription_fr`, `transcription_phonetic` | Answer-L2/L3 |
| `brain_answer` | `audio_normal_url`, `audio_slow_url` | Answer-L3 listen buttons |
| `session_interaction` | `not_understood_vocab_ids` | Understand-L3 recording (backend-only, never synced) |

---

## 7. Endpoints

| Endpoint | Serves |
|---|---|
| `GET /api/session/interaction-hint?interaction_id&button&hint_level` | Understand L1/L2 (and any single-hint lookup). Also returns `interaction_audio_url` for L2. |
| `GET /api/session/interaction-hint-l3?interaction_id` | Understand-L3: ordered blocks + the translation reveal |
| `GET /api/session/answer-hint?interaction_id&hint_level&tier&interaction_answer_id&attribute_mistake_ids` | Answer-L1, tier-routed |
| `GET /api/session/answer-ideas?interaction_id` | Answer-L2 **and** L3 option list |
| `POST /api/session/record-not-understood-vocab` | Understand-L3 recording |

All return `found: false` with a 200 rather than a 404 when nothing is authored — "no hint at this level" is a normal state, not an error.

**Routing data is passed by the client.** It already holds `tier`, `interaction_answer_id`, and `attribute_mistake_ids` from the last evaluate, so the server does no session lookup.

---

## 8. Client architecture notes

- **`HintAudioPlayer`** (`TuJe/Services/HintAudioPlayer.swift`) — the app's first audio-only playback. An `@MainActor ObservableObject` wrapping `AVPlayer`; `play(urlString:)` seeks to zero and plays (serving both auto-play and replay). Sets `AVAudioSession` to `.playback` so hints are audible with the ringer off. Used by Understand-L2, Understand-L3 blocks, and Answer-L3 options.
- **`currentInteractionId` holds the BRAIN interaction id** despite its generic name; `sessionInteractionId` is the session-scoped one. The L3 recording POST needs the *session* id — sending the wrong one writes nothing silently.
- **`answerIdeaAudioUrl(for:)` mutates tap-count state**, so it must only be called from a button action, never from a computed view property, or the normal/slow alternation desyncs.
- **Z-order:** 60 hints → 65 L3 vocab flow → 66 gate → 67 L2 panel → 68 L3 panel → 70 feedback sheet. The gate and vocab flow are **modal** (`.contentShape(Rectangle())` + empty `.onTapGesture`); the two ideas panels deliberately are not.

---

## 9. Not built yet

- **The malus.** Nothing is recorded about hint usage. When `brain_bonus_malus` is built, usage recording should be added — the `bonus_malus_id` column on `brain_hint` is already there waiting. Placeholder cost was agreed at 1 per press.
- **"Highlight the button when the learner is struggling"** — the nudge described in the original design.
- **Personalisation** from user history ("this learner likes hints").
- **The structural-help finale** on repeated pressing — mentioned in early design, never specified.
- **Finer Tier-3 vs no-answer-yet hint filtering** (via `applies_to_tier` or `type`).
- **Reopening a closed ideas panel** — once at L2, pressing Answer targets L3. Tapping the above-mic reminder would be the natural affordance.
