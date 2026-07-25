import json
import logging
from typing import Optional

logger = logging.getLogger("bonus_malus")


# ---- per-rule handlers -----------------------------------------------------
# Each handler receives (metric_row, conditions) and returns a SIGNED int
# adjustment (negative for a malus, positive for a bonus), already accounting
# for the rule's own `value`. metric_row is the session_interaction record.

def _count_over_threshold(count: int, conditions: dict, value: int, sign: int) -> int:
    """Shared logic for count-based rules (attempts, listens):
    free_threshold items are free; each item beyond it costs `value`
    (if per_extra) or a single flat `value` (if not). Returns signed points."""
    threshold = conditions.get("free_threshold", 0)
    over = max(0, (count or 0) - threshold)
    if over == 0:
        return 0
    per_extra = conditions.get("per_extra", True)
    magnitude = value * over if per_extra else value
    return sign * magnitude


def _handle_attempt_count(metric_row, conditions, value, sign) -> int:
    return _count_over_threshold(metric_row.get("attempts_count"), conditions, value, sign)


def _handle_listen_count(metric_row, conditions, value, sign) -> int:
    return _count_over_threshold(metric_row.get("listen_count"), conditions, value, sign)


_HANDLERS = {
    "ATTEMPT_COUNT": _handle_attempt_count,
    "LISTEN_COUNT": _handle_listen_count,
}


# ---- engine ----------------------------------------------------------------

async def evaluate_interaction_bonus_malus(
    session_interaction_id: str,
    user_level: int,
    db_pool,
) -> dict:
    """Evaluate all live interaction-scope bonus/malus rules for one interaction.

    Returns a dict:
      {
        "total_adjustment": int,          # signed sum, NOT yet clamped
        "applied": [                       # per-rule breakdown (for debug/audit)
          {"id","rule_code","name_en","adjustment"}
        ],
        "skipped_rule_codes": [str],       # rules with no handler
      }

    The caller adds total_adjustment to the gross score and clamps to [0,100].
    This function does NOT read or write any score — it's pure evaluation.
    """
    result = {"total_adjustment": 0, "applied": [], "skipped_rule_codes": []}

    async with db_pool.acquire() as conn:
        metric_row = await conn.fetchrow("""
            SELECT attempts_count, listen_count
            FROM session_interaction
            WHERE id = $1
        """, session_interaction_id)
        if metric_row is None:
            logger.warning(f"bonus_malus: no session_interaction {session_interaction_id}")
            return result
        metrics = dict(metric_row)

        rules = await conn.fetch("""
            SELECT id, rule_code, name_en, value, bonus_malus_type,
                   conditions, priority,
                   level_from, level_to
            FROM brain_bonus_malus
            WHERE live = TRUE
              AND scope = 'interaction'
              AND (level_from IS NULL OR $1 >= level_from)
              AND (level_to   IS NULL OR $1 <= level_to)
            ORDER BY priority ASC, id ASC
        """, user_level)

    total = 0
    for r in rules:
        handler = _HANDLERS.get(r["rule_code"])
        if handler is None:
            result["skipped_rule_codes"].append(r["rule_code"])
            logger.warning(f"bonus_malus: no handler for rule_code={r['rule_code']} (rule {r['id']})")
            continue
        try:
            # conditions is jsonb — asyncpg may hand it back as a str.
            raw_conditions = r["conditions"]
            if isinstance(raw_conditions, str):
                conditions = json.loads(raw_conditions) if raw_conditions else {}
            else:
                conditions = raw_conditions or {}
            # Strict: only exactly "malus" subtracts. Anything else is a bonus,
            # so a mis-typed malus would become a bonus — acceptable for now,
            # but the authored values were checked to be exactly bonus/malus.
            sign = -1 if r["bonus_malus_type"] == "malus" else 1
            value = r["value"] or 0
            adjustment = handler(metrics, conditions, value, sign)
        except Exception as e:
            logger.error(f"bonus_malus: rule {r['id']} ({r['rule_code']}) failed: {e}")
            result["skipped_rule_codes"].append(r["rule_code"])
            continue
        if adjustment != 0:
            total += adjustment
            result["applied"].append({
                "id": r["id"],
                "rule_code": r["rule_code"],
                "name_en": r["name_en"],
                "adjustment": adjustment,
            })

    result["total_adjustment"] = total
    return result


def clamp_score(gross: int, adjustment: int) -> int:
    """Apply an adjustment and clamp to [0, 100]. Provided here so the scoring
    task uses one clamp definition rather than duplicating it."""
    return max(0, min(100, gross + adjustment))
