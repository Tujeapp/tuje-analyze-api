import asyncio
import os
import asyncpg
from button_realization import realize_template, curate_quick_help, find_frame_swap_distractors
from answer_selection_service import answer_selection_service


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


CASES = [
    ("J'ai un entityAnimal",  ["ATTR202411120628"], 100, 3, "un @100"),
    ("J'ai une entityAnimal", ["ATTR202411120227"], 100, 3, "une @100"),
    ("J'ai un entityAnimal",  ["ATTR202411120628"], 200, 5, "un @200 (âne in)"),
    ("J'ai un entityAnimal",  ["ATTR202411120628"], 40,  3, "un @40 (none)"),
    ("Je n'ai pas d'animaux", [], 100, 3, "literal (none)"),
]


async def main():
    conn = await asyncpg.connect(_db_url())
    try:
        for tr, attrs, lvl, mx, label in CASES:
            res = await realize_template(conn, tr, attrs, lvl, max_fills=mx)
            print(f"[{label}] -> {res}")

        print("\n=== curate_quick_help (dicts) ===")
        for lvl in (100, 40):
            buttons = await curate_quick_help(conn, 'INT202607041224', user_level=lvl, count=4)
            print(f"[quick_help @level{lvl}]")
            for b in buttons:
                print(f"    id={b['id']}  type={b['answer_type']}  text={b['transcription_fr']!r}")

        print("\n=== curate_vocab_review ===")
        pool = await asyncpg.create_pool(_db_url(), min_size=1, max_size=2)
        try:
            for direction, label in [(-1, "easy/level-down"), (0, "medium/steady"), (1, "hard/level-up")]:
                result = await answer_selection_service.curate_vocab_review(
                    interaction_id='INT202607041224',
                    user_level=100,
                    db_pool=pool,
                    cycle_level_direction=direction,
                    selection_mode='single',
                    count=4
                )
                print(f"[vocab_review {label}] difficulty={result['difficulty']} config={result['config']}")
                for a in result['answers']:
                    print(f"    id={a['id']}  type={a['answer_type']}  text={a['transcription_fr']!r}")
        finally:
            await pool.close()

        print("\n=== find_frame_swap_distractors ===")
        for lvl in (100, 40):
            distractors = await find_frame_swap_distractors(
                conn, "J'ai un entityAnimal", user_level=lvl, count=4
            )
            print(f"[frameswap @level{lvl}]")
            for d in distractors:
                print(f"    id={d['id']}  type={d['answer_type']}  text={d['transcription_fr']!r}")
    finally:
        await conn.close()


asyncio.run(main())
