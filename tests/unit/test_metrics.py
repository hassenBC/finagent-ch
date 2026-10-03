import math

import pytest

from eval.metrics import (
    bootstrap_ci,
    is_relevant,
    ndcg_at_k,
    page_coverage,
    paired_bootstrap,
    recall_at_k,
    reciprocal_rank,
)
from finagent.retrieval.types import Hit


def H(doc, a, b):
    return Hit(chunk_id=1, doc_id=doc, page_start=a, page_end=b, content="", score=0, source="x")


def test_is_relevant_uses_page_span_overlap_within_the_same_doc():
    pages = {(1, 48)}
    assert is_relevant(H(1, 47, 49), pages)
    assert is_relevant(H(1, 48, 48), pages)
    assert not is_relevant(H(1, 49, 50), pages)
    assert not is_relevant(H(2, 48, 48), pages)


def test_recall_and_mrr():
    rel = [False, False, True, False]
    assert recall_at_k(rel, 2) == 0.0 and recall_at_k(rel, 3) == 1.0
    assert reciprocal_rank(rel) == pytest.approx(1 / 3)
    assert reciprocal_rank([False] * 5) == 0.0
    assert reciprocal_rank([False, False, True], k=2) == 0.0


def test_ndcg():
    assert ndcg_at_k([True, False], 10, n_relevant=1) == pytest.approx(1.0)
    assert ndcg_at_k([False, True], 10, n_relevant=1) == pytest.approx(1 / math.log2(3))
    assert ndcg_at_k([True, True, False], 10, n_relevant=2) == pytest.approx(1.0)
    assert ndcg_at_k([False] * 3, 10, n_relevant=2) == 0.0


def test_page_coverage():
    primary = {(1, 10), (2, 20)}
    assert page_coverage([H(1, 10, 10)], primary, 5) == 0.5
    assert page_coverage([H(1, 10, 10), H(2, 19, 20)], primary, 5) == 1.0
    assert page_coverage([H(1, 10, 10), H(2, 20, 20)], primary, 1) == 0.5


def test_bootstrap_ci_brackets_the_mean_and_is_deterministic():
    vals = [1.0] * 30 + [0.0] * 20
    m, lo, hi = bootstrap_ci(vals)
    assert m == pytest.approx(0.6) and lo < m < hi
    assert (m, lo, hi) == bootstrap_ci(vals)


def test_paired_bootstrap_detects_a_real_gap_and_a_null():
    a = [1.0] * 40 + [0.0] * 10
    b = [0.0] * 10 + [1.0] * 40  # same mean after reordering
    m, lo, hi = paired_bootstrap(a, [0.0] * 50)
    assert lo > 0
    m, lo, hi = paired_bootstrap(a, b)
    assert m == pytest.approx(0.0) and lo < 0 < hi
