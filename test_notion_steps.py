#!/usr/bin/env python3
# ============================================================================
# test_notion_steps.py - Unit tests for notion step rules + slot planner
# ============================================================================
# Pure-logic (no DB, no .env):
#   notion_steps.rules:   normalize_purpose, validation, skip, progression
#   notion_steps.planner: plan_slots (from scratch, re-plans, gaps, exhaustion)
#
# RUN: cd ~/Desktop/tuje-analyze-api ; source venv/bin/activate ; python test_notion_steps.py
# ============================================================================

from notion_steps.rules import (
    Step,
    normalize_purpose,
    directly_validated,
    validated_steps,
    current_step,
    is_discovered,
)
from notion_steps.planner import plan_slots, PlannerError


AW = Step("aw", "awareness", 1)
UND = Step("und", "understand", 2)
PG = Step("pg", "practice_guided", 3)
STEPS = [PG, AW, UND]  # deliberately unsorted

CANDS = {
    "aw1": ["aw"], "aw2": ["aw"], "aw3": ["aw"],
    "und1": ["und"], "und2": ["und"], "und3": ["und"],
    "pg1": ["pg"], "pg2": ["pg"], "pg3": ["pg"],
}


def no_consecutive(ids, last=None):
    prev = last
    for i in ids:
        if i == prev:
            return False
        prev = i
    return True


def test_normalize():
    print("=" * 60); print("TEST 1 - normalize_purpose"); print("=" * 60)
    assert normalize_purpose("Practice guided") == "practice_guided"
    assert normalize_purpose("practice-free") == "practice_free"
    assert normalize_purpose("  AWARENESS ") == "awareness"
    assert normalize_purpose("learn") == "learn"
    assert normalize_purpose("awarness") is None
    assert normalize_purpose("") is None
    assert normalize_purpose(None) is None
    print("  PASS")


def test_validation():
    print("=" * 60); print("TEST 2 - validation per purpose"); print("=" * 60)
    for purpose in ("awareness", "learn"):
        s = Step("s", purpose, 1)
        assert directly_validated(s, {"s": {"a": "perfect"}}), purpose
        assert not directly_validated(s, {"s": {"a": "good"}}), purpose
        assert directly_validated(s, {"s": {"a": "good", "b": "good"}}), purpose
    for purpose in ("understand", "practice_guided"):
        s = Step("s", purpose, 1)
        assert not directly_validated(s, {"s": {"a": "perfect"}}), purpose
        assert directly_validated(s, {"s": {"a": "good", "b": "perfect"}}), purpose
    s = Step("s", "practice_free", 1)
    assert not directly_validated(s, {})
    assert directly_validated(s, {"s": {"a": "good"}})
    print("  PASS")


def test_skip():
    print("=" * 60); print("TEST 3 - skip rule"); print("=" * 60)
    v = validated_steps(STEPS, {"pg": {"x": "good", "y": "good"}})
    assert v == {"aw": "skip", "und": "skip", "pg": "direct"}, v

    v = validated_steps(STEPS, {"und": {"x": "good"}})
    assert "aw" not in v, v  # only 1 distinct interaction higher up

    v = validated_steps(STEPS, {"und": {"x": "good"}, "pg": {"x": "good"}})
    assert "aw" not in v, v  # same interaction on two higher steps counts once

    v = validated_steps(STEPS, {"und": {"x": "good"}, "pg": {"y": "good"}})
    assert v.get("aw") == "skip", v
    print("  PASS")


def test_progression():
    print("=" * 60); print("TEST 4 - current_step / is_discovered"); print("=" * 60)
    ev = {}
    assert current_step(STEPS, ev) == AW and not is_discovered(STEPS, ev)
    ev["aw"] = {"aw1": "perfect"}
    assert current_step(STEPS, ev) == UND
    ev["und"] = {"und1": "good", "und2": "good"}
    assert current_step(STEPS, ev) == PG
    ev["pg"] = {"pg1": "good", "pg2": "perfect"}
    assert current_step(STEPS, ev) is None and is_discovered(STEPS, ev)
    assert not is_discovered([], {})
    print("  PASS")


