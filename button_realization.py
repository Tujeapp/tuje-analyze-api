"""
Button realization: turn a templated answer (e.g. "J'ai un entityAnimal") into
one or more displayable button strings by filling its entity slot(s) with
vocab whose attributes match the template's requirements.

First version: single-entity templates, rescue-legibility context.
- Parses the entity token from transcription_fr (e.g. 'entityAnimal').
- Maps the token to a brain_entity by name.
- Selects vocab in that entity where the template's required attributes are a
  subset of the vocab's (own attribute_ids UNION pairing_attribute_ids),
  filtered by level_own <= user_level, ranked by commonness desc.
- Replaces the token in transcription_fr with the chosen vocab's transcription_fr.
"""
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Matches an entity token like 'entityAnimal', 'entityNumber' in readable text.
ENTITY_TOKEN_RE = re.compile(r'entity[A-Z][a-zA-Z]*')


def find_entity_tokens(text: str) -> list[str]:
    """Return the entity tokens present in a template's transcription_fr, e.g. ['entityAnimal']."""
    return ENTITY_TOKEN_RE.findall(text or "")


async def realize_template(
    conn,
    template_transcription_fr: str,
    template_attribute_ids: list[str],
    user_level: int,
    max_fills: int = 1,
) -> list[str]:
    """
    Realize a single-entity template into up to max_fills display strings.

    Returns [] if: no entity token found (caller should treat a literal template
    as already-displayable), or the entity is unknown, or no vocab qualifies.

    A literal answer (no entity token) is NOT this function's job — the caller
    decides that a token-free template is used as-is.
    """
    tokens = find_entity_tokens(template_transcription_fr)
    if not tokens:
        return []  # literal — caller uses transcription_fr directly

    # First version handles ONE entity slot. Report if multiple (future work).
    if len(tokens) > 1:
        logger.warning(
            f"realize_template: multiple entity tokens {tokens} in "
            f"'{template_transcription_fr}' — only single-slot supported for now; skipping"
        )
        return []

    token = tokens[0]  # e.g. 'entityAnimal'

    # Map the token to a brain_entity. Convention: the entity's `name` column
    # holds the token verbatim (e.g. 'entityAnimal').
    entity_id = await conn.fetchval(
        "SELECT id FROM brain_entity WHERE name = $1 AND live = true", token
    )
    if entity_id is None:
        logger.warning(f"realize_template: no brain_entity named '{token}'")
        return []

    # Candidate vocab in this entity, level-gated, ranked by commonness.
    # Union-match: the template's required attributes must all be present in the
    # vocab's own attribute_ids OR its pairing_attribute_ids.
    rows = await conn.fetch(
        """
        SELECT transcription_fr, attribute_ids, pairing_attribute_ids, commonness
        FROM brain_vocab
        WHERE entity_type_id = $1
          AND live = true
          AND (level_own IS NULL OR level_own <= $2)
        ORDER BY commonness DESC NULLS LAST, transcription_fr
        """,
        entity_id, user_level,
    )

    required = set(template_attribute_ids or [])
    picks: list[str] = []
    for r in rows:
        own = set(r["attribute_ids"] or [])
        pairing = set(r["pairing_attribute_ids"] or [])
        if required.issubset(own | pairing):
            # Replace the token with this vocab's readable form.
            display = template_transcription_fr.replace(token, r["transcription_fr"])
            picks.append(display)
            if len(picks) >= max_fills:
                break

    if not picks:
        logger.info(
            f"realize_template: no vocab in {entity_id} satisfied required attrs "
            f"{required} at level {user_level}"
        )
    return picks


