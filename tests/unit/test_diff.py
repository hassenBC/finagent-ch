from eval.diff import diff, passed


def test_pass_rules_per_kind():
    assert passed("retrieval", {"recall@5": 1.0}) and not passed("retrieval", {"recall@5": 0.0})
    assert passed("rag", {"answerable": True, "em_any": 1.0})
    assert not passed("rag", {"answerable": True, "em_any": 0.0})
    assert passed("rag", {"answerable": True, "has_correct_citation": True})  # non-numeric item
    assert passed("rag", {"answerable": False, "abstain": True})
    assert not passed("rag", {"answerable": False, "abstain": False})
    assert passed("judge", {"faithful": 1.0}) and not passed("judge", {"faithful": 0.0})


def test_diff_finds_regressions_and_fixes_hidden_by_equal_averages():
    a = {"q1": True, "q2": True, "q3": False, "q4": True}
    b = {"q1": True, "q2": False, "q3": True, "q4": True}  # same average, two changes
    types = {"q1": "x", "q2": "table", "q3": "text", "q4": "x"}
    d = diff(a, b, types)
    assert d["regressions"] == [("q2", "table")] and d["fixes"] == [("q3", "text")]
    assert d["pass_a"] == d["pass_b"] == 3 and d["only_a"] == d["only_b"] == []


def test_items_missing_on_one_side_are_reported():
    d = diff({"q1": True, "q2": True}, {"q1": True, "q3": False}, {})
    assert d["only_a"] == ["q2"] and d["only_b"] == ["q3"]
