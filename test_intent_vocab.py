#!/usr/bin/env python3
# ============================================================================
# test_intent_vocab.py - Unit tests for intent vocab rules + slot planner
# ============================================================================
# Pure-logic (no DB, no .env):
#   intent_vocab.rules:   increment, apply_evidence, is_owned, pack ratios/state
#   intent_vocab.planner: plan_slots (spread, f weighting, saturation, errors)
#
# RUN: cd ~/Desktop/tuje-analyze-api ; source venv/bin/activate ; python test_intent_vocab.py
# ============================================================================

from intent_vocab.rules import (
    PASSIVE_INC,
    ACTIVE_VOICE_INC,
    ACTIVE_BUTTON_INC,
    WordScore,
    PackWord,
    increment,
    apply_evidence,
    apply_downgrade,
    is_owned,
    weight_of,
    pack_ratios,
    pack_state,
)
from intent_vocab.planner import Candidate, plan_slots, PlannerError, candidate_value
from intent_vocab.engine import (
    build_candidates,
    candidates_from_pool,
    candidates_to_pool,
    describe_candidates,
    has_unowned_target,
    pack_words_from,
)
from intent_vocab.hook import evidence_ids, newly_added_ids, vocab_ids_from_found


def no_consecutive(ids, last=None):
    prev = last
    for i in ids:
        if i == prev:
            return False
        prev = i
    return True


def approx(a, b):
    return abs(a - b) < 1e-9


def test_increment():
    print("=" * 60); print("TEST 1 - increment per kind/mode"); print("=" * 60)
    for mode in ("voice", "multipleButtons", "singleButton"):
        assert increment("passive", mode) == PASSIVE_INC == 50
    assert increment("active", "voice") == ACTIVE_VOICE_INC == 50
    assert increment("active", "multipleButtons") == ACTIVE_BUTTON_INC == 25
    assert increment("active", "singleButton") == 0
    assert increment("active", "voice", {"level": 3}) == 50  # context unused in v1
    for bad in (("bogus", "voice"), ("active", "bogus")):
        try:
            increment(*bad)
            raise AssertionError(f"expected ValueError for {bad}")
        except ValueError:
            pass
    print("  PASS")


def test_apply_evidence():
    print("=" * 60); print("TEST 2 - apply_evidence"); print("=" * 60)
    scores = {"a": WordScore(80, 90)}
    d = apply_evidence(scores, ["a", "b", "b"], ["a", "b"], "voice")
    assert d == {"a": (20, 10), "b": (50, 50)}, d          # cap + duplicate once
    assert scores["a"] == WordScore(100, 100)
    assert scores["b"] == WordScore(50, 50)                 # created
    d = apply_evidence(scores, ["a"], ["a"], "voice")
    assert d == {"a": (0, 0)}                               # already maxed
    d = apply_evidence(scores, [], ["b"], "multipleButtons")
    assert d == {"b": (0, 25)} and scores["b"] == WordScore(50, 75)
    d = apply_evidence(scores, ["c"], ["c"], "singleButton")
    assert d == {"c": (50, 0)} and scores["c"] == WordScore(50, 0)
    print("  PASS")


def test_is_owned():
    print("=" * 60); print("TEST 3 - is_owned"); print("=" * 60)
    assert is_owned(WordScore(100, 100), None, 1)
    assert not is_owned(WordScore(100, 99), None, 1)
    assert not is_owned(WordScore(0, 0), None, 99)
    assert is_owned(WordScore(0, 0), 3, 3)
    assert is_owned(WordScore(0, 0), 3, 5)
    assert not is_owned(WordScore(0, 0), 3, 2)
    print("  PASS")


def test_pack_ratios():
    print("=" * 60); print("TEST 4 - pack_ratios"); print("=" * 60)
    assert weight_of(None) == 0.5 and weight_of(-2) == 0 and weight_of(0.8) == 0.8
    words = [
        PackWord("a", 1.0, 100, 100, True),   # owned
        PackWord("b", None, 100, 0, False),   # understood, weight 0.5
        PackWord("c", 0.5, 0, 0, False),
    ]
    r = pack_ratios(words)
    assert approx(r["understood_ratio"], 1.5 / 2.0), r
    assert approx(r["owned_ratio"], 1.0 / 2.0), r
    assert approx(r["avg_passive"], (100 + 50) / 2.0), r
    assert approx(r["avg_active"], 100 / 2.0), r
    # owned via level counts as understood even with passive < 100
    r = pack_ratios([PackWord("x", 1.0, 0, 0, True)])
    assert r["understood_ratio"] == 1.0 and r["owned_ratio"] == 1.0
    zero = {"understood_ratio": 0.0, "owned_ratio": 0.0, "avg_passive": 0.0, "avg_active": 0.0}
    assert pack_ratios([]) == zero
    assert pack_ratios([PackWord("z", -1, 100, 100, True)]) == zero
    print("  PASS")


