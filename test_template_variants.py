#!/usr/bin/env python3
# ============================================================================
# test_template_variants.py - Pure tests for template-answer realization logic
# ============================================================================
# No DB, no .env: realize_en, assign_template_variants, expected_word_verdict
# from button_realization.
#
# RUN: cd ~/Desktop/tuje-analyze-api ; python3 test_template_variants.py
# ============================================================================

from button_realization import assign_template_variants, expected_word_verdict, realize_en

TOKEN = "entityFamilyMember"


def v(vocab_id):
    return {"vocab_id": vocab_id, "transcription_fr": f"C'est ma {vocab_id}",
            "transcription_en": f"It's my {vocab_id}"}


# Most common first, as realize_template_variants returns them.
VARIANTS = [v("mere"), v("soeur"), v("tante"), v("fille"), v("cousine")]


def test_realize_en():
    print("=" * 60); print("TEST 1 - realize_en"); print("=" * 60)
    assert realize_en(f"It's my {TOKEN}", TOKEN, "mother") == "It's my mother"
    assert realize_en(f"It's my {TOKEN}", TOKEN, None) is None       # can't fill → hide EN
    assert realize_en("It's my relative", TOKEN, "mother") == "It's my relative"  # token-free
    assert realize_en(None, TOKEN, "mother") is None
    assert realize_en("", TOKEN, "mother") is None
    print("  PASS")


def ids(assigned):
    return [(variant["vocab_id"], t) for variant, t in assigned]


def test_assign_with_expected():
    print("=" * 60); print("TEST 2 - correct template with expected words"); print("=" * 60)
    # One hit: it keeps the type; 3 other variants become false good (cap 4).
    got = ids(assign_template_variants("good", VARIANTS, ["soeur"]))
    assert got == [("soeur", "good"), ("mere", "false good"),
                   ("tante", "false good"), ("fille", "false good")], got

    # Two hits: both keep the type (perfect here).
    got = ids(assign_template_variants("perfect", VARIANTS, ["soeur", "fille"]))
    assert got[:2] == [("soeur", "perfect"), ("fille", "perfect")], got
    assert [t for _, t in got[2:]] == ["false good"] * 3, got

    # Expected words exist but none fits this template → most common keeps type.
    got = ids(assign_template_variants("good", VARIANTS, ["pere"]))
    assert got == [("mere", "good")], got

    # max_variants=1 → no false-good slots.
    got = ids(assign_template_variants("good", VARIANTS, ["tante"], max_variants=1))
    assert got == [("tante", "good")], got
    print("  PASS")


def test_assign_without_expected():
    print("=" * 60); print("TEST 3 - no expected words / non-correct templates"); print("=" * 60)
    for exp in (None, []):
        got = ids(assign_template_variants("good", VARIANTS, exp))
        assert got == [("mere", "good")], got
    # Wrong / false-good templates: one variant, type kept, even with expected words.
    for t in ("wrong", "false good"):
        got = ids(assign_template_variants(t, VARIANTS, ["soeur"]))
        assert got == [("mere", t)], got
    assert assign_template_variants("good", [], ["soeur"]) == []
    print("  PASS")


def test_expected_word_verdict():
    print("=" * 60); print("TEST 4 - expected_word_verdict"); print("=" * 60)
    assert expected_word_verdict(["soeur"], set()) is None          # rule doesn't apply
    assert expected_word_verdict(None, {"soeur"}) is None           # old client: unknown
    assert expected_word_verdict(["soeur"], {"soeur"}) is True
    assert expected_word_verdict(["tante"], {"soeur"}) is False
    assert expected_word_verdict([], {"soeur"}) is False            # voice: nothing recognised
    assert expected_word_verdict(["tante", "soeur"], {"soeur"}) is True
    print("  PASS")


def main():
    test_realize_en()
    test_assign_with_expected()
    test_assign_without_expected()
    test_expected_word_verdict()
    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    main()
