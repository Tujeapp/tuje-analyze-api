"""
Diagnostic: why does curate_story return no buttons for INT202607060930?

Walks the whole story-purpose chain, one stage at a time, printing what each
stage produced — so the first empty stage identifies the cause.

Run from the repo root with the venv active:
    source venv/bin/activate && python3 debug_story.py
"""
import asyncio
import os
import asyncpg

from button_realization import find_story_distractors
from answer_selection_service import answer_selection_service, SINGLE_SELECT_CONFIGS

INTERACTION_ID = "INT202607060930"
USER_LEVEL = 100
COUNT = 4


def _db_url() -> str:
    """Same source the app uses (os.getenv DATABASE_URL); fall back to .env for
    local runs where the var isn't exported into the shell."""
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    for line in open(".env"):
        line = line.strip()
        if line.startswith("DATABASE_URL"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("DATABASE_URL not found in env or .env")


def _show_bucket(name, items):
    print(f"    {name:12} ({len(items)}):")
    if not items:
        print("        (empty)")
        return
    for it in items:
        print(f"        id={it.get('id')!r:16} type={it.get('answer_type')!r:14} "
              f"text={it.get('transcription_fr')!r}")


async def main():
    pool = await asyncpg.create_pool(_db_url(), min_size=1, max_size=2)
    try:
        # ------------------------------------------------------------------
        print("=" * 72)
        print(f"1. RAW ANSWERS on {INTERACTION_ID}")
        print("=" * 72)
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT ba.id,
                       bia.answer_type,
                       ba.transcription_fr,
                       ba.live            AS answer_live,
                       bia.live           AS join_live,
                       COALESCE(bia.never_a_button, FALSE) AS never_a_button
                FROM brain_interaction_answer bia
                JOIN brain_answer ba ON ba.id = bia.answer_id
                WHERE bia.interaction_id = $1
                ORDER BY bia.answer_type, ba.id
            """, INTERACTION_ID)
            if not rows:
                print("    (NO answers linked to this interaction at all)")
            for r in rows:
                print(f"    id={r['id']!r:16} type={r['answer_type']!r:14} "
                      f"live={r['answer_live']}/{r['join_live']} "
                      f"never_button={r['never_a_button']} "
                      f"text={r['transcription_fr']!r}")

            # Context that determines whether ANY distractor can be borrowed.
            meta = await conn.fetchrow("""
                SELECT subtopic_id, live,
                       COALESCE(variant_ids, ARRAY[]::text[]) AS variant_ids
                FROM brain_interaction WHERE id = $1
            """, INTERACTION_ID)
            print()
            if meta is None:
                print("    ⚠️  interaction NOT FOUND in brain_interaction")
            else:
                print(f"    subtopic_id = {meta['subtopic_id']!r}  live={meta['live']}")
                print(f"    variant_ids = {list(meta['variant_ids'])}")
                siblings = await conn.fetchval("""
                    SELECT count(*) FROM brain_interaction
                    WHERE live = true AND subtopic_id = $1 AND id <> $2
                """, meta['subtopic_id'], INTERACTION_ID)
                print(f"    other live interactions in same subtopic = {siblings}")

            # ------------------------------------------------------------------
            print()
            print("=" * 72)
            print("2. find_story_distractors (both tiers)")
            print("=" * 72)
            for same_sub in (True, False):
                label = "same-subtopic (subtle)" if same_sub else "cross-subtopic (obvious)"
                d = await find_story_distractors(
                    conn, INTERACTION_ID, USER_LEVEL, count=COUNT, same_subtopic=same_sub
                )
                print(f"  [{label}] -> {len(d)} distractor(s)")
                for x in d:
                    print(f"        id={x['id']!r} type={x['answer_type']!r} "
                          f"text={x['transcription_fr']!r}")

        # ------------------------------------------------------------------
        print()
        print("=" * 72)
        print("3. _fetch_answers_for_story (buckets)")
        print("=" * 72)
        available = await answer_selection_service._fetch_answers_for_story(
            INTERACTION_ID, USER_LEVEL, pool, count=COUNT, same_subtopic=True
        )
        print("  sizes:", {k: len(v) for k, v in available.items()})
        for name in ("perfect", "good", "false good", "wrong"):
            _show_bucket(name, available.get(name, []))

        # ------------------------------------------------------------------
        print()
        print("=" * 72)
        print("4. _select_configuration(available, SINGLE_SELECT_CONFIGS, 'medium')")
        print("=" * 72)
        selected_config, difficulty_used = answer_selection_service._select_configuration(
            available, SINGLE_SELECT_CONFIGS, "medium"
        )
        print(f"    config     = {selected_config}")
        print(f"    difficulty = {difficulty_used}")
        if selected_config is None:
            print("    ⚠️  No satisfiable config — this is why curate_story returns story_empty.")
            print("    Needed per config vs available:")
            for n_buttons, configs in sorted(SINGLE_SELECT_CONFIGS.items()):
                for cfg, diff in configs:
                    need = {}
                    for t in cfg:
                        need[t] = need.get(t, 0) + 1
                    missing = {t: (c, len(available.get(t, []))) for t, c in need.items()
                               if len(available.get(t, [])) < c}
                    if missing:
                        print(f"        {diff:6} {cfg} -> short: "
                              + ", ".join(f"{t} need {c} have {h}" for t, (c, h) in missing.items()))

        # ------------------------------------------------------------------
        print()
        print("=" * 72)
        print("5. curate_story (full result)")
        print("=" * 72)
        result = await answer_selection_service.curate_story(
            INTERACTION_ID, USER_LEVEL, pool,
            cycle_level_direction=0, selection_mode="single", count=COUNT
        )
        print(f"    difficulty    = {result['difficulty']}")
        print(f"    config        = {result['config']}")
        print(f"    correct_count = {result['correct_count']}")
        print(f"    selection_mode= {result['selection_mode']}")
        print(f"    answers ({len(result['answers'])}):")
        for a in result["answers"]:
            print(f"        id={a['id']!r} type={a['answer_type']!r} "
                  f"text={a['transcription_fr']!r}")

    finally:
        await pool.close()


asyncio.run(main())