def test_pack_state():
    print("=" * 60); print("TEST 5 - pack_state thresholds + never downgrade"); print("=" * 60)
    r = lambda u, o: {"understood_ratio": u, "owned_ratio": o}
    assert pack_state(r(0.69, 0.0), None, None) == "in_progress"
    assert pack_state(r(0.7, 0.0), None, None) == "discovered"
    assert pack_state(r(0.7, 0.7), None, None) == "owned"
    assert pack_state(r(0.5, 0.0), 0.5, None) == "discovered"
    assert pack_state(r(0.9, 0.9), 0.95, None) == "in_progress"
    assert pack_state(r(0.0, 0.0), None, "discovered") == "discovered"
    assert pack_state(r(0.8, 0.0), None, "owned") == "owned"
    assert pack_state(r(0.8, 0.8), None, "discovered") == "owned"
    print("  PASS")


def _pack():
    return {
        "A": PackWord("A", 1.0, 0, 0, False),
        "B": PackWord("B", 0.5, 0, 0, False),
        "C": PackWord("C", 0.2, 0, 0, False),
    }


def _cands():
    return [
        Candidate("cA", {"A"}, {"A"}, "voice"),
        Candidate("cAB", {"A", "B"}, set(), "multipleButtons"),
        Candidate("cB", {"B"}, {"B"}, "voice"),
        Candidate("cC", {"C"}, {"C"}, "voice"),
    ]


def test_planner_spread():
    print("=" * 60); print("TEST 6 - planner: 3 words x 4 candidates, 7 slots"); print("=" * 60)
    words = _pack()
    res = plan_slots(words, _cands(), [], set(), 7)
    print("  plan:", res.ids)
    assert len(res.ids) == 7
    assert res.ids[0] == "cA"                       # heaviest, lowest-scored word
    assert res.ids == ["cA", "cAB", "cB", "cA", "cC", "cB", "cC"], res.ids
    assert set(res.ids) == {"cA", "cAB", "cB", "cC"}  # simulated credit spreads picks
    assert no_consecutive(res.ids)
    assert res.warnings == []
    # caller's scores untouched by the simulation
    assert all(w.passive == 0 and w.active == 0 for w in words.values())
    # last_played_id blocks a first-slot repeat
    res = plan_slots(_pack(), _cands(), ["cA"], set(), 3, last_played_id="cA")
    assert res.ids[0] != "cA" and len(res.ids) == 3 and no_consecutive(res.ids, "cA")
    # single candidate: repeats allowed since there's no alternative
    res = plan_slots(_pack(), [Candidate("only", {"A"}, {"A"}, "voice")], [], set(), 3, "only")
    assert res.ids == ["only"] * 3
    assert plan_slots(_pack(), _cands(), [], set(), 0).ids == []
    print("  PASS")


def test_planner_f_weighting():
    print("=" * 60); print("TEST 7 - planner: voice outranks buttons once passive is 100"); print("=" * 60)
    words = {"X": PackWord("X", 1.0, 100, 0, False)}
    cands = [
        Candidate("a_btn", {"X"}, {"X"}, "multipleButtons"),
        Candidate("b_single", {"X"}, {"X"}, "singleButton"),
        Candidate("z_voice", {"X"}, {"X"}, "voice"),
    ]
    res = plan_slots(words, cands, [], set(), 1)
    assert res.ids == ["z_voice"], res.ids          # 100 vs 50 vs 0, despite id order
    print("  PASS")


def test_planner_saturated():
    print("=" * 60); print("TEST 8 - planner: saturated pack"); print("=" * 60)
    words = {
        "A": PackWord("A", 1.0, 100, 100, True),
        "B": PackWord("B", 1.0, 10, 0, True),        # owned by level
    }
    cands = [
        Candidate("c1", {"A"}, {"A"}, "voice"),
        Candidate("c2", {"B"}, {"B"}, "voice"),
        Candidate("c3", {"A", "B"}, set(), "multipleButtons"),
    ]
    res = plan_slots(words, cands, ["c1"], {"c2"}, 5)
    print("  plan:", res.ids, res.warnings)
    assert len(res.ids) == 5 and no_consecutive(res.ids)
    assert res.warnings == ["pack saturated"]
    assert res.ids[0] == "c3"                       # not played, not seen
    print("  PASS")


