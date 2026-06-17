#!/usr/bin/env python3
# ============================================================================
# diagnose_search.py - Search Decision Tracer (READ-ONLY)  v2
# ============================================================================
# Explains WHY the engine picks the subtopic and interactions it does, by
# mirroring interaction_search.search_interactions / find_best_subtopic_with_fallback.
# Prints the full decision tree per fallback phase:
#   - every subtopic, whether it passes the subtopic-level filter (+ why not)
#   - for subtopics that pass: how many interactions qualify, and when they fall
#     short, WHICH condition is to blame (level / boredom / mood) via per-condition counts
#   - the best-subtopic contest and which phase fires
#   - a RESULT note that reads BOTH the healthy "new subtopic won" case and the
#     problem cases (seen-recycling, ties, content gaps)
#
# READ-ONLY: only SELECTs. Writes nothing. Run as often as you like.
#
# MIRRORS interaction_search.py AS OF 2026-06-17. If that query changes
# (level filter, boredom filter, mood/type join, best-subtopic pick, phases),
# UPDATE THIS FILE to match or it will explain the engine WRONGLY.
#
# RUN:
#   cd ~/Desktop/tuje-analyze-api
#   source venv/bin/activate
#   set -a; source .env; set +a
#   python diagnose_search.py
# ============================================================================

import asyncio
import os
import asyncpg

from session_context import SessionContext
from helpers import get_mood_types

# ============================================================================
# CONFIG - match these to the scenario you want to explain
# ============================================================================
USER_ID = "D08BC99B-0996-4E2B-B4FB-80CF9E0B33DC"   # note: case-sensitive (R33)
CYCLE_BOREDOM = 0.30
INTERACTION_USER_LEVEL = 50
SESSION_MOOD = "effective"
MIN_REQUIRED = 7   # the >=7 threshold the engine needs per subtopic
# ============================================================================


def hr(title=""):
    print("\n" + "=" * 74)
    if title:
        print(title)
        print("=" * 74)


def _f(v):
    """Format a boredom value tidily (avoid the long float tail)."""
    return "None" if v is None else f"{float(v):.2f}"


async def explain_phase(conn, context, level, boredom, mood_types_lower, mode, label):
    """Mirror one search_interactions call and explain it, with per-condition detail."""
    level_min = max(0, level - 50)
    level_max = level + 50
    seen_subs = list(context.seen_subtopics)

    sub_rows = await conn.fetch(
        "SELECT s.id, s.level_from, s.boredom, s.live FROM brain_subtopic s "
        "WHERE s.live = true ORDER BY s.id"
    )

    print(f"\n--- {label}  (mode={mode}, level_window=[{level_min},{level_max}], boredom>={boredom:.2f}) ---")
    print(f"  {'subtopic':<22} {'qualify':>7}  note / why short")
    print("  " + "-" * 80)

    results = []  # (sid, qualifying_count, seen_bool)
    for s in sub_rows:
        sid = s["id"]
        seen = sid in seen_subs

        # --- Subtopic-level filter (mirrors target_subtopics) ---
        sub_reasons = []
        if s["level_from"] is None or s["level_from"] < level_min:
            sub_reasons.append(f"sub level_from={s['level_from']} < {level_min}")
        if s["boredom"] is None or float(s["boredom"]) < boredom:
            sub_reasons.append(f"sub boredom={_f(s['boredom'])} < {boredom:.2f}")
        if mode == "new_only" and seen:
            sub_reasons.append("SEEN (excluded in new_only)")

        if sub_reasons:
            print(f"  {sid:<22} {0:>7}  subtopic filtered: {'; '.join(sub_reasons)}")
            results.append((sid, 0, seen))
            continue

        # --- Interaction filter, full + per-condition (#1) ---
        row = await conn.fetchrow(
            """
            SELECT
              COUNT(*) FILTER (
                WHERE i.level_from BETWEEN $2 AND $3
                  AND i.boredom >= $4
                  AND LOWER(bit.name) = ANY($5::varchar[])
              ) AS qualifying,
              COUNT(*) AS total_live,
              COUNT(*) FILTER (WHERE i.level_from BETWEEN $2 AND $3) AS pass_level,
              COUNT(*) FILTER (WHERE i.boredom >= $4) AS pass_boredom,
              COUNT(*) FILTER (WHERE LOWER(bit.name) = ANY($5::varchar[])) AS pass_mood
            FROM brain_interaction i
            JOIN brain_interaction_type bit ON i.interaction_type_id = bit.id
            WHERE i.live = true AND i.subtopic_id = $1
            """,
            sid, level_min, level_max, boredom, mood_types_lower,
        )
        q = row["qualifying"]
        seen_tag = "(SEEN)" if seen else "(new)"
        if q >= MIN_REQUIRED:
            print(f"  {sid:<22} {q:>7}  {seen_tag}  >= {MIN_REQUIRED}")
        else:
            why = (f"{seen_tag} short: total={row['total_live']} "
                   f"pass_level={row['pass_level']} pass_boredom={row['pass_boredom']} "
                   f"pass_mood={row['pass_mood']}")
            print(f"  {sid:<22} {q:>7}  {why}")
        results.append((sid, q, seen))

    eligible = [(sid, q, seen) for sid, q, seen in results if q >= MIN_REQUIRED]
    if eligible:
        eligible_sorted = sorted(eligible, key=lambda x: -x[1])
        winner = eligible_sorted[0]
        tie = [e for e in eligible_sorted if e[1] == winner[1]]
        print(f"\n  -> {len(eligible)} subtopic(s) have >= {MIN_REQUIRED}. WINNER: {winner[0]} ({winner[1]})")
        if len(tie) > 1:
            print(f"     TIE: {len(tie)} subtopics tied at {winner[1]} -- winner decided by ordering,")
            print(f"     not by merit. Tie-break logic is effectively arbitrary here.")
        print(f"  -> PHASE SUCCEEDS -- pool = {winner[0]}'s qualifying interactions.")
        return winner
    else:
        print(f"\n  -> NO subtopic has >= {MIN_REQUIRED}. PHASE FAILS -> fall through.")
        return None


