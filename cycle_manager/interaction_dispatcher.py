"""
Interaction dispatcher: decides how an already-selected interaction is PRESENTED
(voice vs buttons, and which button purpose) — a presentation-layer decision.
Selection is already goal-correct at cycle-start; this only chooses presentation.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Plans that default to buttons vs voice.
_BUTTON_DEFAULT_PLANS = frozenset({"free", "basic"})
_VOICE_DEFAULT_PLANS = frozenset({"pro"})
# Authored interaction-type modes that override the plan default.
_AUTHORED_BUTTON_MODES = frozenset({"multipleButtons", "singleButton"})


def decide_interaction_mode_and_purpose(
    plan: str | None,
    cycle_goal: str | None,
    rescue_level: float = 0.0,
    authored_mode: str | None = None,
) -> tuple[str, str | None]:
    """
    Returns (answer_mode, button_purpose).

    STAGE 1 — mode (voice vs multipleButtons):
      authored multipleButtons/singleButton (interaction type) -> that mode,
                 regardless of plan
      free/basic -> multipleButtons (buttons by default)
      pro        -> voice (default). Pro-escalation-to-buttons (slow session /
                    high frustration / level going down) is DRAFT — stubbed for
                    now (pro stays voice). TODO when those conditions are defined.
      unknown    -> voice (safe default)

    STAGE 2 — button_purpose (only meaningful when mode == multipleButtons):
      intent cycle -> 'vocab_review'  (dormant: no intent cycles exist yet)
      story cycle  -> 'story'         (own answers + borrowed wrong-conversation)
      notion cycle -> 'notion'        (answers carrying the cycle's target notion)
      other/unknown-> 'default'       (routes to the authored-button path)
      voice mode   -> None            (voice interactions have no button purpose)

    NOTE: rescue's quick-help is NOT decided here — it's a client-triggered
    runtime override (rescue_triggered) applied at answer-fetch time. This helper
    stamps the PLANNED purpose for a buttons interaction. rescue_level is accepted
    for the future pro-escalation logic (currently unused).
    """
    plan_norm = (plan or "").strip().lower()

    # STAGE 1
    if authored_mode in _AUTHORED_BUTTON_MODES:
        answer_mode = authored_mode
    elif plan_norm in _BUTTON_DEFAULT_PLANS:
        answer_mode = "multipleButtons"
    elif plan_norm in _VOICE_DEFAULT_PLANS:
        answer_mode = "voice"
        # TODO pro-escalation: if session too slow / rescue_level high /
        # level_direction down -> answer_mode = "multipleButtons". Draft; not built.
    else:
        if plan_norm:
            logger.info(f"decide_interaction: unknown plan '{plan_norm}', defaulting to voice")
        answer_mode = "voice"

    # STAGE 2
    if answer_mode != "multipleButtons":
        button_purpose = None
    else:
        goal = (cycle_goal or "").strip().lower()
        if goal == "intent":
            button_purpose = "vocab_review"   # dormant until intent cycles exist
        elif goal == "story":
            button_purpose = "story"
        elif goal == "notion":
            button_purpose = "notion"
        else:
            button_purpose = "default"        # unknown goal -> authored-button path

    return (answer_mode, button_purpose)


async def resolve_mode_and_purpose(db_pool, user_id: str, cycle_goal,
                                   brain_interaction_id: str | None = None):
    """
    Fetch the user's plan + rescue_level, then decide (answer_mode, button_purpose)
    for a session_interaction being created. Shared by both creation sites
    (cycle-start and advance). Fails safe to voice/None on any fetch issue.

    When brain_interaction_id is given, also reads its interaction type's
    authored answer_mode on the same connection; an authored button mode wins
    over the plan. No extra query when it is None.
    """
    plan = None
    rescue_level = 0.0
    authored_mode = None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT subscription_tier FROM brain_user WHERE id = $1", user_id
            )
            if row:
                plan = row["subscription_tier"]
            rl = await conn.fetchval(
                "SELECT rescue_level FROM user_behavior WHERE user_id = $1", user_id
            )
            if rl is not None:
                rescue_level = float(rl)
            if brain_interaction_id:
                authored_mode = await conn.fetchval("""
                    SELECT bit.answer_mode
                    FROM brain_interaction bi
                    JOIN brain_interaction_type bit ON bi.interaction_type_id = bit.id
                    WHERE bi.id = $1
                """, brain_interaction_id)
    except Exception as e:
        logger.warning(f"resolve_mode_and_purpose: fetch failed for user {user_id}: {e}; defaulting")
    return decide_interaction_mode_and_purpose(plan, cycle_goal, rescue_level, authored_mode)
