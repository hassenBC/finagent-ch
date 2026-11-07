from eval.eval_extraction import classify, matches


def test_matches_uses_relative_tolerance():
    assert matches(100.0, 100.4) and not matches(100.0, 100.6)
    assert matches(0.0, 0.0)


def test_classify_outcomes():
    others = {"net_profit": 763.8, "operating_income": 3860.9}
    assert classify(None, None, None, others) == "both_empty"
    assert classify(None, 5.0, None, others) == "spurious"
    assert classify(763.8, None, None, others) == "missing"
    assert classify(763.8, 763.8, 1022.3, others) == "correct"
    assert classify(763.8, -763.8, 1022.3, others) == "sign"
    assert classify(763.8, 763_800.0, 1022.3, others) == "unit_scale"
    assert classify(107.49, 107_488.9, None, others) == "unit_scale"
    assert classify(763.8, 1022.3, 1022.3, others) == "prior_year"
    assert classify(763.8, 3860.9, 1022.3, others) == "wrong_metric"
    assert classify(763.8, 500.0, 1022.3, others) == "wrong_value"


def test_gold_values_parse_strictly():
    import pytest

    from finagent.figures.load_gold import parse_value

    assert parse_value("1'310'709") == 1310709 and parse_value(" 15.2 ") == 15.2
    assert parse_value("") is None
    for bad in ["15,2", "1,234"]:
        with pytest.raises(ValueError):
            parse_value(bad)