def test_owned_ignores_evidence():
    print("=" * 60); print("TEST 10 - owned words ignore positive evidence"); print("=" * 60)
    scores = {"o": WordScore(30, 0)}
    d = apply_evidence(scores, ["o", "n", "ghost"], ["o", "n", "ghost"], "voice",
                       owned_ids={"o", "ghost"})
    assert d == {"n": (50, 50)}, d
    assert scores["o"] == WordScore(30, 0)          # unchanged
    assert "ghost" not in scores                    # no entry created
    assert apply_evidence(scores, ["o"], [], "voice", owned_ids=None) == {"o": (50, 0)}
    print("  PASS")


def test_downgrade():
    print("=" * 60); print("TEST 11 - apply_downgrade + downgraded ownership"); print("=" * 60)
    # owned by level, with some passive score
    scores = {"lvl": WordScore(80, 40), "low": WordScore(20, 10)}
    assert is_owned(scores["lvl"], 2, 3)
    d = apply_downgrade(scores, ["lvl", "lvl", "low", "new"])
    assert d == {"lvl": -50, "low": -20, "new": 0}, d   # duplicate once, floor 0
    assert scores["lvl"] == WordScore(30, 40)
    assert scores["low"] == WordScore(0, 10)            # active untouched
    assert scores["new"] == WordScore(0, 0)             # created, 0 stays 0
    assert not is_owned(scores["lvl"], 2, 3, downgraded=True)
    assert is_owned(scores["lvl"], 2, 3, downgraded=False)
    # score ownership survives the downgraded flag
    assert is_owned(WordScore(100, 100), 2, 3, downgraded=True)
    # downgrade hits a score-owned word too
    s = {"full": WordScore(100, 100)}
    assert apply_downgrade(s, ["full"], amount=30) == {"full": -30}
    assert s["full"] == WordScore(70, 100) and not is_owned(s["full"], None, 1)
    assert apply_downgrade(s, ["full"], amount=0) == {"full": 0}
    print("  PASS")


def test_planner_errors():
    print("=" * 60); print("TEST 9 - planner: no candidates"); print("=" * 60)
    try:
        plan_slots(_pack(), [], [], set(), 3)
        raise AssertionError("expected PlannerError")
    except PlannerError:
        pass
    assert plan_slots(_pack(), [], [], set(), 0).ids == []
    print("  PASS")


def test_hook_evidence_ids():
    print("=" * 60); print("TEST 12 - hook: evidence id sets from verdict/mode"); print("=" * 60)
    found = '[{"id": "V1", "transcription_fr": "chat"}, {"id": "V2"}, {"transcription_fr": "x"}]'
    args = (["I1", None], ["E1", "I1"], found, "S1", ["A1", "A2"])
    for verdict in ("perfect", "good"):
        assert evidence_ids(verdict, "voice", *args) == ({"I1", "E1"}, {"V1", "V2"})
        assert evidence_ids(verdict, "multipleButtons", *args) == ({"I1", "E1"}, {"S1", "A1", "A2"})
        assert evidence_ids(verdict, "singleButton", *args) == ({"I1", "E1"}, set())
    for verdict in ("wrong", "not_understood", None):
        for mode in ("voice", "multipleButtons", "singleButton"):
            assert evidence_ids(verdict, mode, *args) == (set(), set())
    assert evidence_ids("perfect", None, *args) == (set(), set())        # unknown mode
    assert evidence_ids("perfect", "multipleButtons", None, None, None, None, None) == (set(), set())
    assert evidence_ids("good", "multipleButtons", [], [], None, None, ["A1"]) == (set(), {"A1"})
    # vocabulary_found shapes: text, already-decoded list, NULL, junk
    assert vocab_ids_from_found([{"id": "V9"}]) == {"V9"}
    assert vocab_ids_from_found(None) == set()
    assert vocab_ids_from_found("not json") == set()
    assert vocab_ids_from_found('{"id": "V1"}') == set()
    print("  PASS")


