import pytest

from finagent.retrieval.fts import detect_ts_config
from finagent.retrieval.fusion import rrf
from finagent.retrieval.types import Hit


def H(cid, source="fts"):
    return Hit(
        chunk_id=cid, doc_id=1, page_start=1, page_end=1, content="", score=0.0, source=source
    )


def test_rrf_scores_and_order():
    a = [H(1), H(2), H(3)]
    b = [H(3, "vector"), H(1, "vector"), H(4, "vector")]
    out = rrf([a, b], k=60)
    scores = {h.chunk_id: h.score for h in out}
    assert scores[1] == pytest.approx(1 / 61 + 1 / 62)
    assert scores[3] == pytest.approx(1 / 63 + 1 / 61)
    assert [h.chunk_id for h in out] == [1, 3, 2, 4]  # 1 > 3 > 2 (rank 2, one list) > 4
    assert all(h.source == "fused" for h in out)


def test_rrf_single_list_keeps_order_and_empty_is_ok():
    assert [h.chunk_id for h in rrf([[H(5), H(6)]])] == [5, 6]
    assert rrf([[], []]) == []


@pytest.mark.parametrize(
    ("q", "cfg"),
    [
        ("What was Vontobel's CET1 ratio at the end of 2025?", "english"),
        ("Quel était le ratio CET1 de la BCV fin 2025 ?", "french"),
        ("Combien de membres compte la Direction générale ?", "french"),
    ],
)
def test_detect_ts_config(q, cfg):
    assert detect_ts_config(q) == cfg
