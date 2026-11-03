#!/usr/bin/env python3
# ============================================================================
# test_scoring_level0.py - Unit tests for level-0 binary scoring
# ============================================================================
# Pure-logic (no DB, no .env):
#   interaction_scoring.binary_level0_score
#
# RUN: cd ~/Desktop/tuje-analyze-api ; source venv/bin/activate ; python test_scoring_level0.py
# ============================================================================

from interaction_scoring import binary_level0_score


def test_correct_verdicts():
    print("=" * 60); print("TEST 1 - perfect/good → 100"); print("=" * 60)
    for v in ("perfect", "good"):
        assert binary_level0_score(v) == 100, v
    print("  PASS")


def test_other_verdicts():
    print("=" * 60); print("TEST 2 - anything else → 0 (exact match only)"); print("=" * 60)
    for v in ("wrong", "false good", "not_understood", None, "", "correct", "Perfect", " good"):
        assert binary_level0_score(v) == 0, repr(v)
    print("  PASS")


def test_int():
    print("=" * 60); print("TEST 3 - always an int"); print("=" * 60)
    for v in ("perfect", "wrong", None):
        assert type(binary_level0_score(v)) is int, repr(v)
    print("  PASS")


def main():
    test_correct_verdicts()
    test_other_verdicts()
    test_int()
    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    main()