def test_hook_template_slot():
    print("=" * 60); print("TEST 14 - hook: template answer credits only the realized slot word"); print("=" * 60)
    # "c'est ma entityFamilyMember": 3 variants A/B/C + fixed word F ("c'est").
    answer_vocab = ["F", "A", "B", "C"]
    slot = {"A", "B", "C"}
    inter, expected = ["I1"], ["A"]

    # multipleButtons, selected = variant A (correct) → active = {A, F}
    p, a = evidence_ids("good", "multipleButtons", inter, expected, None, "A", answer_vocab, slot)
    assert p == {"I1", "A"} and a == {"A", "F"}, (p, a)
    # wrong variant selected (evaluate turns it into a wrong verdict) → no credit at all
    for verdict in ("wrong", "not_understood"):
        assert evidence_ids(verdict, "multipleButtons", inter, expected, None, "B",
                            answer_vocab, slot) == (set(), set())
    # old client, no selected_vocab_id → no slot word, fixed word still credited
    _, a = evidence_ids("perfect", "multipleButtons", inter, expected, None, None, answer_vocab, slot)
    assert a == {"F"}, a
    # selected word not listed on the answer is still the realized word
    _, a = evidence_ids("perfect", "multipleButtons", inter, expected, None, "A", ["F", "B"], slot)
    assert a == {"A", "F"}, a

    # voice: the adjuster found F + A (+ B said too) → only the expected slot word
    found = [{"id": "F"}, {"id": "A"}, {"id": "B"}]
    _, a = evidence_ids("good", "voice", inter, expected, found, None, answer_vocab, slot)
    assert a == {"F", "A"}, a
    # voice, no expected words on the interaction → every slot word said
    _, a = evidence_ids("good", "voice", inter, [], [{"id": "F"}, {"id": "B"}], None, answer_vocab, slot)
    assert a == {"F", "B"}, a
    # wrong verdict → nothing
    assert evidence_ids("wrong", "voice", inter, expected, found, None, answer_vocab, slot) == (set(), set())

    # non-template (slot None) unchanged: every answer word + selected; every found word
    _, a = evidence_ids("good", "multipleButtons", inter, expected, None, "S", answer_vocab, None)
    assert a == {"F", "A", "B", "C", "S"}, a
    _, a = evidence_ids("good", "voice", inter, expected, found, None, answer_vocab, None)
    assert a == {"F", "A", "B"}, a
    # template whose slot set came back empty behaves like non-template for fixed words
    _, a = evidence_ids("good", "multipleButtons", inter, expected, None, "A", ["F"], set())
    assert a == {"A", "F"}, a
    print("  PASS")


def test_build_candidates():
    print("=" * 60); print("TEST 15 - engine: build_candidates + owned words value 0"); print("=" * 60)
    pack = {"P1", "P2", "SLOT"}           # SLOT = an expected word that fills a template
    rows = {
        # template quiz: fixed answer word F (not in pack), expected word SLOT in pack
        "Q_tpl": {"interaction_vocab_id": ["P1", "X"], "expected_vocab_id": ["SLOT"],
                  "answer_vocab_ids": ["F"], "mode": "multipleButtons"},
        "V_lit": {"interaction_vocab_id": ["P2"], "expected_vocab_id": [],
                  "answer_vocab_ids": ["P1", "P2", None], "mode": "voice"},
        "S_one": {"interaction_vocab_id": ["P1"], "expected_vocab_id": ["SLOT"],
                  "answer_vocab_ids": ["P2"], "mode": "singleButton"},
        "N_none": {"interaction_vocab_id": None, "expected_vocab_id": None,
                   "answer_vocab_ids": None, "mode": None},
    }
    cands = {c.id: c for c in build_candidates(rows, pack)}
    assert [c for c in sorted(cands)] == ["N_none", "Q_tpl", "S_one", "V_lit"]
    q = cands["Q_tpl"]
    assert q.passive_ids == {"P1", "SLOT"} and q.active_ids == {"SLOT"}, q   # slot word active
    v = cands["V_lit"]
    assert v.passive_ids == {"P2"} and v.active_ids == {"P1", "P2"}, v
    s = cands["S_one"]
    assert s.passive_ids == {"P1", "SLOT"} and s.active_ids == set(), s      # singleButton: passive only
    n = cands["N_none"]
    assert n.passive_ids == set() and n.active_ids == set() and n.mode == "voice"

    # pack_words_from: all words kept, owned flags from scores / level / downgraded
    meta = {"P1": {"weight": 1.0, "level_own": None},
            "P2": {"weight": 0.5, "level_own": 50},
            "SLOT": {"weight": 0.5, "level_own": 50}}
    word_rows = {"P1": (WordScore(100, 100), False, 2, 2),       # owned by scores
                 "SLOT": (WordScore(0, 0), True, 0, 0)}          # downgraded: level no longer owns
    words = pack_words_from(meta, word_rows, session_level=100)
    assert set(words) == {"P1", "P2", "SLOT"}
    assert words["P1"].owned and words["P2"].owned and not words["SLOT"].owned
    r = pack_ratios(list(words.values()))
    assert approx(r["owned_ratio"], 1.5 / 2.0), r                 # owned words count
    # owned words contribute 0: only SLOT has value
    assert candidate_value(cands["V_lit"], words) == 0             # P1, P2 owned
    assert candidate_value(q, words) == 0.5 * 100 + 0.5 * 0.5 * 100  # SLOT passive + half active
    assert candidate_value(s, words) == 0.5 * 100                  # SLOT passive only
    rows_out = describe_candidates(list(cands.values()), words)
    assert rows_out[0]["id"] == "Q_tpl" and rows_out[-1]["value"] == 0

    # pool snapshot round-trip
    back = {c.id: c for c in candidates_from_pool(candidates_to_pool(list(cands.values())))}
    assert all(back[k] == cands[k] for k in cands), back
    print("  PASS")