async def main():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL not set. Run: set -a; source .env; set +a")

    mood_types = get_mood_types(SESSION_MOOD)
    mood_types_lower = [m.lower() for m in mood_types]

    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=2)
    try:
        context = await SessionContext.load(USER_ID, pool)

        win_lo = max(0, INTERACTION_USER_LEVEL - 50)
        win_hi = INTERACTION_USER_LEVEL + 50

        hr("CONFIG")
        print(f"  user_id        : {USER_ID}")
        print(f"  cycle_boredom  : {CYCLE_BOREDOM}")
        print(f"  user_level     : {INTERACTION_USER_LEVEL}  (window [{win_lo},{win_hi}])")
        print(f"  session_mood   : {SESSION_MOOD} -> types {mood_types_lower}")
        print(f"  min required   : {MIN_REQUIRED} qualifying interactions per subtopic")
        print(f"  seen_subtopics : {sorted(context.seen_subtopics)}")
        print("\n  Column key for SHORT subtopics:")
        print("    total        = live interactions in the subtopic")
        print("    pass_level   = how many fall in the level window")
        print("    pass_boredom = how many have interaction-boredom >= the (possibly relaxed) cycle boredom")
        print("    pass_mood    = how many have a type matching the session mood")
        print("    qualify      = how many pass ALL THREE at once (the binding number)")

        hr("FALLBACK DECISION TREE (mirrors find_best_subtopic_with_fallback)")
        async with pool.acquire() as conn:
            winner = None
            phase_succeeded = None

            winner = await explain_phase(conn, context, INTERACTION_USER_LEVEL, CYCLE_BOREDOM,
                                         mood_types_lower, "new_only", "PHASE 1: new subtopics only")
            if winner:
                phase_succeeded = "Phase 1 (new only, requested boredom)"
            if not winner:
                winner = await explain_phase(conn, context, INTERACTION_USER_LEVEL, CYCLE_BOREDOM,
                                             mood_types_lower, "new_and_seen", "PHASE 2: new + seen subtopics")
                if winner:
                    phase_succeeded = "Phase 2 (new+seen, requested boredom)"
            if not winner:
                for i in range(5):
                    b = max(0.0, CYCLE_BOREDOM - 0.1 * (i + 1))
                    winner = await explain_phase(conn, context, INTERACTION_USER_LEVEL, b,
                                                 mood_types_lower, "new_and_seen", f"PHASE 3.{i+1}: boredom={b:.2f}")
                    if winner:
                        phase_succeeded = f"Phase 3 (boredom relaxed to {b:.2f})"
                        break
            if not winner:
                for i in range(3):
                    lv = max(0, INTERACTION_USER_LEVEL - 50 * (i + 1))
                    winner = await explain_phase(conn, context, lv, 0.0,
                                                 mood_types_lower, "new_and_seen", f"PHASE 4.{i+1}: level={lv}, boredom=0")
                    if winner:
                        phase_succeeded = f"Phase 4 (level relaxed to {lv}, boredom 0)"
                        break

        # ---- Smarter RESULT note (#2) ----
        hr("RESULT")
        if winner:
            sid, cnt, seen = winner
            tag = "a SEEN subtopic" if seen else "a NEW subtopic"
            print(f"  Engine builds the cycle from: {sid} ({tag})")
            print(f"  Reached via: {phase_succeeded}")
            print("")
            if not seen and phase_succeeded.startswith("Phase 1"):
                print("  HEALTHY: a new subtopic won at the requested boredom, no fallback needed.")
                print("  The engine is reaching fresh content as intended.")
            elif not seen:
                print("  OK-ish: a NEW subtopic won (good -- fresh content), but only after FALLBACK")
                print(f"  ({phase_succeeded}). Phase 1 at the requested boredom couldn't field {MIN_REQUIRED}.")
                print("  Likely cause: too few interactions per subtopic clear the requested boredom")
                print("  (see pass_boredom in the phases above). Content-distribution tuning, not a bug.")
            else:
                print("  SEEN subtopic won. If this repeats, the engine is recycling familiar content.")
                print("  Check the phases above: did Phase 1 (new-only) fail for lack of qualifying")
                print("  interactions in fresh subtopics? If so it's a content gap, not a logic bug.")
        else:
            print("  No subtopic satisfied even the final fallback -- InsufficientInteractionsError.")
            print("  CONTENT gap: not enough qualifying interactions anywhere. Check pass_level /")
            print("  pass_boredom / pass_mood in the phases above to see which filter is starving it.")

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