async def curate_quick_help(
    conn,
    interaction_id: str,
    user_level: int,
    count: int = 4,
) -> list[dict]:
    """
    Rescue 'quick-help' purpose: one clearly-correct answer + (count-1) clearly-
    wrong distractors, so the right one is easy to spot. Templates are realized
    to a single common vocab fill; literals used as-is.

    Returns answer DICTS. Each button's `id` is the UNDERLYING answer id (the
    template for realized buttons) — that is what the client submits on tap, and
    scoring treats the tap as that answer (design Option A: the vocab fill is a
    valid instance of the template, so it inherits the template's type/level).
    `transcription_fr` is the realized display text.

    v1 gaps (deferred): no readiness/notion filter, no positive-structure
    preference, no shuffle (UI shuffles), single common fill per template.
    """
    rows = await conn.fetch(
        """
        SELECT ba.id, ba.transcription_fr, ba.transcription_en, ba.image_url,
               ba.answer_optimum_level, ba.attribute_ids,
               bia.answer_type, bia.answer_typicality
        FROM brain_interaction_answer bia
        JOIN brain_answer ba ON ba.id = bia.answer_id
        WHERE bia.interaction_id = $1
          AND bia.live = true
          AND COALESCE(bia.never_a_button, false) = false
        ORDER BY bia.answer_typicality DESC NULLS LAST, ba.id
        """,
        interaction_id,
    )

    async def build_button(r) -> Optional[dict]:
        # Template → realize to ONE common fill; literal → use as-is.
        display = r["transcription_fr"]
        if not display:
            return None  # no French text → can't render as a button (client requires it)
        if find_entity_tokens(display):
            realized = await realize_template(
                conn, display, r["attribute_ids"], user_level, max_fills=1
            )
            if not realized:
                return None            # template couldn't realize (e.g. level) → skip
            display = realized[0]
        return {
            "id": r["id"],             # underlying answer id — client submits THIS
            "transcription_fr": display,
            "transcription_en": r["transcription_en"],
            "image_url": r["image_url"],
            "answer_optimum_level": r["answer_optimum_level"],
            "answer_type": r["answer_type"],
            "is_button": True,
        }

    # 1) correct: prefer 'perfect', else highest-typicality 'good'
    correct: Optional[dict] = None
    for want in ("perfect", "good"):
        for r in rows:
            if r["answer_type"] == want:
                b = await build_button(r)
                if b:
                    correct = b
                    break
        if correct:
            break

    # 2) distractors: 'wrong', realized if templates
    seen_text = {correct["transcription_fr"]} if correct else set()
    distractors: list[dict] = []
    for r in rows:
        if r["answer_type"] == "wrong":
            b = await build_button(r)
            if b and b["transcription_fr"] not in seen_text:
                distractors.append(b)
                seen_text.add(b["transcription_fr"])
            if len(distractors) >= count - 1:
                break

    buttons: list[dict] = []
    if correct:
        buttons.append(correct)
    buttons.extend(distractors)

    if len(buttons) < count:
        logger.info(
            f"curate_quick_help({interaction_id}): only {len(buttons)} buttons "
            f"(wanted {count}) — pool may lack enough wrong distractors"
        )
    return buttons[:count]


# Sentinel used to normalize a template into a comparable "frame" (entity slot blanked).
_FRAME_SLOT = "\x00"


def _template_frame(transcription_fr: str) -> Optional[tuple]:
    """
    Reduce a template to its (frame, entity_token). The frame is the text with
    its entity token replaced by a sentinel, so two templates with the same
    surrounding words but different entities share a frame.
    Returns None if there is not exactly one entity token.
    """
    tokens = find_entity_tokens(transcription_fr or "")
    if len(tokens) != 1:
        return None
    token = tokens[0]
    frame = transcription_fr.replace(token, _FRAME_SLOT)
    return (frame, token)


async def find_frame_swap_distractors(
    conn,
    target_transcription_fr: str,
    user_level: int,
    count: int = 3,
    exclude_answer_ids: Optional[set] = None,
) -> list[dict]:
    """
    Vocab-review distractors that share the TARGET's frame but use a DIFFERENT
    entity, realized into level-appropriate vocab. E.g. target
    "J'ai un entityAnimal" -> distractors "J'ai un pull", "J'ai un kiwi".

    These are grammatically valid sentences (their templates are authored real
    answers elsewhere) but WRONG answers for this interaction. Returns dicts:
      { id, transcription_fr, transcription_en, image_url, answer_type }
    with answer_type = "wrong" and id = a sentinel ("FRAMESWAP") because the
    borrowed template does NOT belong to this interaction (submit-scoring treats
    a FRAMESWAP tap as a known wrong; that integration is handled by the caller).

    Fails safe (returns []) if the target has no single entity token or no
    frame-mates realize.
    """
    target = _template_frame(target_transcription_fr)
    if target is None:
        return []  # target isn't a single-slot template — no frame to swap
    target_frame, target_token = target
    exclude_answer_ids = exclude_answer_ids or set()

    # Fetch all live templates that contain an entity token (candidates).
    rows = await conn.fetch(
        """
        SELECT DISTINCT ba.id, ba.transcription_fr, ba.transcription_en,
               ba.image_url, ba.attribute_ids
        FROM brain_answer ba
        WHERE ba.live = true
          AND ba.transcription_fr LIKE '%entity%'
        """
    )

    distractors: list[dict] = []
    seen_text = set()
    for r in rows:
        if r["id"] in exclude_answer_ids:
            continue
        mate = _template_frame(r["transcription_fr"])
        if mate is None:
            continue
        mate_frame, mate_token = mate
        # Same frame, DIFFERENT entity.
        if mate_frame != target_frame or mate_token == target_token:
            continue
        realized = await realize_template(
            conn, r["transcription_fr"], r["attribute_ids"], user_level, max_fills=count
        )
        for text in realized:
            if text in seen_text:
                continue
            seen_text.add(text)
            distractors.append({
                "id": "FRAMESWAP",                 # sentinel — not a real answer here
                "transcription_fr": text,
                "transcription_en": r["transcription_en"],
                "image_url": r["image_url"],
                "answer_type": "wrong",
            })
            if len(distractors) >= count:
                return distractors
    return distractors


