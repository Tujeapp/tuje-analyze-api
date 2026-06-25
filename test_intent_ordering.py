#!/usr/bin/env python3
# ============================================================================
# test_intent_ordering.py - Unit tests for INTENT cycle ordering (Part 4/5)
# ============================================================================
# Pure-logic (no DB). Verifies intent ordering, esp. the cluster-twice rule
# (opposite of notion's diversify-once):
#   - select_first_interaction_intent: boredom-closest in level window
#   - select_next_interaction_intent: prefer continuing last subtopic if used once,
#     max twice per subtopic, combination-closest, fallback to exceed cap
#   - select_cycle_interactions end-to-end (intent goal): 7 picks, twice-cap honored
#
# RUN: cd ~/Desktop/tuje-analyze-api ; source venv/bin/activate ; python test_intent_ordering.py
# ============================================================================

import asyncio
from collections import Counter
from models import InteractionCandidate
from cycle_manager.interaction_selection import (
    select_first_interaction_intent,
    select_next_interaction_intent,
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
    print("=" * 60); print("TEST 1 - intent first: boredom-closest in window"); print("=" * 60)
    cands = [mk("A","S1",100,0.50,5), mk("B","S2",75,0.32,5), mk("D","S4",150,0.30,5,entry=True)]
    first = await select_first_interaction_intent(cands, 100, 0.30)
    assert first.id == "B", first.id
    print(f"  PASS: {first.id} (in-window boredom-closest, entry ignored)")


async def test_next_prefer_continue():
    print("\n" + "=" * 60)
    print("TEST 2 - next: PREFER continuing last subtopic when used once")
    print("=" * 60)
    last = mk("L","S1",100,0.30,5)
    cands = [
        mk("a","S1",100,0.31,5),   # SAME subtopic S1 (continue it) - preferred
        mk("b","S2",100,0.30,5),   # different subtopic, same combination
    ]
    # S1 used once so far
    nxt = await select_next_interaction_intent(cands, {"L"}, {"S1": 1}, last)
    assert nxt.id == "a", f"expected a (continue S1), got {nxt.id}"
    print(f"  PASS: picked {nxt.id} (continued same subtopic S1, which was used once)")


async def test_next_cap_twice():
    print("\n" + "=" * 60)
    print("TEST 3 - next: subtopic at TWICE is excluded")
    print("=" * 60)
    last = mk("L","S1",100,0.30,5)
    cands = [
        mk("a","S1",100,0.30,5),   # S1 already at 2 -> excluded
        mk("b","S2",100,0.30,7),   # S2 fresh -> chosen (only eligible)
    ]
    nxt = await select_next_interaction_intent(cands, {"L"}, {"S1": 2}, last)
    assert nxt.id == "b", f"expected b (S1 capped at twice), got {nxt.id}"
    print(f"  PASS: picked {nxt.id} (S1 excluded at twice cap)")


async def test_next_fallback_exceed():
    print("\n" + "=" * 60)
    print("TEST 4 - next: all subtopics at twice -> fallback exceeds cap")
    print("=" * 60)
    last = mk("L","S1",100,0.30,5)
    cands = [mk("a","S1",100,0.30,5), mk("b","S2",100,0.30,7)]
    nxt = await select_next_interaction_intent(cands, {"L"}, {"S1": 2, "S2": 2}, last)
    assert nxt.id in ("a", "b"), nxt.id
    print(f"  PASS: picked {nxt.id} (fallback allowed exceeding the twice cap)")


async def test_end_to_end_cluster():
    print("\n" + "=" * 60)
    print("TEST 5 - END-TO-END intent: clusters subtopics (max twice each)")
    print("=" * 60)
    # 4 subtopics, 2 interactions each (8 total) -> 7 picks, each subtopic max twice.
    cands = [
        mk("a1","S1",100,0.30,5), mk("a2","S1",100,0.30,5),
        mk("b1","S2",100,0.30,5), mk("b2","S2",100,0.30,5),
        mk("c1","S3",100,0.30,5), mk("c2","S3",100,0.30,5),
        mk("d1","S4",100,0.30,5), mk("d2","S4",100,0.30,5),
    ]
    result = await select_cycle_interactions(cands, 100, 0.30, "intent")
    print(f"  selected {len(result)}: {result}")
    assert len(result) == 7, f"expected 7, got {len(result)}"
    assert len(set(result)) == 7, f"duplicates! {result}"
    subtopic_of = {c.id: c.subtopic_id for c in cands}
    counts = Counter(subtopic_of[i] for i in result)
    print(f"  subtopic usage counts: {dict(counts)}")
    # No subtopic used more than twice (cap honored; with 4 subtopics x 2 = 8 avail, 7 picks)
    assert all(v <= 2 for v in counts.values()), f"a subtopic exceeded twice: {counts}"
    print("  PASS: 7 picks, no subtopic used more than twice (cluster-twice cap honored)")


async def main():
    await test_first()
    await test_next_prefer_continue()
    await test_next_cap_twice()
    await test_next_fallback_exceed()
    await test_end_to_end_cluster()
    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