def test_unowned_target_and_saturated_tiebreak():
    print("=" * 60); print("TEST 16 - skip owned-only packs + saturated tie-break"); print("=" * 60)
    owned = {"A": PackWord("A", 1.0, 100, 100, True),
             "B": PackWord("B", 0.5, 0, 0, True)}          # owned by level
    mixed = dict(owned, C=PackWord("C", 0.5, 50, 0, False))
    c_a = Candidate("b_pack", {"A"}, set(), "voice")
    c_b = Candidate("c_pack", set(), {"B"}, "multipleButtons")
    c_none = Candidate("a_none", {"X"}, {"X"}, "voice")     # touches no pack word
    c_c = Candidate("d_c", set(), {"C"}, "singleButton")    # active only, mode gives none

    # A: an intent is skipped when no candidate touches a not-owned pack word
    assert not has_unowned_target([c_a, c_b, c_none], owned)
    assert not has_unowned_target([], mixed)
    assert has_unowned_target([c_a, c_c], mixed)            # touch counts, even at value 0
    assert not has_unowned_target([c_a, c_b, c_none], mixed)

    # B: saturated pack → pack-touching candidates before non-touching ones
    res = plan_slots(owned, [c_none, c_a, c_b], [], set(), 3)
    assert res.warnings == ["pack saturated"]
    assert res.ids == ["b_pack", "c_pack", "b_pack"], res.ids   # a_none never picked
    # non-touching used only to avoid a back-to-back repeat
    res = plan_slots(owned, [c_none, c_a], [], set(), 3)
    assert res.ids == ["b_pack", "a_none", "b_pack"], res.ids
    # with value > 0 available, value still wins over the touch rule
    res = plan_slots(mixed, [c_none, c_a, Candidate("e_c", {"C"}, set(), "voice")], [], set(), 1)
    assert res.ids == ["e_c"], res.ids
    print("  PASS")


def test_newly_added_ids():
    print("=" * 60); print("TEST 13 - newly_added_ids (not-understood re-record)"); print("=" * 60)
    assert newly_added_ids(None, ["B", "A"]) == ["B", "A"]            # first record, order kept
    assert newly_added_ids(["A"], ["C", "A", "B"]) == ["C", "B"]      # only the new ones
    assert newly_added_ids([], ["A", "A", "B", "A"]) == ["A", "B"]    # dupes once
    assert newly_added_ids(["A", None], [None, "", "A", "B"]) == ["B"]  # None/empty ignored
    assert newly_added_ids(["A", "B"], ["B", "A"]) == []              # same set, reordered
    assert newly_added_ids(["A", "B"], []) == []                      # removals downgrade nothing
    assert newly_added_ids(["A"], None) == []
    assert newly_added_ids(None, None) == []
    print("  PASS")


def main():
    test_increment()
    test_apply_evidence()
    test_is_owned()
    test_pack_ratios()
    test_pack_state()
    test_planner_spread()
    test_planner_f_weighting()
    test_planner_saturated()
    test_planner_errors()
    test_owned_ignores_evidence()
    test_downgrade()
    test_hook_evidence_ids()
    test_newly_added_ids()
    test_hook_template_slot()
    test_build_candidates()
    test_unowned_target_and_saturated_tiebreak()
    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    main()