async def find_story_distractors(
    conn,
    interaction_id: str,
    user_level: int,
    count: int = 3,
    same_subtopic: bool = True,
) -> list[dict]:
    """
    Story-purpose distractors: borrow perfect/good answers from OTHER interactions
    — valid responses to a DIFFERENT question, hence wrong for this one.

    Distance is the difficulty lever:
      same_subtopic=True  -> subtle (same scene, different question:
                             "Votre billet ?" answers vs a passport question)
      same_subtopic=False -> obvious (a different subtopic entirely)

    Excludes the current interaction AND its variants (bidirectionally: both the
    ids this interaction lists, and any interaction listing this one) — a variant's
    answer would be VALID here, so borrowing it would create a false-wrong.

    Returns dicts {id:"BORROWED", transcription_fr, transcription_en, image_url,
    answer_type:"wrong"}. The sentinel id is used because the borrowed answer has
    no brain_interaction_answer row for THIS interaction; the submit path scores a
    BORROWED tap as wrong directly. Fails safe ([]).
    """
    # Current interaction: subtopic + its declared variants.
    cur = await conn.fetchrow(
        """
        SELECT subtopic_id, COALESCE(variant_ids, ARRAY[]::text[]) AS variant_ids
        FROM brain_interaction
        WHERE id = $1
        """,
        interaction_id,
    )
    if not cur:
        logger.warning(f"find_story_distractors: interaction {interaction_id} not found")
        return []

    # Bidirectional exclusion: self + ids it lists + ids that list it.
    reverse = await conn.fetch(
        "SELECT id FROM brain_interaction WHERE variant_ids @> ARRAY[$1]::text[]",
        interaction_id,
    )
    excluded = {interaction_id}
    excluded.update(cur["variant_ids"] or [])
    excluded.update(r["id"] for r in reverse)

    # Candidate source interactions by tier.
    if same_subtopic:
        rows = await conn.fetch(
            """
            SELECT id FROM brain_interaction
            WHERE live = true AND subtopic_id = $1 AND id <> ALL($2::text[])
            ORDER BY id
            """,
            cur["subtopic_id"], list(excluded),
        )
    else:
        rows = await conn.fetch(
            """
            SELECT id FROM brain_interaction
            WHERE live = true AND subtopic_id IS DISTINCT FROM $1 AND id <> ALL($2::text[])
            ORDER BY id
            LIMIT 50
            """,
            cur["subtopic_id"], list(excluded),
        )
    if not rows:
        logger.info(f"find_story_distractors: no source interactions for {interaction_id} (same_subtopic={same_subtopic})")
        return []

    distractors: list[dict] = []
    seen_text = set()
    for r in rows:
        # Borrow that interaction's VALID answers (valid there = wrong here).
        answers = await conn.fetch(
            """
            SELECT ba.transcription_fr, ba.transcription_en, ba.image_url, ba.attribute_ids
            FROM brain_interaction_answer bia
            JOIN brain_answer ba ON ba.id = bia.answer_id
            WHERE bia.interaction_id = $1
              AND bia.live = true
              AND bia.answer_type IN ('perfect','good')
              AND ba.live = true
              AND COALESCE(bia.never_a_button, false) = false
            ORDER BY bia.answer_typicality DESC NULLS LAST, ba.id
            """,
            r["id"],
        )
        for a in answers:
            fr = a["transcription_fr"]
            if not fr:
                continue
            if find_entity_tokens(fr):
                realized = await realize_template(conn, fr, a["attribute_ids"], user_level, max_fills=1)
                if not realized:
                    continue
                text = realized[0]
            else:
                text = fr
            if text in seen_text:
                continue
            seen_text.add(text)
            distractors.append({
                "id": "BORROWED",
                "transcription_fr": text,
                "transcription_en": a["transcription_en"],
                "image_url": a["image_url"],
                "answer_type": "wrong",
            })
            if len(distractors) >= count:
                return distractors
    return distractors