def test_plan_from_scratch():
    print("=" * 60); print("TEST 5 - plan from scratch, 7 slots"); print("=" * 60)
    r = plan_slots(STEPS, CANDS, {}, [], set(), 7)
    print(f"  plan: {r.ids}  warnings: {r.warnings}")
    assert len(r.ids) == 7
    assert r.ids[0].startswith("aw")
    assert all(i.startswith("und") for i in r.ids[1:3])
    assert all(i.startswith("pg") for i in r.ids[3:7])
    assert r.ids == ["aw1", "und1", "und2", "pg1", "pg2", "pg3", "pg1"], r.ids
    assert no_consecutive(r.ids)
    assert r.warnings == []

    # Never-seen candidates are preferred.
    r = plan_slots(STEPS, CANDS, {}, [], {"aw1"}, 1)
    assert r.ids == ["aw2"], r.ids
    print("  PASS")


def test_replan_after_wrong():
    print("=" * 60); print("TEST 6 - re-plan after wrong answer on awareness"); print("=" * 60)
    r = plan_slots(STEPS, CANDS, {}, ["aw1"], {"aw1"}, 6, last_played_id="aw1")
    print(f"  plan: {r.ids}")
    assert len(r.ids) == 6
    assert r.ids[0] == "aw2", r.ids
    assert no_consecutive(r.ids, last="aw1")
    print("  PASS")


def test_replan_after_discovery():
    print("=" * 60); print("TEST 7 - re-plan after discovery mid-cycle"); print("=" * 60)
    played = ["aw1", "und1", "und2", "pg1", "pg2"]
    ev = {
        "aw": {"aw1": "perfect"},
        "und": {"und1": "good", "und2": "good"},
        "pg": {"pg1": "good", "pg2": "good"},
    }
    assert is_discovered(STEPS, ev)
    r = plan_slots(STEPS, CANDS, ev, played, set(played), 2, last_played_id="pg2")
    print(f"  plan: {r.ids}")
    assert len(r.ids) == 2
    assert all(i.startswith("pg") for i in r.ids), r.ids
    assert r.ids[0] == "pg3", r.ids
    assert no_consecutive(r.ids, last="pg2")
    print("  PASS")


def test_content_gap():
    print("=" * 60); print("TEST 8 - step with no candidates"); print("=" * 60)
    cands = {k: v for k, v in CANDS.items() if not k.startswith("und")}
    r = plan_slots(STEPS, cands, {}, [], set(), 7)
    print(f"  plan: {r.ids}  warnings: {r.warnings}")
    assert len(r.ids) == 7
    assert any("content gap: step und" in w for w in r.warnings), r.warnings
    assert r.ids[0].startswith("aw") and all(i.startswith("pg") for i in r.ids[1:]), r.ids
    assert no_consecutive(r.ids)
    print("  PASS")


def test_exhaustion():
    print("=" * 60); print("TEST 9 - exhaustion: 1 candidate per step, 7 slots"); print("=" * 60)
    cands = {"aw1": ["aw"], "und1": ["und"], "pg1": ["pg"]}
    r = plan_slots(STEPS, cands, {}, [], set(), 7)
    print(f"  plan: {r.ids}  warnings: {r.warnings}")
    assert len(r.ids) == 7
    assert r.ids[:3] == ["aw1", "und1", "pg1"], r.ids
    assert no_consecutive(r.ids)

    # Unavoidable repeat: a single candidate overall.
    r = plan_slots([PG], {"pg1": ["pg"]}, {}, [], set(), 3)
    assert r.ids == ["pg1", "pg1", "pg1"], r.ids
    print("  PASS")


def test_errors():
    print("=" * 60); print("TEST 10 - empty candidates / steps / slots"); print("=" * 60)
    for steps, cands in ((STEPS, {}), ([], CANDS)):
        try:
            plan_slots(steps, cands, {}, [], set(), 3)
        except PlannerError:
            pass
        else:
            raise AssertionError("expected PlannerError")
    r = plan_slots(STEPS, {}, {}, [], set(), 0)
    assert r.ids == [] and r.warnings == []
    print("  PASS")


def main():
    test_normalize()
    test_validation()
    test_skip()
    test_progression()
    test_plan_from_scratch()
    test_replan_after_wrong()
    test_replan_after_discovery()
    test_content_gap()
    test_exhaustion()
    test_errors()
    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    main()
