from eval.eval_sql import same_result


def test_extra_columns_are_allowed():
    ref = [{"bank": "efg", "value": 17.2}]
    pred = [{"bank": "efg", "value": 17.2, "doc_id": 6, "page_no": 12}]
    assert same_result(ref, pred, ordered=False)


def test_column_names_do_not_matter_and_numbers_have_tolerance():
    assert same_result([{"avg": 18.3333}], [{"avg_cet1": 18.33}], ordered=False)
    assert not same_result([{"avg": 18.3333}], [{"x": 18.5}], ordered=False)


def test_text_is_case_insensitive():
    assert same_result([{"bank": "juliusbaer"}], [{"b": "JuliusBaer"}], ordered=False)


def test_row_count_must_match():
    ref = [{"bank": "efg"}, {"bank": "bcv"}]
    assert not same_result(ref, [{"bank": "efg"}], ordered=False)
    assert not same_result(ref, ref + [{"bank": "bcge"}], ordered=False)


def test_order_only_when_asked():
    ref = [{"bank": "efg"}, {"bank": "bcv"}]
    rev = list(reversed(ref))
    assert same_result(ref, rev, ordered=False)
    assert not same_result(ref, rev, ordered=True)


def test_each_reference_row_needs_its_own_predicted_row():
    ref = [{"bank": "efg"}, {"bank": "efg"}]
    assert not same_result(ref, [{"bank": "efg"}, {"bank": "bcv"}], ordered=False)


def test_empty_results_match():
    assert same_result([], [], ordered=False)
    assert same_result([{"value": None}], [{"v": None}], ordered=False)
