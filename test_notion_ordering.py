#!/usr/bin/env python3
# ============================================================================
# test_notion_ordering.py - Unit tests for notion cycle ordering (Piece 4)
# ============================================================================
# Pure-logic (no DB):
#   step 1: select_first_interaction_notion
#   step 2: select_next_interaction_notion
#   step 3: select_cycle_interactions end-to-end (notion goal, 7 picks, subtopic rule)
#
# RUN: cd ~/Desktop/tuje-analyze-api ; source venv/bin/activate ; python test_notion_ordering.py
# ============================================================================

import asyncio
from models import InteractionCandidate
from cycle_manager.interaction_selection import (
    select_first_interaction_notion,
    select_next_interaction_notion,
    select_cycle_interactions,
)


def mk(id, subtopic, level, boredom, combination, entry=False):
    c = InteractionCandidate(
        id=id, subtopic_id=subtopic, intent_ids=[],
        boredom_rate=boredom, is_entry_point=entry,
        level_from=level, transcription_fr="",
    )
    c.combination = combination
    return c


async def test_first():
    print("=" * 60); print("TEST 1 - first: boredom-closest in level window"); print("=" * 60)
    cands = [
        mk("A","S1",100,0.50,5), mk("B","S2",75,0.32,5), mk("C","S3",50,0.10,5),
        mk("D","S4",150,0.30,5,entry=True), mk("E","S5",40,0.31,5),
    ]
    first = await select_first_interaction_notion(cands, 100, 0.30)
    assert first.id == "B", first.id
    print(f"  PASS: {first.id}")


async def test_next_fresh():
    print("\n" + "=" * 60); print("TEST 2 - next: prefers fresh subtopic"); print("=" * 60)
    last = mk("L","S1",100,0.30,5)
    cands = [mk("a","S1",100,0.30,5), mk("b","S2",100,0.31,5), mk("c","S3",100,0.30,6)]
    nxt = await select_next_interaction_notion(cands, {"L"}, {"S1"}, last)
    assert nxt.id == "b", nxt.id
    print(f"  PASS: {nxt.id}")


async def test_next_combo():
    print("\n" + "=" * 60); print("TEST 3 - next: combination-closest among fresh"); print("=" * 60)
    last = mk("L","S1",100,0.30,5)
    cands = [mk("p","S2",100,0.30,8), mk("q","S3",100,0.30,6), mk("r","S4",100,0.30,9)]
    nxt = await select_next_interaction_notion(cands, {"L"}, {"S1"}, last)
    assert nxt.id == "q", nxt.id
    print(f"  PASS: {nxt.id}")


async def test_next_fallback():
    print("\n" + "=" * 60); print("TEST 4 - next: fallback allows subtopic reuse"); print("=" * 60)
    last = mk("L","S1",100,0.30,5)
    cands = [mk("x","S1",100,0.30,5), mk("y","S2",100,0.30,7)]
    nxt = await select_next_interaction_notion(cands, {"L"}, {"S1","S2"}, last)
    assert nxt.id == "x", nxt.id
    print(f"  PASS: {nxt.id}")


async def test_end_to_end():
    print("\n" + "=" * 60)
    print("TEST 5 - select_cycle_interactions END-TO-END (notion, 7 picks)")
    print("=" * 60)
    # 10 candidates across 7 subtopics (S1..S7); enough fresh subtopics for 7 distinct,
    # then a couple of extras in already-used subtopics.
    cands = [
        mk("i1","S1",100,0.30,5),
        mk("i2","S2",100,0.30,5),
        mk("i3","S3",90,0.31,5),
        mk("i4","S4",80,0.30,6),
        mk("i5","S5",100,0.32,5),
        mk("i6","S6",70,0.30,5),
        mk("i7","S7",100,0.30,6),
        mk("i8","S1",100,0.30,5),   # extra in S1
        mk("i9","S2",100,0.30,5),   # extra in S2
        mk("i10","S3",100,0.30,5),  # extra in S3
    ]
    result = await select_cycle_interactions(cands, cycle_level=100, cycle_boredom=0.30, cycle_goal="notion")
    print(f"  selected {len(result)} interactions: {result}")
    assert len(result) == 7, f"expected 7, got {len(result)}"
    assert len(set(result)) == 7, f"duplicates! {result}"
    # With 7 distinct subtopics available, the 7 picks should each be from a different
    # subtopic (no reuse needed).
    subtopic_of = {c.id: c.subtopic_id for c in cands}
    used_subs = [subtopic_of[i] for i in result]
    print(f"  subtopics used: {used_subs}")
    assert len(set(used_subs)) == 7, f"expected 7 distinct subtopics, got {len(set(used_subs))}: {used_subs}"
    print("  PASS: 7 distinct interactions, 7 distinct subtopics (subtopic rule respected)")


async def test_end_to_end_forced_reuse():
    print("\n" + "=" * 60)
    print("TEST 6 - END-TO-END with only 4 subtopics (forces reuse to reach 7)")
    print("=" * 60)
    # Only 4 subtopics but 8 interactions -> must reuse subtopics to reach 7.
    cands = [
        mk("a1","S1",100,0.30,5), mk("a2","S1",100,0.30,5),
        mk("b1","S2",100,0.30,5), mk("b2","S2",100,0.30,5),
        mk("c1","S3",100,0.30,5), mk("c2","S3",100,0.30,5),
        mk("d1","S4",100,0.30,5), mk("d2","S4",100,0.30,5),
    ]
    result = await select_cycle_interactions(cands, 100, 0.30, "notion")
    print(f"  selected {len(result)}: {result}")
    assert len(result) == 7, f"expected 7, got {len(result)}"
    assert len(set(result)) == 7, f"duplicates! {result}"
    print("  PASS: reached 7 distinct interactions despite only 4 subtopics (reuse fallback worked)")


async def main():
    await test_first()
    await test_next_fresh()
    await test_next_combo()
    await test_next_fallback()
    await test_end_to_end()
    await test_end_to_end_forced_reuse()
    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
